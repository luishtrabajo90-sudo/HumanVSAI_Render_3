"""Download a local, independent image collection for the game.

Real photos come from the Wikimedia Commons source manifest. IA images are
direct photorealistic generations from Pollinations AI; neither is altered or
derived from the other. The generated sources.json records the provenance.
"""

import json
import sys
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from app.extensions import db
from app.models import GameImage


COLLECTION_PATH = PROJECT_ROOT / "data" / "coleccion_curada" / "coleccion_curada.json"
OUTPUT_ROOT = PROJECT_ROOT / "static" / "assets" / "images"
IMAGE_COUNT = 100
PICSUM_IDS = tuple(range(1, 51))
AI_PROMPTS = (
    "candid documentary photo of engineers reviewing a refinery control room, 35mm lens, natural skin texture, subtle film grain",
    "editorial travel photo of a family walking through a tropical Venezuelan town, natural daylight, imperfect candid framing",
    "wildlife photograph of a sea turtle above a coral reef, underwater sunlight, National Geographic documentary style",
    "professional photo of an electric car beside a mountain lake, overcast afternoon, realistic reflections",
    "photojournalism photo of a scientist working in a laboratory, natural imperfections, available window light",
    "architectural photograph of a modern library interior with people reading naturally, 24mm lens",
    "realistic street photograph of cyclists at a city intersection after rain, handheld 35mm camera",
    "documentary photograph of workers on an offshore platform at sunrise, realistic safety equipment",
    "natural portrait photograph of a chef in a busy restaurant kitchen, shallow depth of field",
    "landscape photograph of a tepui in Venezuela after rain, muted natural colors, 50mm camera",
    "realistic photograph of a veterinary doctor examining a dog in a clinic, candid composition",
    "candid photograph of friends having coffee in a bright cafe, natural faces, subtle camera noise",
)


def download(url, destination):
    if destination.exists() and destination.stat().st_size > 10_000:
        return
    request = Request(url, headers={"User-Agent": "AI Fest educational game/1.0"})
    for attempt in range(4):
        try:
            with urlopen(request, timeout=120) as response:
                destination.write_bytes(response.read())
            return
        except OSError:
            destination.unlink(missing_ok=True)
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def ai_url(prompt, seed):
    return (
        "https://image.pollinations.ai/prompt/"
        f"{quote(prompt + ', no text, no watermark')}?width=1024&height=768&seed={seed}&nologo=true&model=flux"
    )


def main():
    manifest_entries = json.loads(COLLECTION_PATH.read_text(encoding="utf-8"))
    entries = manifest_entries + [
        {
            "category": manifest_entries[index % len(manifest_entries)]["category"],
            "download_url": f"https://picsum.photos/id/{image_id}/1024/768",
            "source_page": f"https://picsum.photos/id/{image_id}/1024/768",
            "author": "Lorem Picsum / Unsplash",
            "license": "Unsplash License",
        }
        for index, image_id in enumerate(PICSUM_IDS)
    ]
    if len(entries) != IMAGE_COUNT:
        raise RuntimeError(f"Se esperaban {IMAGE_COUNT} imágenes reales.")
    real_directory = OUTPUT_ROOT / "Real"
    ai_directory = OUTPUT_ROOT / "IA"
    real_directory.mkdir(parents=True, exist_ok=True)
    ai_directory.mkdir(parents=True, exist_ok=True)
    sources = []

    for index, entry in enumerate(entries, 1):
        filename = f"real_{index:02d}.jpg"
        destination = real_directory / filename
        download(entry["download_url"], destination)
        sources.append({
            "file": f"Real/{filename}", "class": "REAL", "category": entry["category"],
            "source": entry["source_page"], "author": entry["author"], "license": entry["license"],
        })
        print(f"Real {index}/{len(entries)}")

    for index, entry in enumerate(entries, 1):
        filename = f"ia_{index:02d}.jpg"
        prompt = AI_PROMPTS[(index - 1) % len(AI_PROMPTS)]
        url = ai_url(prompt, 5000 + index)
        download(url, ai_directory / filename)
        sources.append({
            "file": f"IA/{filename}", "class": "IA", "category": entry["category"],
            "source": "Pollinations AI (Flux)", "prompt": prompt, "seed": 5000 + index,
        })
        print(f"IA {index}/{len(entries)}")

    (OUTPUT_ROOT / "sources.json").write_text(
        json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    app = create_app()
    with app.app_context():
        GameImage.query.delete()
        for source in sources:
            db.session.add(GameImage(
                category=source["category"],
                image_url=f"assets/images/{source['file']}",
                image_class=source["class"],
                source_name=source["source"],
                active=True,
            ))
        db.session.commit()
    print(f"Colección lista: {len(entries)} reales y {len(entries)} IA.")


if __name__ == "__main__":
    main()