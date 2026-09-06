"""Create the single-image game catalog from online real and AI image sources.

Real entries use the original Wikimedia Commons URLs recorded by the curated
collection builder. AI entries use direct, seeded renders from Pollinations AI.
Neither source is locally altered or paired with another image.
"""

import json
import sys
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from app.extensions import db
from app.models import GameImage


COLLECTION_PATH = PROJECT_ROOT / "data" / "coleccion_curada" / "coleccion_curada.json"
AI_PROMPTS = (
    "photorealistic Venezuelan tepui landscape after rain",
    "photorealistic offshore oil platform at blue hour",
    "photorealistic scientist examining a circuit board in a modern laboratory",
    "photorealistic colorful tropical market in Caracas Venezuela",
    "photorealistic astronaut repairing a satellite in orbit",
    "photorealistic electric car driving through a mountain valley",
    "photorealistic family cooking together in a bright kitchen",
    "photorealistic sea turtle swimming above a coral reef",
    "photorealistic city skyline reflected in a calm river at dawn",
    "photorealistic engineer wearing safety equipment at an oil refinery",
)


def ai_image_url(prompt, seed):
    return (
        "https://image.pollinations.ai/prompt/"
        f"{quote(prompt)}?width=1024&height=768&seed={seed}&nologo=true"
    )


def load_real_entries():
    if not COLLECTION_PATH.exists():
        raise RuntimeError(
            "No existe la colección de fuentes reales. Ejecuta primero "
            "scripts/build_curated_collection.py data/coleccion_curada."
        )
    collection = json.loads(COLLECTION_PATH.read_text(encoding="utf-8"))
    return [
        entry for entry in collection
        if entry.get("download_url") and entry.get("category")
    ]


def main():
    real_entries = load_real_entries()
    app = create_app()
    with app.app_context():
        GameImage.query.delete()
        for entry in real_entries:
            db.session.add(GameImage(
                category=entry["category"],
                image_url=entry["download_url"],
                image_class="REAL",
                source_name="Wikimedia Commons",
                active=True,
            ))
        for index, entry in enumerate(real_entries):
            db.session.add(GameImage(
                category=entry["category"],
                image_url=ai_image_url(AI_PROMPTS[index % len(AI_PROMPTS)], 1000 + index),
                image_class="IA",
                source_name="Pollinations AI",
                active=True,
            ))
        db.session.commit()
    print(f"Catálogo listo: {len(real_entries)} imágenes reales y {len(real_entries)} imágenes IA.")


if __name__ == "__main__":
    main()