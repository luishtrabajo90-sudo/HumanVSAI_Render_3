"""Build a sourced 50-image collection and subtle synthetic counterparts."""

import hashlib
import html
import json
import random
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, ImageStat


COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "RealVsIA educational game/1.0"
OUTPUT_SIZE = (1024, 768)
EXCLUDED_TITLE_WORDS = {
    "map",
    "flag",
    "logo",
    "coat of arms",
    "diagram",
    "drawing",
    "painting",
    "poster",
    "stamp",
    "locator",
    "icon",
}

GROUPS = (
    (
        "Paisaje venezolano",
        (
            ('"Angel Falls" Venezuela photograph', 2),
            ('"Canaima National Park" landscape photograph', 2),
            ('Los Roques Venezuela', 2),
            ('Gran Sabana Venezuela', 2),
            ('Mount Roraima Venezuela', 2),
            ('Médanos de Coro Venezuela', 2),
            ('Morrocoy Venezuela', 2),
            ('Mérida Venezuela mountains', 2),
            ('Orinoco Delta Venezuela', 2),
            ('Henri Pittier Venezuela', 2),
        ),
    ),
    (
        "Paisaje del mundo",
        (
            ('Grand Canyon landscape', 2),
            ('Swiss Alps landscape', 2),
            ('Patagonia landscape', 2),
            ('Iceland waterfall landscape', 2),
            ('Sahara Desert dunes', 2),
            ('Norwegian fjord landscape', 2),
            ('Banff National Park landscape', 2),
            ('New Zealand Fiordland landscape', 2),
            ('Dolomites landscape', 2),
            ('Zhangjiajie landscape', 2),
        ),
    ),
    (
        "Ambiente petrolero",
        (
            ('oil refinery', 2),
            ('offshore oil platform', 2),
            ('oil pumpjack field', 2),
            ('petroleum storage tanks', 2),
            ('oil drilling rig', 2),
        ),
    ),
)


def _curl_json(params):
    command = [
        "curl.exe",
        "--ssl-no-revoke",
        "--silent",
        "--show-error",
        "--fail",
        "--retry",
        "6",
        "--retry-all-errors",
        "--retry-delay",
        "2",
        "--get",
        "--user-agent",
        USER_AGENT,
    ]
    for key, value in params.items():
        command.extend(("--data-urlencode", f"{key}={value}"))
    command.append(COMMONS_API)
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    time.sleep(0.35)
    return json.loads(result.stdout)


def _search(query):
    data = _curl_json(
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": "20",
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": "1600",
            "format": "json",
            "formatversion": "2",
        }
    )
    return data.get("query", {}).get("pages", [])


def _download(url, destination):
    subprocess.run(
        [
            "curl.exe",
            "--ssl-no-revoke",
            "--silent",
            "--show-error",
            "--fail",
            "--location",
            "--retry",
            "6",
            "--retry-all-errors",
            "--retry-delay",
            "2",
            "--user-agent",
            USER_AGENT,
            url,
            "--output",
            str(destination),
        ],
        check=True,
    )
    time.sleep(0.25)


def _clean_metadata(value):
    value = html.unescape(value or "")
    while "<" in value and ">" in value:
        start = value.find("<")
        end = value.find(">", start)
        if end < 0:
            break
        value = value[:start] + " " + value[end + 1 :]
    return " ".join(value.split())


def _candidate(page, used_urls):
    infos = page.get("imageinfo") or []
    if not infos:
        return None
    info = infos[0]
    title = page.get("title", "").lower()
    if any(word in title for word in EXCLUDED_TITLE_WORDS):
        return None
    if info.get("mime") not in {"image/jpeg", "image/png", "image/webp"}:
        return None
    if info.get("width", 0) < 1000 or info.get("height", 0) < 650:
        return None
    url = info.get("thumburl") or info.get("url")
    if not url or url in used_urls:
        return None
    return info, url


def _normalize(source, destination):
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image = ImageOps.fit(
            image,
            OUTPUT_SIZE,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        image.save(destination, "JPEG", quality=95, subsampling=0, optimize=True)


def _best_element_box(image, rng):
    width, height = image.size
    box_w = rng.randint(55, 90)
    box_h = rng.randint(42, 72)
    candidates = []
    for row in range(2, 8):
        for col in range(1, 11):
            x = int(col * width / 12 - box_w / 2)
            y = int(row * height / 10 - box_h / 2)
            box = (x, y, x + box_w, y + box_h)
            patch = image.crop(box).convert("L")
            variance = ImageStat.Stat(patch).var[0]
            if 90 < variance < 2400:
                candidates.append((variance, box))
    if not candidates:
        return (width // 8, height // 5, width // 8 + box_w, height // 5 + box_h)
    candidates.sort(reverse=True)
    return rng.choice(candidates[: max(3, len(candidates) // 4)])[1]


def _add_synthetic_element(source, destination):
    seed = int.from_bytes(hashlib.sha256(source.read_bytes()).digest()[:8], "big")
    rng = random.Random(seed)
    with Image.open(source) as opened:
        image = opened.convert("RGB")

    box = _best_element_box(image, rng)
    element = image.crop(box)
    if rng.random() < 0.5:
        element = ImageOps.mirror(element)
    element = element.resize(
        (
            max(36, int(element.width * rng.uniform(0.78, 1.08))),
            max(30, int(element.height * rng.uniform(0.78, 1.08))),
        ),
        Image.Resampling.LANCZOS,
    )

    source_center = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    source_stats = ImageStat.Stat(element)
    source_mean = source_stats.mean
    source_variance = source_stats.var
    destinations = []
    for _ in range(80):
        x = rng.randint(18, image.width - element.width - 18)
        y = rng.randint(25, image.height - element.height - 25)
        distance = abs(x - source_center[0]) + abs(y - source_center[1])
        if distance > 250:
            target_stats = ImageStat.Stat(
                image.crop((x, y, x + element.width, y + element.height))
            )
            color_delta = sum(
                (source_mean[channel] - target_stats.mean[channel]) ** 2
                for channel in range(3)
            )
            texture_delta = sum(
                abs(source_variance[channel] - target_stats.var[channel])
                for channel in range(3)
            )
            destinations.append((color_delta + texture_delta * 0.18, x, y))
    if destinations:
        destinations.sort()
        _, x, y = rng.choice(destinations[: min(5, len(destinations))])
    else:
        x, y = image.width - element.width - 30, 40

    mask = Image.new("L", element.size, 0)
    inset = max(4, min(element.size) // 8)
    from PIL import ImageDraw

    ImageDraw.Draw(mask).rounded_rectangle(
        (inset, inset, element.width - inset, element.height - inset),
        radius=inset,
        fill=245,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(inset))
    image.paste(element, (x, y), mask)
    image.save(destination, "JPEG", quality=95, subsampling=0, optimize=True)
    return {
        "artifact": "Elemento del entorno agregado mediante composición sintética",
        "source_region": list(box),
        "added_at": [x, y, x + element.width, y + element.height],
    }


def build(output_folder):
    output_folder = output_folder.resolve()
    staging = output_folder / "_staging_curated"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    used_urls = set()
    entries = []
    index = 0

    for category, searches in GROUPS:
        category_count = 0
        for query, needed in searches:
            selected = 0
            for page in _search(query):
                candidate = _candidate(page, used_urls)
                if candidate is None:
                    continue
                info, url = candidate
                index += 1
                raw = staging / f"raw_{index:03d}"
                real = staging / f"real_{index:03d}.jpg"
                ai = staging / f"ia_{index:03d}.jpg"
                try:
                    _download(url, raw)
                    _normalize(raw, real)
                    synthetic = _add_synthetic_element(real, ai)
                except Exception as error:
                    index -= 1
                    print(f"  Omitida {page.get('title')}: {error}")
                    continue
                finally:
                    raw.unlink(missing_ok=True)

                metadata = info.get("extmetadata") or {}
                entry = {
                    "index": index,
                    "category": category,
                    "real_image": real.name,
                    "ai_image": ai.name,
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
                entries.append(entry)
                used_urls.add(url)
                selected += 1
                category_count += 1
                print(f"[{index:02d}/50] {category}: {page.get('title')}")
                if selected == needed:
                    break
            if selected != needed:
                raise RuntimeError(f"No se consiguieron {needed} fotos para: {query}")
        expected = 20 if category != "Ambiente petrolero" else 10
        if category_count != expected:
            raise RuntimeError(f"{category}: se esperaban {expected}, se obtuvieron {category_count}")

    if len(entries) != 50:
        raise RuntimeError(f"Se esperaban 50 imágenes, se obtuvieron {len(entries)}")

    for pattern in ("real_*.jpg", "ia_*.jpg"):
        for old_file in output_folder.glob(pattern):
            old_file.unlink()
    for generated in staging.glob("*.jpg"):
        shutil.move(str(generated), output_folder / generated.name)
    (output_folder / "coleccion_curada.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    shutil.rmtree(staging)
    return entries


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    collection = build(args.folder)
    print(f"\nColección terminada: {len(collection)} pares.")
