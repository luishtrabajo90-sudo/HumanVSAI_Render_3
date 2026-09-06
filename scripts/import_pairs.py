"""Importa pares de imágenes nuevos desde un manifest JSON.

Formato esperado del manifest (lista de objetos):
[
  {
    "category": "Retrato de persona",
    "ai_image": "ruta/a/imagen_ia.jpg",
    "real_image": "ruta/a/imagen_real.jpg",
    "tell": "Cómo detectar que es IA...",
    "realtip": "Qué la hace real...",
    "active": true
  },
  ...
]

Las rutas de ai_image/real_image pueden ser absolutas o relativas al
manifest. Los archivos se copian a static/uploads/pairs/<id>/.

Uso:
    python scripts/import_pairs.py ruta/al/manifest.json
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.extensions import db
from app.models import ImagePair

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}


def _copy_image(src_path, manifest_dir, dest_dir, role):
    if not src_path:
        return None
    full_src = src_path if os.path.isabs(src_path) else os.path.join(manifest_dir, src_path)
    if not os.path.isfile(full_src):
        print(f"  AVISO: no se encontró el archivo '{full_src}', se omite.")
        return None
    ext = full_src.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        print(f"  AVISO: extensión no permitida '{ext}' en '{full_src}', se omite.")
        return None
    os.makedirs(dest_dir, exist_ok=True)
    filename = f"{role}.{ext}"
    shutil.copy2(full_src, os.path.join(dest_dir, filename))
    return filename


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/import_pairs.py ruta/al/manifest.json")
        sys.exit(1)

    manifest_path = os.path.abspath(sys.argv[1])
    if not os.path.isfile(manifest_path):
        print(f"No se encontró el manifest: {manifest_path}")
        sys.exit(1)

    manifest_dir = os.path.dirname(manifest_path)
    with open(manifest_path, "r", encoding="utf-8-sig") as f:
        entries = json.load(f)

    app = create_app()
    with app.app_context():
        count = 0
        for entry in entries:
            pair = ImagePair(
                category=entry.get("category", ""),
                tell=entry.get("tell", ""),
                realtip=entry.get("realtip", ""),
                active=bool(entry.get("active", True)),
            )
            db.session.add(pair)
            db.session.flush()

            pair_dir = os.path.join(app.config["UPLOAD_FOLDER"], str(pair.id))
            ai_filename = _copy_image(entry.get("ai_image"), manifest_dir, pair_dir, "ai")
            real_filename = _copy_image(entry.get("real_image"), manifest_dir, pair_dir, "real")

            if ai_filename:
                pair.ai_image_path = f"uploads/pairs/{pair.id}/{ai_filename}"
            if real_filename:
                pair.real_image_path = f"uploads/pairs/{pair.id}/{real_filename}"

            if not (ai_filename and real_filename):
                pair.active = False

            count += 1
            print(f"Importado #{pair.id}: {pair.category}")

        db.session.commit()
        print(f"\nListo. {count} pares procesados.")


if __name__ == "__main__":
    main()
