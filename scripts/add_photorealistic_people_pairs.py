"""Add photorealistic people and everyday-scene challenges."""

import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from app.extensions import db
from app.models import ImagePair
from scripts.add_real_photo_pairs import build_pair_files


REQUESTS = (
    ("Personas en oficina", '"FEMA workers in a meeting in Puerto Rico"', ("fema workers in a meeting",)),
    ("Fotografía corporativa", '"Business Roundtable CEO Committee"', ("business roundtable ceo",)),
    ("Escena cotidiana", '"Business Woman is reading Newspaper"', ("business woman",)),
    ("Retrato natural", '"Woman redhead natural portrait 1"', ("woman redhead natural portrait",)),
    ("Personas en oficina", '"FEMA Public Assistance specialist in Illinois"', ("fema public assistance specialist",)),
    ("Fotografía corporativa", '"Barack Obama works on his re-election acceptance speech"', ("barack obama works",)),
    ("Escena cotidiana", '"Friends - Flickr - Braiu"', ("friends - flickr",)),
    ("Escena cotidiana", '"Family in a kitchen"', ("family in a kitchen",)),
    ("Personas en oficina", '"FEMA workers at a meeting in Puerto Rico"', ("fema workers at a meeting",)),
    ("Escena cotidiana", '"Mount Sinai Hospital Coffee Shop"', ("mount sinai hospital coffee shop",)),
)

SOURCE_MANIFEST = PROJECT_ROOT / "instance" / "photorealistic_people_sources.json"


def main():
    app = create_app()
    if SOURCE_MANIFEST.exists():
        recorded = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
        with app.app_context():
            if recorded and all(db.session.get(ImagePair, item["pair_id"]) for item in recorded):
                print(f"La colección ya está instalada ({len(recorded)} pares).")
                return

    staging = PROJECT_ROOT / "instance" / "_staging_photorealistic_people"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    selections = []
    used_urls = set()

    try:
        for index, (category, query, title_terms) in enumerate(REQUESTS, 1):
            selection = build_pair_files(staging, index, query, title_terms, used_urls)
            selection["category"] = category
            selections.append(selection)
            print(f"[{index:02d}/10] {category}: {selection['commons_title']}")

        imported = []
        created_directories = []
        with app.app_context():
            try:
                for selection in selections:
                    pair = ImagePair(
                        category=selection["category"],
                        ai_image_class="IA",
                        real_image_class="REAL",
                        tell="",
                        realtip="",
                        active=True,
                    )
                    db.session.add(pair)
                    db.session.flush()
                    pair_directory = Path(app.config["UPLOAD_FOLDER"]) / str(pair.id)
                    pair_directory.mkdir(parents=True, exist_ok=False)
                    created_directories.append(pair_directory)
                    shutil.copy2(selection["generated"], pair_directory / "ai.jpg")
                    shutil.copy2(selection["real"], pair_directory / "real.jpg")
                    pair.ai_image_path = f"uploads/pairs/{pair.id}/ai.jpg"
                    pair.real_image_path = f"uploads/pairs/{pair.id}/real.jpg"
                    imported.append(
                        {
                            "pair_id": pair.id,
                            "category": pair.category,
                            "commons_title": selection["commons_title"],
                            "source_page": selection["source_page"],
                            "download_url": selection["download_url"],
                            "author": selection["author"],
                            "license": selection["license"],
                            "synthetic_treatment": selection["artifact"],
                        }
                    )
                db.session.commit()
            except Exception:
                db.session.rollback()
                for directory in created_directories:
                    shutil.rmtree(directory, ignore_errors=True)
                raise

        SOURCE_MANIFEST.write_text(
            json.dumps(imported, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nImportados {len(imported)} pares fotorrealistas.")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    main()
