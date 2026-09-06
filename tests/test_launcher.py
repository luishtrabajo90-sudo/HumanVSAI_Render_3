import unittest
from pathlib import Path

from app import create_app
from app.extensions import db
from app.game_catalog import get_game_catalog


ROOT = Path(__file__).resolve().parents[1]


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = ""
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


class LauncherAndCatalogTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def test_catalog_has_one_available_game_and_four_placeholders(self):
        catalog = get_game_catalog()
        self.assertEqual([game["id"] for game in catalog], [
            "human-vs-ai", "spot-deepfake", "password-master",
            "social-engineering", "coming-soon",
        ])
        self.assertEqual([game["status"] for game in catalog], [
            "available", "coming-soon", "coming-soon", "coming-soon", "coming-soon",
        ])

    def test_index_renders_only_human_vs_ai_launcher_card(self):
        html = self.app.test_client().get("/").get_data(as_text=True)
        self.assertIn('id="screenLauncher"', html)
        self.assertIn('data-game-id="human-vs-ai"', html)
        self.assertNotIn('data-game-id="glitch-hunter"', html)
        self.assertNotIn('data-game-id="it-challenge"', html)
        self.assertNotIn('data-game-id="email-detective"', html)
        self.assertNotIn('data-game-id="vishing-challenge"', html)
        self.assertNotIn('data-game-id="threat-hunter"', html)
        self.assertNotIn('data-game-id="coming-soon"', html)
        self.assertEqual(html.count('class="game-app '), 1)
        self.assertIn('id="screenStart"', html)
        self.assertIn('id="screenGame"', html)
        self.assertIn('js/launcher.js', html)
        self.assertNotIn('glitch-hunter.css', html)
        self.assertNotIn('it-challenge.css', html)


if __name__ == "__main__":
    unittest.main()
