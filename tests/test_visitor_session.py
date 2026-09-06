import unittest
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import AdminUser, MissionResult, PlayerProfile, VisitorSession
from app.visitor_session import purge_expired_guests


ROOT = Path(__file__).resolve().parents[1]


class TestConfig:
    TESTING = True
    ENFORCE_VISITOR_SESSION_IN_TESTS = True
    SECRET_KEY = "visitor-session-test"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = ""
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


class VisitorSessionTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def test_protected_apis_require_an_active_visitor(self):
        response = self.app.test_client().get("/api/profile")
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.get_json()["session_expired"])

    def test_start_registers_visitor_and_unlocks_game_apis(self):
        client = self.app.test_client()
        response = client.post("/api/visitor-session", json={"name": "  Daniela  "})
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertTrue(data["active"])
        self.assertEqual(data["name"], "Daniela")
        self.assertEqual(data["seconds_remaining"], 600)

        visitor = VisitorSession.query.one()
        profile = PlayerProfile.query.one()
        self.assertEqual(visitor.player_id, profile.id)
        self.assertEqual(profile.name, "Daniela")
        self.assertIsNotNone(profile.last_activity_at)
        self.assertAlmostEqual(
            (profile.expires_at - profile.created_at).total_seconds(),
            24 * 60 * 60,
            delta=2,
        )
        self.assertEqual(client.get("/api/profile").status_code, 200)

    def test_invalid_name_does_not_create_a_session(self):
        client = self.app.test_client()
        for name in ("", "x" * 31, "José", "Nombre_1"):
            with self.subTest(name=name):
                response = client.post("/api/visitor-session", json={"name": name})
                self.assertEqual(response.status_code, 400)
        self.assertEqual(VisitorSession.query.count(), 0)

    def test_visitor_name_accepts_internal_spaces(self):
        client = self.app.test_client()
        response = client.post(
            "/api/visitor-session",
            json={"name": "  Carlos Moron  "},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["name"], "Carlos Moron")
        self.assertEqual(PlayerProfile.query.one().name, "Carlos Moron")

    def test_visitor_can_resume_with_same_name_after_logout(self):
        first = self.app.test_client()
        second = self.app.test_client()
        self.assertEqual(
            first.post("/api/visitor-session", json={"name": "Carlos1"}).status_code,
            201,
        )
        first.post("/api/visitor-session/end")

        resumed = second.post(
            "/api/visitor-session",
            json={"name": "Carlos1"},
        )
        self.assertEqual(resumed.status_code, 201)
        self.assertTrue(resumed.get_json()["active"])
        self.assertEqual(VisitorSession.query.count(), 1)
        self.assertEqual(PlayerProfile.query.count(), 1)

    def test_elapsed_time_is_shared_across_multiple_logins(self):
        first = self.app.test_client()
        second = self.app.test_client()
        first.post("/api/visitor-session", json={"name": "Tiempo Compartido"})
        visitor = VisitorSession.query.one()
        visitor.started_at = datetime.now(timezone.utc) - timedelta(seconds=125)
        db.session.commit()

        first.post("/api/visitor-session/end")
        db.session.refresh(visitor)
        self.assertGreaterEqual(visitor.consumed_seconds, 124)
        self.assertLess(visitor.consumed_seconds, 127)

        resumed = second.post(
            "/api/visitor-session",
            json={"name": "Tiempo Compartido"},
        )
        self.assertEqual(resumed.status_code, 201)
        self.assertGreaterEqual(resumed.get_json()["seconds_remaining"], 473)
        self.assertLessEqual(resumed.get_json()["seconds_remaining"], 476)
        self.assertEqual(VisitorSession.query.count(), 1)

    def test_visitor_cannot_restart_after_consuming_ten_minutes(self):
        first = self.app.test_client()
        second = self.app.test_client()
        first.post("/api/visitor-session", json={"name": "Tiempo Agotado"})
        visitor = VisitorSession.query.one()
        visitor.started_at = datetime.now(timezone.utc) - timedelta(seconds=600)
        visitor.expires_at = datetime.now(timezone.utc)
        db.session.commit()

        exhausted = second.post(
            "/api/visitor-session",
            json={"name": "Tiempo Agotado"},
        )
        self.assertEqual(exhausted.status_code, 403)
        self.assertTrue(exhausted.get_json()["session_expired"])
        db.session.refresh(visitor)
        self.assertEqual(visitor.consumed_seconds, 600)

    def test_visitor_names_are_case_sensitive(self):
        first = self.app.test_client()
        second = self.app.test_client()
        self.assertEqual(
            first.post("/api/visitor-session", json={"name": "Carlos1"}).status_code,
            201,
        )
        self.assertEqual(
            second.post("/api/visitor-session", json={"name": "carlos1"}).status_code,
            201,
        )
        self.assertEqual(
            {profile.name for profile in PlayerProfile.query.all()},
            {"Carlos1", "carlos1"},
        )

    def test_guest_retention_boundary_and_idempotent_cleanup(self):
        now = datetime.now(timezone.utc)
        keep = PlayerProfile(
            id="keep",
            name="Keep2359",
            created_at=now - timedelta(hours=23, minutes=59),
            last_activity_at=now,
            expires_at=now + timedelta(minutes=1),
        )
        purge = PlayerProfile(
            id="purge",
            name="Purge2400",
            created_at=now - timedelta(hours=24),
            last_activity_at=now - timedelta(hours=1),
            expires_at=now,
        )
        db.session.add_all([keep, purge])
        db.session.add(MissionResult(
            player_id=purge.id,
            run_token="expired-result",
            game_id="human-vs-ai",
        ))
        db.session.commit()
        self.assertEqual(purge_expired_guests(now), 1)
        self.assertIsNotNone(db.session.get(PlayerProfile, keep.id))
        self.assertIsNone(db.session.get(PlayerProfile, purge.id))
        self.assertEqual(MissionResult.query.filter_by(player_id=purge.id).count(), 0)
        self.assertEqual(purge_expired_guests(now), 0)

    def test_cleanup_never_deletes_admin_or_legacy_admin_named_profile(self):
        now = datetime.now(timezone.utc)
        admin = AdminUser.query.filter_by(username="emartinez").first()
        if admin is None:
            admin = AdminUser(
                username="emartinez",
                full_name="Esdras Martinez",
                password_hash="not-used",
                active=True,
            )
        admin.created_at = now - timedelta(days=2)
        legacy = PlayerProfile(
            id="legacy-admin-visitor",
            name="EMARTINEZ",
            created_at=now - timedelta(days=2),
            last_activity_at=now - timedelta(days=2),
            expires_at=now - timedelta(days=1),
        )
        db.session.add_all([admin, legacy])
        db.session.commit()
        purge_expired_guests(now)
        self.assertIsNotNone(db.session.get(AdminUser, admin.id))
        self.assertIsNotNone(db.session.get(PlayerProfile, legacy.id))

    def test_request_hook_purges_expired_guest(self):
        now = datetime.now(timezone.utc)
        player = PlayerProfile(
            id="request-expired",
            name="RequestExpired1",
            expires_at=now - timedelta(seconds=1),
        )
        db.session.add(player)
        db.session.commit()
        self.app.extensions["guest_cleanup_last_run"] = 0
        self.assertEqual(self.app.test_client().get("/").status_code, 200)
        self.assertIsNone(db.session.get(PlayerProfile, player.id))

    def test_cleanup_cli_is_idempotent(self):
        now = datetime.now(timezone.utc)
        db.session.add(PlayerProfile(
            id="cli-expired",
            name="CliExpired1",
            expires_at=now - timedelta(seconds=1),
        ))
        db.session.commit()
        runner = self.app.test_cli_runner()
        first = runner.invoke(args=["purge-expired-guests"])
        second = runner.invoke(args=["purge-expired-guests"])
        self.assertEqual(first.exit_code, 0)
        self.assertIn("Purged guest profiles: 1", first.output)
        self.assertIn("Purged guest profiles: 0", second.output)

    def test_startup_purges_expired_guest_from_existing_database(self):
        handle, path = tempfile.mkstemp(suffix=".db")
        os.close(handle)

        class FileConfig(TestConfig):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{path}"

        try:
            first_app = create_app(FileConfig)
            with first_app.app_context():
                db.session.add(PlayerProfile(
                    id="startup-expired",
                    name="StartupExpired1",
                    expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                ))
                db.session.commit()
                db.session.remove()
                db.engine.dispose()
            second_app = create_app(FileConfig)
            with second_app.app_context():
                self.assertIsNone(db.session.get(PlayerProfile, "startup-expired"))
                db.session.remove()
                db.engine.dispose()
        finally:
            os.remove(path)

    def test_registered_visitor_cannot_rename_profile(self):
        client = self.app.test_client()
        client.post("/api/visitor-session", json={"name": "NombreReservado"})
        response = client.patch("/api/profile", json={"name": "NombreNuevo"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("queda fijado", response.get_json()["error"])
        self.assertEqual(PlayerProfile.query.one().name, "NombreReservado")

    def test_manual_logout_closes_the_record_and_clears_access(self):
        client = self.app.test_client()
        client.post("/api/visitor-session", json={"name": "Miguel"})
        response = client.post("/api/visitor-session/end")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ended"])

        visitor = VisitorSession.query.one()
        self.assertEqual(visitor.end_reason, "manual")
        self.assertIsNotNone(visitor.ended_at)
        self.assertEqual(client.get("/api/profile").status_code, 401)

    def test_expired_session_is_closed_by_the_server(self):
        client = self.app.test_client()
        client.post("/api/visitor-session", json={"name": "Laura"})
        visitor = VisitorSession.query.one()
        visitor.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()

        status = client.get("/api/visitor-session").get_json()
        self.assertFalse(status["active"])
        db.session.refresh(visitor)
        self.assertEqual(visitor.end_reason, "expired")
        self.assertEqual(client.get("/api/profile").status_code, 401)

    def test_read_only_ranking_includes_registered_visitors(self):
        first = self.app.test_client()
        second = self.app.test_client()
        first.post("/api/visitor-session", json={"name": "Ana"})
        second.post("/api/visitor-session", json={"name": "Bruno"})

        ana = PlayerProfile.query.filter_by(name="Ana").one()
        bruno = PlayerProfile.query.filter_by(name="Bruno").one()
        ana.total_points = 250
        ana.mission_count = 2
        bruno.total_points = 500
        bruno.mission_count = 1
        db.session.commit()

        response = first.get("/api/visitor-ranking").get_json()
        ranking = response["ranking"]
        self.assertEqual([item["name"] for item in ranking], ["Bruno", "Ana"])
        self.assertEqual([item["points"] for item in ranking], [500, 250])
        self.assertTrue(all(item["active"] for item in ranking))
        self.assertEqual(response["active_count"], 2)

    def test_online_players_returns_all_active_players_with_projection_data(self):
        clients = [self.app.test_client() for _ in range(5)]
        for index, client in enumerate(clients):
            self.assertEqual(
                client.post("/api/visitor-session", json={"name": f"Player{index}"}).status_code,
                201,
            )
        VisitorSession.query.filter_by(normalized_name="Player0").one().current_image_url = (
            "https://images.example.test/current.jpg"
        )
        player = VisitorSession.query.filter_by(normalized_name="Player0").one()
        player.current_score = 325
        player.current_round = 2
        player.current_total_rounds = 5
        player.current_hits = 1
        player.current_misses = 1
        player.round_expires_at = datetime.now(timezone.utc) + timedelta(seconds=15)
        db.session.commit()

        response = self.app.test_client().get("/api/online-players?projection=1")
        self.assertEqual(response.status_code, 200)
        players = response.get_json()["players"]
        self.assertEqual([player["name"] for player in players], [
            "Player0", "Player1", "Player2", "Player3",
        ])
        self.assertGreater(players[0]["round_seconds_remaining"], 0)
        self.assertEqual(players[0]["image_url"], "https://images.example.test/current.jpg")
        self.assertEqual(players[0]["points"], 325)
        self.assertEqual(players[0]["round"], 2)
        self.assertEqual(players[0]["total_rounds"], 5)
        self.assertEqual(players[0]["hits"], 1)
        self.assertEqual(players[0]["misses"], 1)
        self.assertIsNone(players[1]["image_url"])

        second_screen = self.app.test_client().get("/api/online-players?projection=2")
        self.assertEqual(second_screen.status_code, 200)
        self.assertEqual(second_screen.get_json()["projection"], 2)
        self.assertEqual(
            [player["name"] for player in second_screen.get_json()["players"]],
            ["Player4"],
        )

    def test_templates_and_script_expose_complete_visitor_flow(self):
        html = self.app.test_client().get("/").get_data(as_text=True)
        launcher = (ROOT / "static/js/launcher.js").read_text(encoding="utf-8")
        for element_id in (
            "visitorLoginModal",
            "visitorNameInput",
            "launcherSessionTimer",
            "gameSessionClock",
            "gameSessionName",
            "gameSessionTimer",
            "btnLauncherLogout",
            "btnOpenVisitorRanking",
            "btnClearVisitorRanking",
            "visitorRankingAdminActions",
            "visitorRankingModal",
            "sessionExpiredModal",
            "btnAcknowledgeSessionExpired",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertNotIn('id="visitorSessionHud"', html)
        self.assertNotIn('id="btnVisitorLogout"', html)
        self.assertIn('requestJson("/api/visitor-session"', launcher)
        self.assertIn('el("gameSessionTimer").textContent = value', launcher)
        self.assertIn('var timedSession = active && !visitorSession.admin', launcher)
        self.assertIn("function renderSessionClocks(timedSession)", launcher)
        self.assertIn("var startVisible = !el(\"screenStart\").classList.contains(\"hide\")", launcher)
        self.assertIn("!(timedSession && launcherVisible)", launcher)
        self.assertIn("!(timedSession && !launcherVisible && !startVisible)", launcher)
        self.assertIn("renderSessionClocks(false)", launcher)
        self.assertIn("if (!visitorSession || visitorSession.admin) return", launcher)
        self.assertIn('requestJson("/api/visitor-session/end"', launcher)
        self.assertIn(
            'el("btnLauncherHome").addEventListener("click", function () {\n'
            "    endVisitorSession(false);\n"
            "  });",
            launcher,
        )
        self.assertIn('requestJson("/api/visitor-ranking"', launcher)
        self.assertIn('requestJson("/api/visitor-ranking/clear"', launcher)
        self.assertIn("visitorSession.can_clear_visitor_history", launcher)
        self.assertIn("setInterval(loadVisitorRanking, 2000)", launcher)
        self.assertIn("showSessionExpired(message)", launcher)
        self.assertIn('el("btnStart").addEventListener("click", function () {', launcher)
        self.assertNotIn("if (visitorSession) open();", launcher)
        self.assertIn("endVisitorSession: endVisitorSession", launcher)


if __name__ == "__main__":
    unittest.main()
