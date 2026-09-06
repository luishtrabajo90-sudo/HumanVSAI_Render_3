"""Add ten sourced real-photo pairs to the game collection."""

import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from app.extensions import db
from app.models import ImagePair
from scripts.build_curated_collection import (
    _add_synthetic_element,
    _candidate,
    _clean_metadata,
    _download,
    _normalize,
    _search,
)


PHOTO_REQUESTS = (
    ("Animal", "African elephant wildlife photograph", ("elephant",)),
    ("Animal", "red fox wildlife photograph", ("fox",)),
    ("Animal", "macaw bird wildlife photograph", ("macaw", "ara ararauna")),
    ("Carro", "classic automobile car photograph", ("automobile", "car")),
    ("Carro", "rally car motorsport photograph", ("rally", "car")),
    ("Carro", "electric car street photograph", ("electric car",)),
    ("Objeto", '"wristwatch" product photograph', ("wristwatch", "watch")),
    ("Objeto", '"Camera Zenit 11"', ("camera zenit",)),
    ("Paisaje", "tropical beach landscape photograph", ("beach",)),
    ("Paisaje", "snowy mountain lake landscape photograph", ("mountain", "lake", "snow")),
)

SOURCE_MANIFEST = PROJECT_ROOT / "instance" / "added_real_photo_sources.json"


def select_photo(query, required_title_terms, used_urls):
    for page in _search(query):
        title = page.get("title", "").lower()
        if not any(term in title for term in required_title_terms):
            continue
        candidate = _candidate(page, used_urls)
        if candidate is not None:
            info, url = candidate
            return page, info, url
    raise RuntimeError(f"No se encontró una foto apta para: {query}")


def build_pair_files(staging, index, query, required_title_terms, used_urls):
    page, info, url = select_photo(query, required_title_terms, used_urls)
    raw = staging / f"raw_{index:02d}"
    real = staging / f"real_{index:02d}.jpg"
    generated = staging / f"ai_{index:02d}.jpg"
    try:
        _download(url, raw)
        _normalize(raw, real)
        synthetic = _add_synthetic_element(real, generated)
    finally:
        raw.unlink(missing_ok=True)

    metadata = info.get("extmetadata") or {}
    used_urls.add(url)
    return {
        "real": real,
        "generated": generated,
        "commons_title": page.get("title", ""),
        "source_page": info.get("descriptionurl", ""),
        "download_url": url,
        "author": _clean_metadata(
            (metadata.get("Artist") or {}).get("value", "Autor de Wikimedia Commons")
        ),
        "license": _clean_metadata(
            (metadata.get("LicenseShortName") or {}).get("value", "Ver fuente")
        ),
        **synthetic,
    }


def main():
    staging = PROJECT_ROOT / "instance" / "_staging_add_real_photos"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    selections = []
    used_urls = set()
    try:
        for index, (category, query, required_title_terms) in enumerate(PHOTO_REQUESTS, 1):
            selection = build_pair_files(
                staging, index, query, required_title_terms, used_urls
            )
            selection.update(category=category, query=query)
            selections.append(selection)
            print(f"[{index:02d}/10] {category}: {selection['commons_title']}")

        app = create_app()
        imported = []
        created_directories = []
        with app.app_context():
            try:
                for selection in selections:
                    pair = ImagePair(
                        category=selection["category"],
                        ai_image_class="IA",
                        real_image_class="REAL",
                        tell="Busca pequeñas repeticiones o elementos fuera de contexto en la versión sintética.",
                        realtip="La fotografía real conserva texturas, iluminación y detalles naturales coherentes.",
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
                            "category": selection["category"],
                            "commons_title": selection["commons_title"],
                            "source_page": selection["source_page"],
                            "download_url": selection["download_url"],
                            "author": selection["author"],
                            "license": selection["license"],
                            "artifact": selection["artifact"],
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
        print(f"\nImportados {len(imported)} pares. Fuentes: {SOURCE_MANIFEST}")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    main()
