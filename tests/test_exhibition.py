import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import start_exhibition


class ExhibitionTests(unittest.TestCase):
    def test_cloudflared_resolution_precedence_and_portable_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            explicit = root / "explicit.exe"
            from_path = root / "path.exe"
            portable = root / "local" / "cloudflared" / "cloudflared.exe"
            for executable in (explicit, from_path, portable):
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.touch()

            environment = {"LOCALAPPDATA": str(root / "local")}
            lookup = lambda _name: str(from_path)
            self.assertEqual(
                start_exhibition.resolve_cloudflared(str(explicit), environment, lookup),
                str(explicit.resolve()),
            )
            self.assertEqual(
                start_exhibition.resolve_cloudflared(None, environment, lookup),
                str(from_path.resolve()),
            )
            self.assertEqual(
                start_exhibition.resolve_cloudflared(None, environment, lambda _name: None),
                str(portable.resolve()),
            )
            self.assertIsNone(
                start_exhibition.resolve_cloudflared(
                    str(root / "missing.exe"),
                    {"LOCALAPPDATA": str(root / "missing-local")},
                    lambda _name: None,
                )
            )

    def test_extracts_only_cloudflare_quick_tunnel_url(self):
        line = "INF +https://bright-demo.trycloudflare.com ready"
        self.assertEqual(
            start_exhibition.parse_tunnel_url(line),
            "https://bright-demo.trycloudflare.com",
        )
        self.assertIsNone(start_exhibition.parse_tunnel_url("https://example.com"))

    def test_generates_local_qr_and_exact_metadata_url(self):
        public_url = "https://bright-demo.trycloudflare.com"
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            with (
                patch.object(start_exhibition, "RUNTIME_DIR", runtime),
                patch.object(start_exhibition, "METADATA_PATH", runtime / "exhibition.json"),
                patch.object(start_exhibition, "QR_PATH", runtime / "exhibition-qr.png"),
            ):
                start_exhibition.generate_runtime_files(public_url)
                metadata = json.loads((runtime / "exhibition.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["public_url"], public_url)
                qr_bytes = (runtime / "exhibition-qr.png").read_bytes()
                self.assertTrue(qr_bytes.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
