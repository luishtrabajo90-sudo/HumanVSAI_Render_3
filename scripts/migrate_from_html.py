"""Migra los pares de imágenes del HTML original a la base de datos.

Lee el array `ROUNDS` embebido en el archivo HTML legado, decodifica las
imágenes de IA (que venían en base64) y las guarda como archivos en
static/uploads/pairs/<id>/. Las fotos "reales" del HTML original se
cargaban desde URLs externas (r.reals); como ahora las imágenes deben ser
archivos locales subidos, este script NO las descarga: crea el par con
real_image_path=NULL y lo deja inactivo hasta que se suba la foto real
manualmente desde el panel admin (/admin/pairs).

Uso:
    python scripts/migrate_from_html.py [ruta_al_html]

Si no se indica ruta, usa por defecto:
    ../Imagenes/juego-real-vs-ia Original.html (relativo a este proyecto)
"""
import json
import mimetypes
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.extensions import db
from app.models import ImagePair

DEFAULT_HTML = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "Imagenes", "juego-real-vs-ia Original.html")
)


def extract_rounds(html_text):
    marker = "var ROUNDS = "
    idx = html_text.find(marker)
    if idx == -1:
        raise ValueError("No se encontró 'var ROUNDS =' en el HTML.")
    start = idx + len(marker)
    decoder = json.JSONDecoder()
    rounds, _end = decoder.raw_decode(html_text, start)
    return rounds


def save_data_uri(data_uri, dest_dir, filename_no_ext):
    header, b64data = data_uri.split(",", 1)
    mime = header.split(";")[0].replace("data:", "")
    ext = mimetypes.guess_extension(mime) or ".jpg"
    if ext == ".jpe":
        ext = ".jpg"
    import base64

    raw = base64.b64decode(b64data)
    os.makedirs(dest_dir, exist_ok=True)
    filename = filename_no_ext + ext
    with open(os.path.join(dest_dir, filename), "wb") as f:
        f.write(raw)
    return filename


def main():
    html_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HTML
    if not os.path.isfile(html_path):
        print(f"No se encontró el archivo HTML: {html_path}")
        sys.exit(1)

    with open(html_path, "r", encoding="utf-8") as f:
        html_text = f.read()

    rounds = extract_rounds(html_text)
    print(f"Encontrados {len(rounds)} pares en el HTML original.")

    app = create_app()
    with app.app_context():
        created = []
        for r in rounds:
            pair = ImagePair(
                category=r.get("cat", ""),
                tell=r.get("tell", ""),
                realtip=r.get("realtip", ""),
                active=False,  # inactivo hasta que se suba la foto real
            )
            db.session.add(pair)
            db.session.flush()  # asigna pair.id sin cerrar la transacción

            pair_dir = os.path.join(app.config["UPLOAD_FOLDER"], str(pair.id))
            ai_data_uri = r.get("ai")
            if ai_data_uri:
                filename = save_data_uri(ai_data_uri, pair_dir, "ai")
                pair.ai_image_path = f"uploads/pairs/{pair.id}/{filename}"

            created.append((pair, r.get("reals", [])))

        db.session.commit()

        print("\nPares creados (inactivos, pendientes de foto real):")
        for pair, reals in created:
            print(f"  #{pair.id} [{pair.category}] -> sube la foto real en /admin/pairs/{pair.id}/edit")
            if reals:
                print(f"        URLs de referencia originales: {', '.join(reals)}")

        print(
            "\nListo. Ve a /admin/pairs, sube la foto 'real' de cada par y actívalo "
            "para que aparezca en el juego."
        )


if __name__ == "__main__":
    main()
