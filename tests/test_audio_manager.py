import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AudioManagerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js no está disponible")
    def test_wrong_audio_timeout_stop_and_resource_cleanup(self):
        manager = (ROOT / "static/js/audio-manager.js").as_posix()
        script = f"""
const fs = require("fs");
const vm = require("vm");
const timers = [];
class FakeAudio {{
  constructor(src) {{ this.src = src; this.currentTime = 7; this.paused = false; this.listeners = {{}}; FakeAudio.instances.push(this); }}
  addEventListener(name, handler) {{ this.listeners[name] = handler; }}
  removeEventListener(name, handler) {{ if (this.listeners[name] === handler) delete this.listeners[name]; }}
  play() {{ return Promise.resolve(); }}
  pause() {{ this.paused = true; }}
  removeAttribute(name) {{ if (name === "src") this.src = ""; }}
  load() {{ this.loaded = true; }}
}}
FakeAudio.instances = [];
const window = {{
  Audio: FakeAudio,
  setTimeout(callback, delay) {{ timers.push({{callback, delay, cleared:false}}); return timers.length - 1; }},
  clearTimeout(id) {{ timers[id].cleared = true; }}
}};
vm.runInNewContext(fs.readFileSync("{manager}", "utf8"), {{window, Number, Map, Array, TypeError}});
const gameTimer = window.setTimeout(() => {{}}, 15000);
window.AudioManager.play("/wrong.mp3", {{maxDurationMs:2000}});
if (timers[1].delay !== 2000) throw new Error("El límite no es de 2 segundos");
timers[1].callback();
const wrong = FakeAudio.instances[0];
if (!wrong.paused || wrong.currentTime !== 0 || wrong.src || !wrong.loaded) throw new Error("El audio no se liberó");
if (Object.keys(wrong.listeners).length) throw new Error("Quedaron listeners");
if (timers[gameTimer].cleared) throw new Error("Se canceló un temporizador ajeno al audio");
window.AudioManager.play("/correct.mp3");
const correct = FakeAudio.instances[1];
window.AudioManager.stopAll();
if (!correct.paused || correct.src || !correct.loaded) throw new Error("stopAll no limpió el audio");
const music = window.AudioManager.play("/rise.mp3", {{loop:true, volume:0.32}});
if (!music.loop || music.volume !== 0.32) throw new Error("No configuró la música de fondo");
if (!window.AudioManager.isActive(music)) throw new Error("No registró la música activa");
window.AudioManager.stop(music);
if (window.AudioManager.isActive(music) || !music.paused) throw new Error("No detuvo la música");
"""
        subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)

    def test_all_games_use_shared_manager_for_wrong_audio_and_navigation_cleanup(self):
        template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
        self.assertLess(template.index("js/audio-manager.js"), template.index("js/game.js"))
        scripts = [
            ROOT / "static/js/game.js",
        ]
        for path in scripts:
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertIn("AudioManager.play", source)
                self.assertIn("maxDurationMs: 2000" if path.name == "game.js" and path.parent.name == "js" else "maxDurationMs:2000", source)
                self.assertIn("AudioManager.stopAll", source)

    def test_first_two_screens_have_no_background_music_controls(self):
        launcher = (ROOT / "static/js/launcher.js").read_text(encoding="utf-8")
        game = (ROOT / "static/js/game.js").read_text(encoding="utf-8")
        template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
        launcher_template = (ROOT / "templates/partials/game_launcher.html").read_text(encoding="utf-8")
        self.assertNotIn("Music.mp3", launcher)
        self.assertNotIn("menuMusic", launcher)
        self.assertNotIn('id="btnMenuMusicStart"', template)
        self.assertNotIn('id="btnMenuMusicLauncher"', launcher_template)
        self.assertNotIn("GameLauncher.playMenuMusic()", game)


if __name__ == "__main__":
    unittest.main()
