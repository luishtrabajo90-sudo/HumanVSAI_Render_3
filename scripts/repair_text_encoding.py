"""Restaura los acentos que se perdieron al importar el manifest de pares.

El manifest original se generó con una codificación que reemplazó cada vocal
acentuada por '?'. Los textos afectados provienen de plantillas fijas, por lo
que la corrección es determinista.

Uso:
    python scripts/repair_text_encoding.py            # solo reporta
    python scripts/repair_text_encoding.py --apply    # guarda los cambios
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.extensions import db
from app.models import ImagePair

REPLACEMENTS = {
    "Fotograf?a": "Fotografía",
    "agreg?": "agregó",
    "composici?n": "composición",
    "repetici?n": "repetición",
    "sint?tica": "sintética",
}


def repair(text):
    for damaged, fixed in REPLACEMENTS.items():
        text = text.replace(damaged, fixed)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Guarda los cambios en la base de datos.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        changed = 0
        for pair in ImagePair.query.order_by(ImagePair.id).all():
            category = repair(pair.category or "")
            tell = repair(pair.tell or "")
            realtip = repair(pair.realtip or "")
            if (category, tell, realtip) == (pair.category, pair.tell, pair.realtip):
                continue
            changed += 1
            if args.apply:
                pair.category = category
                pair.tell = tell
                pair.realtip = realtip
        if args.apply:
            db.session.commit()
        remaining = sum(
            1 for pair in ImagePair.query.all()
            if any(token in f"{pair.category} {pair.tell} {pair.realtip}" for token in REPLACEMENTS)
        )
        print(f"Pares corregidos: {changed}")
        print(f"Pares con texto dañado restante: {remaining}")
        print("Modo:", "aplicado" if args.apply else "solo reporte")


if __name__ == "__main__":
    main()
