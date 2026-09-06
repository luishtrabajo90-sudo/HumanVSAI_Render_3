import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ResponsiveContractTests(unittest.TestCase):
    def test_viewport_and_explicit_breakpoints(self):
        base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertIn("width=device-width, initial-scale=1, viewport-fit=cover", base)
        self.assertNotIn("user-scalable=no", base)
        for query in (
            "@media(min-width:1200px)",
            "@media(min-width:992px) and (max-width:1199px)",
            "@media(min-width:768px) and (max-width:991px)",
            "@media(max-width:767px)",
            "@media(max-width:767px) and (orientation:portrait)",
            "@media(max-width:767px) and (orientation:landscape)",
        ):
            self.assertIn(query, css)
        self.assertIn("env(safe-area-inset-left)", css)
        self.assertIn("min-height:100dvh", css)
        self.assertNotIn("transform:scale(", css)
        for query in (
            "@media(max-width:480px)",
            "@media(min-width:481px) and (max-width:768px)",
            "@media(min-width:769px) and (max-width:1024px)",
            "@media(min-width:1025px) and (max-width:1440px)",
            "@media(min-width:1441px)",
            "@media(max-width:1024px) and (orientation:portrait)",
            "@media(min-width:1800px)",
            "@media(min-width:2200px)",
        ):
            self.assertIn(query, css)
        launcher_css = (ROOT / "static" / "css" / "launcher.css").read_text(encoding="utf-8")
        self.assertIn("height:clamp(22rem,68vw,34rem)", launcher_css)
        self.assertIn("max-height:calc(var(--app-height,100dvh) - 1rem)", launcher_css)

    def test_global_fullscreen_and_directional_navigation(self):
        base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "responsive.js").read_text(encoding="utf-8")
        self.assertIn('id="appFullscreen"', base)
        self.assertIn("requestFullscreen()", script)
        self.assertIn("fullscreenchange", script)
        self.assertIn("ArrowLeft", script)
        self.assertIn("ArrowRight", script)
        self.assertIn("appviewportchange", script)

    def test_human_game_exposes_binary_classification(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "game.js").read_text(encoding="utf-8")
        choices = {
            "choiceAI": ("ia", "IA"),
            "choiceReal": ("real", "REAL"),
        }
        for element_id, (value, label) in choices.items():
            self.assertIn(f'id="{element_id}"', template)
            self.assertIn(f'data-choice="{value}"', template)
            self.assertIn(label, template)
            self.assertIn(f'$("{element_id}").addEventListener("click"', script)

    def test_reveal_highlights_only_the_authoritative_correct_choice(self):
        script = (ROOT / "static" / "js" / "game.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
        reveal_start = script.index("function revealCorrectChoice(correctAnswer)")
        reveal_end = script.index("function reveal(r, chosenChoice)", reveal_start)
        reveal_buttons = script[reveal_start:reveal_end]
        self.assertIn('button.classList.remove("is-correct", "is-wrong", "is-muted")', reveal_buttons)
        self.assertIn('button.dataset.choice === correctAnswer ? "is-correct" : "is-muted"', reveal_buttons)
        self.assertNotIn('button.classList.add("is-wrong")', reveal_buttons)
        self.assertIn("var correctAnswer = r.correct_choice;", script)
        self.assertIn("revealCorrectChoice(correctAnswer);", script)
        self.assertNotIn(".classification-choice.is-wrong", css)
        self.assertIn(".classification-choice.is-muted", css)
        self.assertIn("box-shadow:none", css)

    def test_round_sequence_waits_for_image_before_timer(self):
        script = (ROOT / "static" / "js" / "game.js").read_text(encoding="utf-8")
        load_round_start = script.index("function loadRound()")
        load_round_end = script.index("function choose(", load_round_start)
        load_round = script[load_round_start:load_round_end]
        expected_order = (
            ".then(validateRoundPayload)",
            ".then(prepareRoundImage)",
            "registerRound(round)",
            "showPreparedRound(round)",
            "startTimer(round.timer_seconds)",
        )
        positions = [load_round.index(step) for step in expected_order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("showRoundError(error, \"load\")", load_round)
        self.assertIn("btnRetryRound", script)
        self.assertIn("btnSkipRound", script)
        self.assertIn('api("/api/game/next", "POST")', script)

    def test_human_game_has_no_trivia_screen(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "game.js").read_text(encoding="utf-8")
        launcher = (ROOT / "static" / "js" / "launcher.js").read_text(encoding="utf-8")
        for marker in ('id="screenTrivia"', 'id="btnTriviaNext"', 'id="rTrivia"'):
            self.assertNotIn(marker, template)
        self.assertNotIn("screenTrivia", script)
        self.assertNotIn("screenTrivia", launcher)
        self.assertNotIn("/api/game/trivia/answer", script)

    def test_detective_feedback_uses_one_simple_summary(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "game.js").read_text(encoding="utf-8")
        for element_id in ("detectiveHint", "fbSummary"):
            self.assertIn(f'id="{element_id}"', template)
            self.assertIn(f'$("{element_id}").textContent', script)
        for element_id in ("fbReason", "fbExplanation", "fbNextTip"):
            self.assertNotIn(f'id="{element_id}"', template)
        self.assertEqual(template.count('class="feedback-summary"'), 1)

    def test_round_layout_keeps_controls_in_document_flow(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
        status_index = template.index('id="timeoutAlert"')
        image_index = template.index('id="roundCards"')
        self.assertLess(status_index, image_index)
        self.assertIn('class="round-status-row"', template)
        self.assertIn('class="timer-label"', template)
        self.assertIn("position:relative;z-index:4;top:auto", css)
        self.assertNotIn(".timeout-alert{top:clamp", css)
        self.assertNotIn(".timeout-alert{top:4.2rem", css)
        self.assertIn("aspect-ratio:4/3", css)
        self.assertIn("object-fit:contain", css)
        self.assertIn("width:min(100%,80rem)", css)

    def test_session_clock_and_progress_have_reserved_space(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertIn('id="gameSessionClock"', template)
        self.assertIn('id="gameSessionTimer"', template)
        self.assertIn(".game-session-clock", css)
        self.assertIn("margin:clamp(1rem,2vh,1.5rem)", css)
        self.assertIn("align-items:flex-end", css)

    def test_visitor_ranking_keeps_brand_image_and_uses_blue_theme(self):
        template = (ROOT / "templates" / "partials" / "game_launcher.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "css" / "launcher.css").read_text(encoding="utf-8")
        ranking_template = template.split('id="visitorRankingModal"', 1)[1]
        self.assertIn("img/ui/festival-brand-transparent.png", ranking_template)
        self.assertIn('class="visitor-ranking-brand"', template)
        self.assertNotIn("img/aifest-log.jpg", template)
        self.assertNotIn("filename='img/ui/festival-brand.png'", ranking_template)
        self.assertIn("#visitorRankingModal{", css)
        self.assertIn("width:100vw;height:100vh;height:100dvh", css)
        self.assertIn("max-width:none;max-height:none", css)
        self.assertIn("env(safe-area-inset-top)", css)
        self.assertIn("grid-template-rows:auto auto minmax(0,1fr) auto auto", css)
        self.assertIn("overflow-x:hidden;overflow-y:auto", css)
        self.assertIn("html.ranking-modal-open,body.ranking-modal-open{overflow:hidden}", css)
        self.assertIn(".visitor-ranking-card>:not(.launcher-modal-close)", css)
        self.assertIn("background:transparent;box-shadow:none", css)
        self.assertIn("linear-gradient(145deg,#071c49 0%,#041432 52%,#020b22 100%)", css)
        self.assertIn(".visitor-ranking-table tbody tr:nth-child(1)", css)
        self.assertIn(".visitor-ranking-footer b{font-size:1.05rem;color:#4de2ff}", css)
        index = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        launcher = (ROOT / "static" / "js" / "launcher.js").read_text(encoding="utf-8")
        self.assertIn("v='ranking-fullscreen-3'", index)
        self.assertIn('document.documentElement.classList.add("ranking-modal-open")', launcher)
        self.assertIn('document.documentElement.classList.remove("ranking-modal-open")', launcher)
        self.assertIn('document.body.classList.add("ranking-modal-open")', launcher)
        self.assertIn('document.body.classList.remove("ranking-modal-open")', launcher)

    def test_admin_pages_share_blue_responsive_theme(self):
        base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
        players = (ROOT / "templates" / "admin" / "players_list.html").read_text(encoding="utf-8")
        self.assertIn("request.blueprint == 'admin'", base)
        self.assertIn("v='admin-blue-1'", base)
        for marker in (
            "body.admin-page{",
            ".admin-page .brand{",
            ".admin-page .admin-form input[type=text]",
            ".admin-page .admin-table-wrap{",
            ".admin-page .admin-table tbody tr:nth-child(even)",
            ".admin-page .hud{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))",
            ".admin-page .admin-table tr{",
        ):
            self.assertIn(marker, css)
        self.assertIn("overflow-x:auto", css)
        self.assertIn('class="admin-table admin-table-wide"', players)


if __name__ == "__main__":
    unittest.main()
