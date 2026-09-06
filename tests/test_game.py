import unittest

from flask import session

from app import create_app
from app.extensions import db
from app.game import load_ai_fest_questions
from app.gamification import record_result
from app.models import GameImage, ImagePair, PlayerProfile


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = ""
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


class GameFlowTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def add_pair(self, class_a="IA", class_b="REAL", suffix="one"):
        pair = ImagePair(
            category="Prueba",
            ai_image_path=f"uploads/pairs/{suffix}/a.jpg",
            real_image_path=f"uploads/pairs/{suffix}/b.jpg",
            ai_image_class=class_a,
            real_image_class=class_b,
            tell="Pista",
            realtip="Consejo",
            active=True,
        )
        db.session.add(pair)
        db.session.commit()
        return pair

    def add_single_image(self, image_class="IA", suffix="one"):
        image = GameImage(
            category="Prueba",
            image_url=f"https://images.example.test/{suffix}.jpg",
            image_class=image_class,
            source_name="Fuente de prueba",
            active=True,
        )
        db.session.add(image)
        db.session.commit()
        return image

    def set_round(self, client, pair, image_index=0):
        with client.session_transaction() as session:
            session.update({
                "deck": [pair.id],
                "i": 0,
                "score": 0,
                "streak": 0,
                "best": 0,
                "hits": 0,
                "answered": False,
                "image_index": image_index,
            })

    def test_each_image_can_be_classified_as_ai_or_real(self):
        cases = [
            ("IA", "REAL", 0, "ia"),
            ("IA", "REAL", 1, "real"),
            ("REAL", "IA", 0, "real"),
            ("REAL", "IA", 1, "ia"),
        ]
        for index, (class_a, class_b, image_index, expected) in enumerate(cases):
            with self.subTest(class_a=class_a, class_b=class_b):
                pair = self.add_pair(class_a, class_b, str(index))
                client = self.app.test_client()
                self.set_round(client, pair, image_index)
                response = client.post("/api/game/answer", json={"choice": expected})
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertTrue(data["correct"])
                self.assertEqual(data["correct_choice"], expected)
                self.assertEqual(data["image"]["isAI"], (class_a, class_b)[image_index] == "IA")
                db.session.delete(pair)
                db.session.commit()

    def test_selected_image_changes_authoritative_answer(self):
        pair = self.add_pair("IA", "REAL")
        client = self.app.test_client()
        self.set_round(client, pair, image_index=1)
        wrong = client.post("/api/game/answer", json={"choice": "ia"})
        self.assertFalse(wrong.get_json()["correct"])
        self.assertEqual(wrong.get_json()["correct_choice"], "real")
        self.assertTrue(wrong.get_json()["summary"])

    def test_correct_choice_covers_correct_wrong_inverse_and_timeout(self):
        pair = self.add_pair("IA", "REAL", "answer-states")
        cases = (
            (1, "/api/game/answer", {"choice": "ia"}, False, "real"),
            (1, "/api/game/answer", {"choice": "real"}, True, "real"),
            (0, "/api/game/answer", {"choice": "ia"}, True, "ia"),
            (0, "/api/game/timeout", None, False, "ia"),
        )
        for image_index, endpoint, payload, expected_correct, expected_choice in cases:
            with self.subTest(endpoint=endpoint, payload=payload):
                client = self.app.test_client()
                self.set_round(client, pair, image_index=image_index)
                response = client.post(endpoint, json=payload)
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertEqual(data["correct"], expected_correct)
                self.assertEqual(data["correct_choice"], expected_choice)

    def test_round_contract_hides_classification_until_answer(self):
        pair = self.add_pair("IA", "REAL")
        client = self.app.test_client()
        self.set_round(client, pair)

        round_data = client.get("/api/game/round").get_json()
        self.assertEqual(round_data["image"]["id"], "A")
        self.assertIn("src", round_data["image"])
        self.assertTrue(round_data["detective_tip"])
        self.assertNotIn("isAI", round_data["image"])

        answer_data = client.post("/api/game/answer", json={"choice": "ia"}).get_json()
        self.assertTrue(answer_data["image"]["isAI"])
        for field in ("reason", "explanation", "next_tip", "summary"):
            self.assertIsInstance(answer_data[field], str)
            self.assertTrue(answer_data[field])
        self.assertNotIn("%", answer_data["summary"])
        self.assertNotIn("tell", answer_data)
        self.assertNotIn("realtip", answer_data)

    def test_online_single_image_round_uses_its_own_classification(self):
        image = GameImage(
            category="Escena IA",
            image_url="https://images.example.test/generated-scene.jpg",
            image_class="IA",
            source_name="Generador IA",
            active=True,
        )
        db.session.add(image)
        db.session.commit()
        client = self.app.test_client()

        self.assertEqual(client.post("/api/game/start").status_code, 200)
        round_data = client.get("/api/game/round").get_json()
        self.assertEqual(round_data["image"]["id"], str(image.id))
        self.assertEqual(round_data["image"]["src"], image.image_url)
        self.assertNotIn("isAI", round_data["image"])

        answer = client.post("/api/game/answer", json={"choice": "ia"}).get_json()
        self.assertTrue(answer["correct"])
        self.assertTrue(answer["image"]["isAI"])

    def test_profile_keeps_only_the_highest_completed_game_score(self):
        with self.app.test_request_context():
            session["player_id"] = "best-score-player"
            self.assertTrue(record_result("best-score-1", "human-vs-ai", "", 700, 20, True)[1])
            self.assertTrue(record_result("best-score-2", "human-vs-ai", "", 350, 20, True)[1])
        self.assertEqual(db.session.get(PlayerProfile, "best-score-player").total_points, 700)

    def test_invalid_and_duplicate_answers_are_rejected(self):
        pair = self.add_pair()
        client = self.app.test_client()
        self.set_round(client, pair)
        self.assertEqual(client.post("/api/game/answer", json={"choice": "all"}).status_code, 400)
        self.assertEqual(client.post("/api/game/answer", json={"choice": "ia"}).status_code, 200)
        self.assertEqual(client.post("/api/game/answer", json={"choice": "ia"}).status_code, 400)

    def test_existing_pair_defaults_remain_ai_and_real(self):
        pair = ImagePair(
            category="Legado",
            ai_image_path="uploads/pairs/legacy/ai.jpg",
            real_image_path="uploads/pairs/legacy/real.jpg",
            tell="Pista",
            realtip="Consejo",
        )
        db.session.add(pair)
        db.session.commit()
        self.assertEqual(pair.image_classes, ("IA", "REAL"))

    def test_two_browsers_keep_independent_scores_and_rounds(self):
        pair = self.add_pair("IA", "REAL")
        player_a = self.app.test_client()
        player_b = self.app.test_client()
        self.set_round(player_a, pair)
        self.set_round(player_b, pair)

        self.assertTrue(player_a.post("/api/game/answer", json={"choice": "ia"}).get_json()["correct"])
        self.assertFalse(player_b.post("/api/game/answer", json={"choice": "real"}).get_json()["correct"])

        result_a = player_a.get("/api/game/result").get_json()
        result_b = player_b.get("/api/game/result").get_json()
        self.assertEqual(result_a["score"], 100)
        self.assertEqual(result_a["hits"], 1)
        self.assertEqual(result_b["score"], 0)
        self.assertEqual(result_b["hits"], 0)

    def test_ai_fest_questions_have_four_unique_options(self):
        questions = load_ai_fest_questions()
        self.assertEqual(len(questions), 5)
        for question in questions:
            with self.subTest(question=question["id"]):
                option_ids = [option["id"] for option in question["options"]]
                self.assertEqual(len(option_ids), 4)
                self.assertEqual(len(set(option_ids)), 4)
                self.assertIn(question["correct"], option_ids)

    def test_flow_contains_only_image_rounds(self):
        for index in range(5):
            self.add_single_image(suffix=f"only-images-{index}")
        client = self.app.test_client()
        self.assertEqual(client.post("/api/game/start").get_json()["total"], 5)
        with client.session_transaction() as game_session:
            self.assertNotIn("trivia_order", game_session)
            self.assertNotIn("awaiting_trivia", game_session)

        client.get("/api/game/round")
        client.post("/api/game/answer", json={"choice": "ia"})
        advanced = client.post("/api/game/next").get_json()
        self.assertNotIn("type", advanced)
        self.assertFalse(advanced["finished"])
        self.assertEqual(client.get("/api/game/round").get_json()["round"], 2)
        self.assertEqual(client.post("/api/game/trivia/answer", json={}).status_code, 404)

    def test_complete_sequence_progresses_beyond_third_round_to_results(self):
        for index in range(5):
            self.add_single_image(suffix=f"complete-{index}")
        client = self.app.test_client()
        self.assertEqual(client.post("/api/game/start").get_json()["total"], 5)
        visited_rounds = []
        detective_tips = []
        explanations = []

        for expected_round in range(1, 6):
            round_data = client.get("/api/game/round").get_json()
            visited_rounds.append(round_data["round"])
            detective_tips.append(round_data["detective_tip"])
            with client.session_transaction() as game_session:
                image_id = int(game_session["deck"][game_session["i"]].split(":", 1)[1])
                image = db.session.get(GameImage, image_id)
            choice = image.image_class.lower()
            answer = client.post("/api/game/answer", json={"choice": choice})
            self.assertEqual(answer.status_code, 200)
            answer_data = answer.get_json()
            self.assertEqual(answer_data["is_last"], expected_round == 5)
            explanations.append(answer_data["explanation"])
            self.assertNotEqual(answer_data["next_tip"], round_data["detective_tip"])
            advanced = client.post("/api/game/next").get_json()
            self.assertEqual(advanced["finished"], expected_round == 5)

        self.assertEqual(visited_rounds, [1, 2, 3, 4, 5])
        self.assertEqual(len(set(detective_tips)), 5)
        self.assertEqual(len(set(explanations)), 5)
        result = client.get("/api/game/result").get_json()
        self.assertEqual(result["hits"], 5)
        self.assertNotIn("trivia_hits", result)
if __name__ == "__main__":
    unittest.main()
