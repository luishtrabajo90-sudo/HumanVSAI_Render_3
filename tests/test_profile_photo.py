import io
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from PIL import Image

from app import create_app
from app.admin_auth import ADMIN_INITIAL_PASSWORDS
from app.extensions import db
from app.models import AdminUser, PlayerProfile
from app.visitor_session import purge_expired_guests


TEST_PASSWORD = "photo-test-password"


class TestConfig:
    TESTING = True
    ENFORCE_VISITOR_SESSION_IN_TESTS = True
    SECRET_KEY = "photo-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = ""
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    ADMIN_BOOTSTRAP_PASSWORD = TEST_PASSWORD


class ProfilePhotoTests(unittest.TestCase):
    def setUp(self):
        self.photo_dir = tempfile.mkdtemp()
        TestConfig.PROFILE_PHOTO_FOLDER = self.photo_dir
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        shutil.rmtree(self.photo_dir)

    @staticmethod
    def image_file(image_format="JPEG", size=(320, 240), exif=False):
        buffer = io.BytesIO()
        image = Image.new("RGB", size, (30, 120, 210))
        metadata = None
        if exif:
            metadata = Image.Exif()
            metadata[274] = 6
            metadata[270] = "private metadata"
        if metadata is None:
            image.save(buffer, image_format)
        else:
            image.save(buffer, image_format, exif=metadata)
        buffer.seek(0)
        return buffer

    @staticmethod
    def csrf(client):
        with client.session_transaction() as flask_session:
            return flask_session.get("admin_csrf_token")

    def guest(self, name="PhotoGuest1"):
        client = self.app.test_client()
        client.get("/")
        response = client.post("/api/visitor-session", json={"name": name})
        self.assertEqual(response.status_code, 201)
        return client

    def admin(self, username="emartinez"):
        client = self.app.test_client()
        client.get("/")
        response = client.post(
            "/api/visitor-session",
            json={
                "name": username,
                "password": ADMIN_INITIAL_PASSWORDS[username],
                "csrf_token": self.csrf(client),
            },
        )
        self.assertEqual(response.status_code, 200)
        if response.get_json().get("password_change_required"):
            changed = client.post(
                "/admin/first-login",
                data={
                    "new_password": TEST_PASSWORD,
                    "confirm_password": TEST_PASSWORD,
                    "csrf_token": self.csrf(client),
                },
            )
            self.assertEqual(changed.status_code, 302)
        return client

    def upload(self, client, file_data=None, filename="photo.jpg", content_type="image/jpeg"):
        token = self.csrf(client)
        return client.post(
            "/api/profile/photo",
            data={"photo": (file_data or self.image_file(), filename, content_type)},
            headers={"X-CSRF-Token": token} if token else {},
            content_type="multipart/form-data",
        )

    def test_upload_requires_session_and_csrf(self):
        anonymous = self.app.test_client()
        self.assertEqual(self.upload(anonymous).status_code, 401)
        guest = self.guest()
        response = guest.post(
            "/api/profile/photo",
            data={"photo": (self.image_file(), "photo.jpg", "image/jpeg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 403)

    def test_upload_reencodes_without_exif_and_serves_current_profile(self):
        client = self.guest()
        response = self.upload(client, self.image_file(exif=True))
        self.assertEqual(response.status_code, 200)
        profile = response.get_json()["profile"]
        self.assertTrue(profile["photo_url"])
        player = PlayerProfile.query.filter_by(name="PhotoGuest1").one()
        path = os.path.join(self.photo_dir, player.photo_filename)
        self.assertTrue(os.path.isfile(path))
        with Image.open(path) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(len(image.getexif()), 0)
            self.assertLessEqual(max(image.size), 512)
        served = client.get(profile["photo_url"])
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.mimetype, "image/webp")
        served.close()

    def test_replace_is_atomic_and_delete_removes_file(self):
        client = self.guest()
        self.upload(client)
        player = PlayerProfile.query.filter_by(name="PhotoGuest1").one()
        old_path = os.path.join(self.photo_dir, player.photo_filename)
        replacement = self.upload(client, self.image_file("PNG"), "photo.png", "image/png")
        self.assertEqual(replacement.status_code, 200)
        db.session.refresh(player)
        new_path = os.path.join(self.photo_dir, player.photo_filename)
        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(os.path.exists(new_path))
        removed = client.delete(
            "/api/profile/photo",
            headers={"X-CSRF-Token": self.csrf(client)},
        )
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(os.path.exists(new_path))

    def test_false_mime_oversize_and_corrupt_images_are_rejected(self):
        client = self.guest()
        fake = self.upload(client, io.BytesIO(b"<svg></svg>"), "fake.jpg", "image/jpeg")
        self.assertEqual(fake.status_code, 400)
        mismatched = self.upload(client, self.image_file("PNG"), "fake.jpg", "image/jpeg")
        self.assertEqual(mismatched.status_code, 400)
        wrong_mime = self.upload(client, self.image_file(), "photo.gif", "image/gif")
        self.assertEqual(wrong_mime.status_code, 400)
        oversized = self.upload(
            client,
            io.BytesIO(b"x" * (2 * 1024 * 1024 + 1)),
            "large.jpg",
            "image/jpeg",
        )
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(os.listdir(self.photo_dir), [])

    def test_two_sessions_can_only_replace_their_own_photo(self):
        first = self.guest("PhotoOne1")
        second = self.guest("PhotoTwo2")
        first_profile = self.upload(first).get_json()["profile"]
        second_profile = self.upload(second, self.image_file("PNG"), "two.png", "image/png").get_json()["profile"]
        self.assertNotEqual(first_profile["photo_url"], second_profile["photo_url"])
        first.delete("/api/profile/photo", headers={"X-CSRF-Token": self.csrf(first)})
        served = second.get(second_profile["photo_url"])
        self.assertEqual(served.status_code, 200)
        served.close()

    def test_guest_expiry_and_manual_admin_delete_remove_photo_file(self):
        guest = self.guest("PurgePhoto1")
        self.upload(guest)
        player = PlayerProfile.query.filter_by(name="PurgePhoto1").one()
        path = os.path.join(self.photo_dir, player.photo_filename)
        player.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()
        self.assertEqual(purge_expired_guests(), 1)
        self.assertFalse(os.path.exists(path))

        guest = self.guest("DeletePhoto2")
        self.upload(guest)
        player = PlayerProfile.query.filter_by(name="DeletePhoto2").one()
        path = os.path.join(self.photo_dir, player.photo_filename)
        admin = self.admin()
        response = admin.post(
            f"/admin/players/{player.id}/delete",
            data={"csrf_token": self.csrf(admin)},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(os.path.exists(path))

    def test_admin_cannot_create_persistent_player_photo(self):
        client = self.admin("epinto")
        response = self.upload(client)
        self.assertEqual(response.status_code, 403)
        admin = AdminUser.query.filter_by(username="epinto").one()
        self.assertIsNone(db.session.get(PlayerProfile, f"admin-{admin.id}"))
        self.assertEqual(os.listdir(self.photo_dir), [])

    def test_camera_ui_contract_and_cleanup_paths(self):
        html = self.app.test_client().get("/").get_data(as_text=True)
        with open(
            os.path.join(os.path.dirname(__file__), "..", "static", "js", "profile-photo.js"),
            encoding="utf-8",
        ) as script_file:
            script = script_file.read()
        with open(
            os.path.join(os.path.dirname(__file__), "..", "static", "js", "launcher.js"),
            encoding="utf-8",
        ) as launcher_file:
            launcher_script = launcher_file.read()
        self.assertIn("¿Deseas tomarte una foto para personalizar tu perfil dentro del juego?", html)
        self.assertIn("Sí, tomar foto", html)
        self.assertIn("No, cancelar", html)
        self.assertIn("playsinline autoplay muted", html)
        self.assertIn('facingMode: "user"', script)
        self.assertIn("stream.getTracks().forEach", script)
        self.assertIn("video.srcObject = null", script)
        self.assertIn("pagehide", script)
        self.assertIn("No fue posible acceder a la cámara.", script)
        self.assertIn('id="btnVisitorPhoto"', html)
        self.assertIn("submitRegistrationPhoto", script)
        self.assertIn("discardRegistrationPhoto", script)
        self.assertIn("ProfilePhoto.submitRegistrationPhoto()", launcher_script)
        self.assertNotIn("promptAfterLogin", launcher_script)


if __name__ == "__main__":
    unittest.main()
