import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import qrcode


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / "static" / "runtime"
METADATA_PATH = RUNTIME_DIR / "exhibition.json"
QR_PATH = RUNTIME_DIR / "exhibition-qr.png"
TUNNEL_URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


def resolve_cloudflared(explicit_path=None, environment=None, path_lookup=shutil.which):
    environment = os.environ if environment is None else environment
    if explicit_path:
        explicit = Path(explicit_path).expanduser()
        if explicit.is_file():
            return str(explicit.resolve())

    from_path = path_lookup("cloudflared")
    if from_path and Path(from_path).is_file():
        return str(Path(from_path).resolve())

    local_app_data = environment.get("LOCALAPPDATA")
    if local_app_data:
        portable = Path(local_app_data) / "cloudflared" / "cloudflared.exe"
        if portable.is_file():
            return str(portable.resolve())
    return None


def parse_tunnel_url(line):
    match = TUNNEL_URL_PATTERN.search(line)
    return match.group(0) if match else None


def wait_for_flask(port, timeout=20):
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)
    raise RuntimeError(f"Flask no respondió en {url} después de {timeout} segundos.")


def flask_is_ready(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def stream_output(stream, lines):
    for line in iter(stream.readline, ""):
        print(line, end="")
        lines.put(line)
    stream.close()


def generate_runtime_files(public_url):
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    qr = qrcode.QRCode(version=None, box_size=10, border=4)
    qr.add_data(f"{public_url}/?modo=movil")
    qr.make(fit=True)
    qr.make_image(fill_color="#020620", back_color="white").save(QR_PATH)
    temporary_path = METADATA_PATH.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps({"public_url": public_url}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(METADATA_PATH)


def remove_runtime_files():
    for path in (METADATA_PATH, QR_PATH):
        if path.exists():
            path.unlink()


def terminate(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(
        description="Inicia Flask, abre un Cloudflare Quick Tunnel y genera su QR local."
    )
    parser.add_argument("--port", type=int, default=5000, help="Puerto local de Flask (5000).")
    parser.add_argument(
        "--cloudflared",
        help=(
            "Ruta explícita al ejecutable. Si no existe, se busca en PATH y luego "
            "en %%LOCALAPPDATA%%\\cloudflared\\cloudflared.exe."
        ),
    )
    parser.add_argument(
        "--reuse-flask",
        action="store_true",
        help="Usa un Flask ya activo en el puerto indicado en vez de iniciarlo.",
    )
    parser.add_argument(
        "--tunnel-timeout",
        type=int,
        default=45,
        help="Segundos máximos para detectar la URL pública.",
    )
    args = parser.parse_args()

    cloudflared = resolve_cloudflared(args.cloudflared)
    if not cloudflared:
        parser.error(
            "No se encontró cloudflared mediante --cloudflared, PATH ni "
            "%LOCALAPPDATA%\\cloudflared\\cloudflared.exe."
        )
    if not 1 <= args.port <= 65535:
        parser.error("--port debe estar entre 1 y 65535.")

    flask_process = None
    tunnel_process = None
    remove_runtime_files()
    try:
        if not args.reuse_flask:
            if flask_is_ready(args.port):
                raise RuntimeError(
                    f"Ya hay un servidor en el puerto {args.port}. "
                    "Usa --reuse-flask para publicarlo o elige otro --port."
                )
            environment = os.environ.copy()
            environment["PORT"] = str(args.port)
            environment["FLASK_DEBUG"] = "0"
            flask_process = subprocess.Popen(
                [sys.executable, str(PROJECT_ROOT / "run.py")],
                cwd=PROJECT_ROOT,
                env=environment,
            )
        elif not flask_is_ready(args.port):
            raise RuntimeError(
                f"--reuse-flask requiere un servidor activo en http://127.0.0.1:{args.port}/."
            )
        wait_for_flask(args.port)

        tunnel_process = subprocess.Popen(
            [
                cloudflared,
                "tunnel",
                "--url",
                f"http://127.0.0.1:{args.port}",
                "--no-autoupdate",
            ],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        lines = queue.Queue()
        for stream in (tunnel_process.stdout, tunnel_process.stderr):
            threading.Thread(target=stream_output, args=(stream, lines), daemon=True).start()

        deadline = time.monotonic() + args.tunnel_timeout
        public_url = None
        while time.monotonic() < deadline and tunnel_process.poll() is None:
            try:
                public_url = parse_tunnel_url(lines.get(timeout=0.25))
            except queue.Empty:
                continue
            if public_url:
                break
        if not public_url:
            code = tunnel_process.poll()
            detail = f" (código de salida {code})" if code is not None else ""
            raise RuntimeError(
                f"cloudflared no publicó una URL trycloudflare.com en "
                f"{args.tunnel_timeout} segundos{detail}."
            )

        generate_runtime_files(public_url)
        print("\n" + "=" * 72)
        print(f"EXPOSICIÓN ACTIVA: {public_url}")
        print(f"QR local: {QR_PATH}")
        print("Presiona Ctrl+C para cerrar el túnel.")
        print("=" * 72 + "\n")
        return tunnel_process.wait()
    except KeyboardInterrupt:
        print("\nCerrando modo exposición...")
        return 0
    except (OSError, RuntimeError) as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        return 1
    finally:
        terminate(tunnel_process)
        terminate(flask_process)
        remove_runtime_files()


if __name__ == "__main__":
    raise SystemExit(main())
