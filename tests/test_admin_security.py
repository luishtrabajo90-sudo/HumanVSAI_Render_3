import unittest

from app import create_app
from app.admin_auth import (
    ADMIN_ACCOUNTS,
    ADMIN_INITIAL_PASSWORDS,
    ROLE_ADMIN,
    SHARED_PASSWORD_ADMINS,
)
from app.extensions import db
from app.gamification import purge_admin_game_data
from app.models import (
    AdminAudit,
    AdminUser,
    ImagePair,
    MissionResult,
    PlayerProfile,
    VisitorSession,
)
from app.visitor_session import VISITOR_HISTORY_ADMINS


TEST_CHANGED_PASSWORD = "local-test-password-987"


class TestConfig:
    TESTING = True
    ENFORCE_VISITOR_SESSION_IN_TESTS = True
    SECRET_KEY = "admin-security-test"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = ""
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    ADMIN_BOOTSTRAP_PASSWORD = TEST_CHANGED_PASSWORD


class AdminSecurityTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    @staticmethod
    def csrf(client):
        with client.session_transaction() as flask_session:
            return flask_session["admin_csrf_token"]

    def login(self, client, username="lhernandez", password=None):
        normalized = username.strip().casefold()
        password = password or ADMIN_INITIAL_PASSWORDS[normalized]
        client.get("/admin/login")
        response = client.post(
            "/admin/login",
            data={
                "username": username,
                "password": password,
                "csrf_token": self.csrf(client),
            },
        )
        if response.status_code == 302 and response.headers["Location"] == "/admin/first-login":
            response = client.post(
                "/admin/first-login",
                data={
                    "new_password": TEST_CHANGED_PASSWORD,
                    "confirm_password": TEST_CHANGED_PASSWORD,
                    "csrf_token": self.csrf(client),
                },
            )
        return response

    def test_bootstrap_creates_exact_allowlist_with_hashes(self):
        admins = AdminUser.query.order_by(AdminUser.username).all()
        self.assertEqual({admin.username for admin in admins}, set(ADMIN_ACCOUNTS))
        self.assertEqual(
            SHARED_PASSWORD_ADMINS,
            {"cmoron", "lhernandez", "emartinez", "hpinto"},
        )
        self.assertEqual({admin.full_name for admin in admins}, set(ADMIN_ACCOUNTS.values()))
        self.assertTrue(all(admin.active for admin in admins))
        self.assertTrue(all(admin.role == ROLE_ADMIN for admin in admins))
        for admin in admins:
            self.assertNotIn(ADMIN_INITIAL_PASSWORDS[admin.username], admin.password_hash)
            self.assertEqual(
                admin.password_change_required,
                admin.username not in SHARED_PASSWORD_ADMINS,
            )

    def test_all_authorized_admins_can_login_case_insensitively_after_first_change(self):
        for username in ADMIN_ACCOUNTS:
            with self.subTest(username=username):
                client = self.app.test_client()
                response = self.login(client, f"  {username.upper()}  ")
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/admin/pairs")
                page = client.get("/admin/pairs")
                self.assertEqual(page.status_code, 200)
                self.assertIn(ADMIN_ACCOUNTS[username], page.get_data(as_text=True))

    def test_admin_login_with_initial_password_requires_first_change(self):
        client = self.app.test_client()
        client.get("/admin/login")
        response = client.post(
            "/admin/login",
            data={
                "username": "admin",
                "password": "admin",
                "csrf_token": self.csrf(client),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/first-login")
        self.assertEqual(client.get("/admin/pairs").status_code, 302)

        changed = client.post(
            "/admin/first-login",
            data={
                "new_password": TEST_CHANGED_PASSWORD,
                "confirm_password": TEST_CHANGED_PASSWORD,
                "csrf_token": self.csrf(client),
            },
        )
        self.assertEqual(changed.status_code, 302)
        self.assertEqual(changed.headers["Location"], "/admin/pairs")
        self.assertFalse(AdminUser.query.filter_by(username="admin").one().password_change_required)
        self.assertEqual(client.get("/admin/pairs").status_code, 200)

    def test_all_authorized_admins_can_login_from_existing_modal_backend(self):
        for username in ADMIN_ACCOUNTS:
            with self.subTest(username=username):
                client = self.app.test_client()
                client.get("/")
                player_count = PlayerProfile.query.count()
                response = client.post(
                    "/api/visitor-session",
                    json={
                        "name": f"  {username.upper()}  ",
                        "password": ADMIN_INITIAL_PASSWORDS[username],
                        "csrf_token": self.csrf(client),
                    },
                )
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertTrue(payload["admin"])
                if username in SHARED_PASSWORD_ADMINS:
                    self.assertTrue(payload["active"])
                    self.assertTrue(payload["unlimited_time"])
                    self.assertNotIn("password_change_required", payload)
                else:
                    self.assertTrue(payload["password_change_required"])
                    self.assertEqual(payload["redirect_url"], "/admin/first-login")
                    self.assertFalse(payload["active"])
                self.assertEqual(PlayerProfile.query.count(), player_count)
                expected_profile_status = (
                    200 if username in SHARED_PASSWORD_ADMINS else 401
                )
                self.assertEqual(
                    client.get("/api/profile").status_code,
                    expected_profile_status,
                )

    def test_repeated_admin_login_never_hits_visitor_name_uniqueness(self):
        client = self.app.test_client()
        for _ in range(3):
            client.get("/")
            response = client.post(
                "/api/visitor-session",
                json={
                    "name": "emartinez",
                    "password": ADMIN_INITIAL_PASSWORDS["emartinez"],
                    "csrf_token": self.csrf(client),
                },
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(PlayerProfile.query.filter(PlayerProfile.id.like("admin-%")).count(), 0)

    def test_admin_can_logout_and_login_ten_times_with_crud_access(self):
        client = self.app.test_client()
        for index in range(10):
            response = self.login(
                client,
                username="emartinez",
                password=ADMIN_INITIAL_PASSWORDS["emartinez"],
            )
            self.assertEqual(response.status_code, 302)
            token = self.csrf(client)
            self.assertEqual(
                client.post(
                    "/admin/settings",
                    data={"timer_seconds": str(20 + index), "csrf_token": token},
                ).status_code,
                302,
            )
            self.assertEqual(
                client.post(
                    "/api/visitor-session/end",
                    json={"csrf_token": token},
                ).status_code,
                200,
            )

    def test_same_admin_can_use_two_clients_simultaneously(self):
        self.login(self.app.test_client(), username="cmoron")
        clients = [self.app.test_client(), self.app.test_client()]
        for client in clients:
            client.get("/")
            response = client.post(
                "/api/visitor-session",
                json={
                    "name": "cmoron",
                    "password": ADMIN_INITIAL_PASSWORDS["cmoron"],
                    "csrf_token": self.csrf(client),
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get("/admin/players").status_code, 200)

    def test_admin_can_play_without_persisting_score_or_profile(self):
        pair = ImagePair(
            category="Prueba",
            ai_image_path="uploads/pairs/test/a.jpg",
            real_image_path="uploads/pairs/test/b.jpg",
            ai_image_class="IA",
            real_image_class="REAL",
            tell="Detalle",
            realtip="Pista",
            active=True,
        )
        db.session.add(pair)
        db.session.commit()
        client = self.app.test_client()
        self.login(client, username="dcanache")
        self.assertEqual(client.post("/api/game/start").status_code, 200)
        self.assertEqual(client.get("/api/game/round").status_code, 200)
        self.assertEqual(client.post("/api/game/answer", json={"choice": "ia"}).status_code, 200)
        with client.session_transaction() as flask_session:
            flask_session["i"] = len(flask_session["deck"])
        result = client.get("/api/game/result")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.get_json()["profile"]["points"], 0)
        self.assertEqual(result.get_json()["profile"]["missions"], 0)
        self.assertTrue(result.get_json()["profile"]["admin"])
        self.assertEqual(client.post("/api/game/start").status_code, 200)
        self.assertEqual(client.get("/admin/pairs").status_code, 200)
        admin = AdminUser.query.filter_by(username="dcanache").one()
        self.assertIsNone(PlayerProfile.query.filter_by(id=f"admin-{admin.id}").first())
        self.assertEqual(MissionResult.query.count(), 0)

    def test_bad_admin_credentials_do_not_fall_through_to_guest(self):
        client = self.app.test_client()
        client.get("/")
        response = client.post(
            "/api/visitor-session",
            json={
                "name": "emartinez",
                "password": "incorrect",
                "csrf_token": self.csrf(client),
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "Usuario o contraseña incorrectos.")
        self.assertEqual(PlayerProfile.query.count(), 0)

    def test_admin_can_login_after_guest_without_reloading_page(self):
        client = self.app.test_client()
        client.get("/")
        original_token = self.csrf(client)
        self.assertEqual(
            client.post("/api/visitor-session", json={"name": "PrimeraInvitada"}).status_code,
            201,
        )
        self.assertEqual(
            client.post("/api/visitor-session/end", json={}).status_code,
            200,
        )
        response = client.post(
            "/api/visitor-session",
            json={
                "name": "lhernandez",
                "password": ADMIN_INITIAL_PASSWORDS["lhernandez"],
                "csrf_token": original_token,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["admin"])
        self.assertTrue(response.get_json()["active"])
        self.assertNotIn("password_change_required", response.get_json())

    def test_similar_admin_name_remains_password_free_guest(self):
        client = self.app.test_client()
        response = client.post("/api/visitor-session", json={"name": "emartinez2"})
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.get_json().get("admin", False))
        self.assertEqual(PlayerProfile.query.one().name, "emartinez2")

    def test_non_javascript_form_uses_admin_branch_for_hpinto(self):
        client = self.app.test_client()
        client.get("/")
        response = client.post(
            "/api/visitor-session",
            data={
                "name": " HPINTO ",
                "password": "12345677",
                "csrf_token": self.csrf(client),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/pairs")
        self.assertEqual(PlayerProfile.query.filter(PlayerProfile.id.like("admin-%")).count(), 0)

    def test_bad_password_and_foreign_user_share_generic_failure(self):
        wrong_password = self.login(self.app.test_client(), password="incorrect").get_data(as_text=True)
        foreign_user = self.login(
            self.app.test_client(), username="ordinary-player", password=TEST_CHANGED_PASSWORD
        ).get_data(as_text=True)
        self.assertIn("Usuario o contraseña incorrectos.", wrong_password)
        self.assertIn("Usuario o contraseña incorrectos.", foreign_user)
        self.assertNotIn(TEST_CHANGED_PASSWORD, wrong_password + foreign_user)

    def test_admin_pages_and_mutations_are_backend_protected(self):
        client = self.app.test_client()
        self.assertEqual(client.get("/admin/pairs").status_code, 302)
        self.assertEqual(client.get("/admin/players").status_code, 302)
        self.assertEqual(client.post("/admin/settings", data={}).status_code, 401)
        self.assertEqual(client.post("/admin/pairs/new", data={}).status_code, 401)
        self.assertEqual(client.post("/admin/players/new", data={}).status_code, 401)

    def test_admin_can_change_password_and_use_new_password(self):
        client = self.app.test_client()
        self.login(client, username="admin")
        token = self.csrf(client)
        response = client.post(
            "/admin/change-password",
            data={
                "current_password": TEST_CHANGED_PASSWORD,
                "new_password": "another-password-123",
                "confirm_password": "another-password-123",
                "csrf_token": token,
            },
        )
        self.assertEqual(response.status_code, 302)
        client.post("/admin/logout", data={"csrf_token": self.csrf(client)})
        response = self.login(client, username="admin", password="another-password-123")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/pairs")

    def test_admin_can_reset_authorized_admin_password_only(self):
        client = self.app.test_client()
        self.login(client, username="admin")
        response = client.post(
            "/admin/admins/password-reset",
            data={"username": "epinto", "csrf_token": self.csrf(client)},
        )
        self.assertEqual(response.status_code, 302)
        target = AdminUser.query.filter_by(username="epinto").one()
        self.assertTrue(target.password_change_required)
        self.assertEqual(
            client.post(
                "/admin/admins/password-reset",
                data={"username": "no-autorizado", "csrf_token": self.csrf(client)},
            ).status_code,
            403,
        )

    def test_csrf_is_required_for_every_admin_mutation(self):
        client = self.app.test_client()
        self.login(client)
        self.assertEqual(client.post("/admin/settings", data={"timer_seconds": "20"}).status_code, 403)
        self.assertEqual(client.post("/admin/players/new", data={"name": "Ana"}).status_code, 403)
        self.assertEqual(client.post("/admin/logout", data={}).status_code, 403)

    def test_admin_can_manage_content_and_players_with_audit(self):
        client = self.app.test_client()
        self.login(client)
        token = self.csrf(client)
        settings = client.post(
            "/admin/settings",
            data={"timer_seconds": "24", "csrf_token": token},
        )
        self.assertEqual(settings.status_code, 302)
        created_pair = client.post(
            "/admin/pairs/new",
            data={
                "category": "Seguridad",
                "tell": "Detalle",
                "realtip": "Pista",
                "active": "on",
                "csrf_token": token,
            },
        )
        self.assertEqual(created_pair.status_code, 302)
        self.assertEqual(ImagePair.query.count(), 1)

        created_player = client.post(
            "/admin/players/new",
            data={"name": "JugadorUno", "role": "admin", "csrf_token": token},
        )
        self.assertEqual(created_player.status_code, 302)
        player = PlayerProfile.query.filter_by(name="JugadorUno").one()
        self.assertFalse(hasattr(player, "role"))
        edited_player = client.post(
            f"/admin/players/{player.id}/edit",
            data={"name": "JugadorEditado", "is_admin": "1", "csrf_token": token},
        )
        self.assertEqual(edited_player.status_code, 302)
        self.assertEqual(db.session.get(PlayerProfile, player.id).name, "JugadorEditado")
        actions = {(row.action, row.entity_type) for row in AdminAudit.query.all()}
        self.assertIn(("update", "settings"), actions)
        self.assertIn(("create", "image_pair"), actions)
        self.assertIn(("create", "player"), actions)
        self.assertIn(("update", "player"), actions)

    def test_player_validation_and_duplicate_detection(self):
        client = self.app.test_client()
        self.login(client)
        token = self.csrf(client)
        self.assertEqual(
            client.post("/admin/players/new", data={"name": "", "csrf_token": token}).status_code,
            400,
        )
        client.post("/admin/players/new", data={"name": "Carlos1", "csrf_token": token})
        case_variant = client.post(
            "/admin/players/new", data={"name": "carlos1", "csrf_token": token}
        )
        self.assertEqual(case_variant.status_code, 302)
        duplicate = client.post(
            "/admin/players/new", data={"name": "Carlos1", "csrf_token": token}
        )
        self.assertEqual(duplicate.status_code, 409)
        invalid = client.post(
            "/admin/players/new", data={"name": "Carlos_1", "csrf_token": token}
        )
        self.assertEqual(invalid.status_code, 400)
        spaced = client.post(
            "/admin/players/new", data={"name": "Carlos Moron", "csrf_token": token}
        )
        self.assertEqual(spaced.status_code, 302)
        self.assertIsNotNone(PlayerProfile.query.filter_by(name="Carlos Moron").first())

    def test_logout_and_guest_login_clear_admin_authority(self):
        client = self.app.test_client()
        self.login(client)
        token = self.csrf(client)
        self.assertEqual(
            client.post("/admin/logout", data={"csrf_token": token}).status_code,
            302,
        )
        self.assertEqual(client.get("/admin/pairs").status_code, 302)

        self.login(client)
        guest = client.post("/api/visitor-session", json={"name": "InvitadoSinClave"})
        self.assertEqual(guest.status_code, 201)
        self.assertEqual(client.get("/admin/pairs").status_code, 302)
        self.assertEqual(client.get("/api/profile").status_code, 200)

    def test_precreated_player_is_reused_by_guest_flow(self):
        client = self.app.test_client()
        self.login(client)
        client.post(
            "/admin/players/new",
            data={"name": "JugadorPreparado", "csrf_token": self.csrf(client)},
        )
        player_id = PlayerProfile.query.filter_by(name="JugadorPreparado").one().id
        guest = client.post("/api/visitor-session", json={"name": "JugadorPreparado"})
        self.assertEqual(guest.status_code, 201)
        self.assertEqual(PlayerProfile.query.count(), 1)
        self.assertEqual(PlayerProfile.query.one().id, player_id)

    def test_admin_can_delete_guest_and_name_can_be_recreated(self):
        guest = self.app.test_client()
        self.assertEqual(
            guest.post("/api/visitor-session", json={"name": "DeleteMe1"}).status_code,
            201,
        )
        player = PlayerProfile.query.filter_by(name="DeleteMe1").one()
        admin = self.app.test_client()
        self.login(admin, username="epinto")
        response = admin.post(
            f"/admin/players/{player.id}/delete",
            data={"csrf_token": self.csrf(admin)},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(db.session.get(PlayerProfile, player.id))
        self.assertEqual(VisitorSession.query.filter_by(player_id=player.id).count(), 0)
        recreated = self.app.test_client().post(
            "/api/visitor-session", json={"name": "DeleteMe1"}
        )
        self.assertEqual(recreated.status_code, 201)

    def test_history_clear_capability_is_limited_to_requested_admins(self):
        self.assertEqual(
            VISITOR_HISTORY_ADMINS,
            {"cmoron", "hpinto", "lhernandez", "emartinez"},
        )
        for username in ADMIN_ACCOUNTS:
            with self.subTest(username=username):
                client = self.app.test_client()
                self.login(client, username=username)
                session_data = client.get("/api/visitor-session").get_json()
                self.assertTrue(session_data["unlimited_time"])
                self.assertNotIn("seconds_remaining", session_data)
                self.assertEqual(
                    session_data["can_clear_visitor_history"],
                    username in VISITOR_HISTORY_ADMINS,
                )

    def test_guest_and_unlisted_admin_cannot_clear_visitor_history(self):
        guest = self.app.test_client()
        guest.post("/api/visitor-session", json={"name": "NoBorrar"})
        self.assertEqual(
            guest.post("/api/visitor-ranking/clear", json={}).status_code,
            401,
        )

        admin = self.app.test_client()
        self.login(admin, username="epinto")
        denied = admin.post(
            "/api/visitor-ranking/clear",
            json={"csrf_token": self.csrf(admin)},
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(VisitorSession.query.count(), 1)
        self.assertEqual(PlayerProfile.query.filter_by(name="NoBorrar").count(), 1)

    def test_authorized_admin_can_clear_visitors_results_and_ranking(self):
        first = self.app.test_client()
        second = self.app.test_client()
        first.post("/api/visitor-session", json={"name": "BorrarUno"})
        second.post("/api/visitor-session", json={"name": "BorrarDos"})
        players = PlayerProfile.query.order_by(PlayerProfile.name).all()
        for index, player in enumerate(players):
            db.session.add(MissionResult(
                player_id=player.id,
                run_token=f"clear-result-{index}",
                game_id="human-vs-ai",
                score=100,
            ))
        db.session.commit()

        admin = self.app.test_client()
        self.login(admin, username="cmoron")
        cleared = admin.post(
            "/api/visitor-ranking/clear",
            json={"csrf_token": self.csrf(admin)},
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.get_json()["deleted_visitors"], 2)
        self.assertEqual(cleared.get_json()["deleted_results"], 2)
        self.assertEqual(VisitorSession.query.count(), 0)
        self.assertEqual(MissionResult.query.count(), 0)
        self.assertEqual(PlayerProfile.query.count(), 0)
        self.assertEqual(AdminUser.query.count(), len(ADMIN_ACCOUNTS))
        self.assertEqual(
            AdminAudit.query.filter_by(
                action="clear",
                entity_type="visitor_ranking",
            ).count(),
            1,
        )
        ranking = admin.get("/api/visitor-ranking").get_json()
        self.assertEqual(ranking["ranking"], [])
        self.assertEqual(ranking["active_count"], 0)

    def test_authorized_history_clear_requires_csrf(self):
        admin = self.app.test_client()
        self.login(admin, username="lhernandez")
        self.assertEqual(
            admin.post("/api/visitor-ranking/clear", json={}).status_code,
            403,
        )

    def test_player_delete_cannot_delete_admin_game_profile(self):
        client = self.app.test_client()
        self.login(client)
        client.get("/api/profile")
        admin = AdminUser.query.filter_by(username="lhernandez").one()
        response = client.post(
            f"/admin/players/admin-{admin.id}/delete",
            data={"csrf_token": self.csrf(client)},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(db.session.get(PlayerProfile, f"admin-{admin.id}"))

    def test_legacy_admin_game_records_are_purged(self):
        admin = AdminUser.query.filter_by(username="emartinez").one()
        profile = PlayerProfile(
            id=f"admin-{admin.id}",
            name=admin.full_name,
            total_points=900,
            mission_count=3,
        )
        db.session.add(profile)
        db.session.flush()
        profile_id = profile.id
        db.session.add(MissionResult(
            player_id=profile.id,
            run_token="legacy-admin-result",
            game_id="human-vs-ai",
            mission_id="",
            score=900,
            duration_seconds=30,
            completed=True,
        ))
        db.session.commit()
        self.assertEqual(purge_admin_game_data(), [])
        self.assertIsNone(db.session.get(PlayerProfile, profile_id))
        self.assertEqual(MissionResult.query.count(), 0)

    def test_legacy_admin_full_name_is_excluded_without_admin_id_prefix(self):
        profile = PlayerProfile(
            id="legacy-esdras-profile",
            name=ADMIN_ACCOUNTS["emartinez"],
            total_points=1200,
            mission_count=4,
        )
        db.session.add(profile)
        db.session.flush()
        profile_id = profile.id
        db.session.add(MissionResult(
            player_id=profile_id,
            run_token="legacy-full-name-result",
            game_id="human-vs-ai",
            mission_id="",
            score=1200,
            duration_seconds=20,
            completed=True,
        ))
        db.session.commit()

        self.assertEqual(purge_admin_game_data(), [])
        self.assertIsNone(db.session.get(PlayerProfile, profile_id))
        self.assertEqual(MissionResult.query.count(), 0)

    def test_modal_exposes_accessible_conditional_password_field(self):
        html = self.app.test_client().get("/").get_data(as_text=True)
        self.assertIn('id="visitorAdminPassword" hidden aria-hidden="true"', html)
        self.assertIn('for="visitorPasswordInput"', html)
        self.assertIn('autocomplete="current-password"', html)
        self.assertIn('id="adminUsernameData"', html)
        for username in ADMIN_ACCOUNTS:
            self.assertIn(username, html)

    def test_admin_routes_receive_shared_admin_page_theme(self):
        client = self.app.test_client()
        login_page = client.get("/admin/login").get_data(as_text=True)
        self.assertIn('<body class="admin-page">', login_page)
        self.assertIn("admin-blue-1", login_page)
        game_page = client.get("/").get_data(as_text=True)
        self.assertIn('<body class="game-page">', game_page)
        self.assertNotIn('<body class="admin-page">', game_page)


if __name__ == "__main__":
    unittest.main()
