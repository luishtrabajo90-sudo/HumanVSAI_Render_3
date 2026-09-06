r"""Create educational AI-style variants from a folder of real photographs.

The transformations are local and deterministic. They preserve the source
resolution and framing while introducing subtle visual inconsistencies useful
for the Real vs. AI game.

Usage:
    python scripts/generate_ai_variants.py C:\path\to\images
"""

import argparse
import hashlib
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps


def _seed_for(path):
    digest = hashlib.sha256(path.read_bytes()).digest()
    return int.from_bytes(digest[:8], "big")


def _feather_mask(size, radius=10, opacity=255):
    mask = Image.new("L", size, 0)
    inset = max(2, radius)
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset, inset, size[0] - inset, size[1] - inset),
        radius=radius,
        fill=opacity,
    )
    return mask.filter(ImageFilter.GaussianBlur(radius))


def _peripheral_box(rng, width, height, min_scale=0.10, max_scale=0.18):
    box_w = int(width * rng.uniform(min_scale, max_scale))
    box_h = int(height * rng.uniform(min_scale, max_scale))
    side = rng.choice(("left", "right", "top", "bottom"))
    if side == "left":
        x = rng.randint(8, max(8, min(int(width * 0.24), width - box_w - 8)))
        y = rng.randint(8, max(8, height - box_h - 8))
    elif side == "right":
        high = max(8, width - box_w - 8)
        x = rng.randint(min(max(8, int(width * 0.76)), high), high)
        y = rng.randint(8, max(8, height - box_h - 8))
    elif side == "top":
        x = rng.randint(8, max(8, width - box_w - 8))
        y = rng.randint(8, max(8, min(int(height * 0.22), height - box_h - 8)))
    else:
        x = rng.randint(8, max(8, width - box_w - 8))
        high = max(8, height - box_h - 8)
        y = rng.randint(min(max(8, int(height * 0.78)), high), high)
    return x, y, x + box_w, y + box_h


def _duplicate_object(image, rng):
    width, height = image.size
    box = _peripheral_box(rng, width, height)
    patch = image.crop(box)
    if rng.random() < 0.35:
        patch = ImageOps.mirror(patch)
    shift_x = int(patch.width * rng.choice((-0.75, 0.75)))
    shift_y = int(patch.height * rng.uniform(-0.3, 0.3))
    x = min(max(4, box[0] + shift_x), width - patch.width - 4)
    y = min(max(4, box[1] + shift_y), height - patch.height - 4)
    mask = _feather_mask(patch.size, max(6, patch.width // 14), 230)
    image.paste(patch, (x, y), mask)
    return "Objeto o elemento del fondo duplicado"


def _distort_perspective(image, rng):
    width, height = image.size
    box = _peripheral_box(rng, width, height, 0.13, 0.22)
    patch = image.crop(box)
    dx = max(3, int(patch.width * rng.uniform(0.04, 0.09)))
    dy = max(3, int(patch.height * rng.uniform(0.04, 0.09)))
    quad = (
        rng.randint(0, dx),
        rng.randint(0, dy),
        patch.width - rng.randint(0, dx),
        rng.randint(0, dy),
        patch.width - rng.randint(0, dx),
        patch.height - rng.randint(0, dy),
        rng.randint(0, dx),
        patch.height - rng.randint(0, dy),
    )
    warped = patch.transform(
        patch.size,
        Image.Transform.QUAD,
        quad,
        resample=Image.Resampling.BICUBIC,
    )
    mask = _feather_mask(patch.size, max(8, patch.width // 12), 235)
    image.paste(warped, box[:2], mask)
    return "Perspectiva local ligeramente incompatible"


def _add_false_shadow(image, rng):
    width, height = image.size
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    ellipse_w = int(width * rng.uniform(0.12, 0.22))
    ellipse_h = int(height * rng.uniform(0.025, 0.06))
    x = rng.choice(
        (
            rng.randint(10, max(10, int(width * 0.25))),
            rng.randint(max(10, int(width * 0.65)), width - ellipse_w - 10),
        )
    )
    y = rng.randint(int(height * 0.55), height - ellipse_h - 10)
    draw.ellipse(
        (x, y, x + ellipse_w, y + ellipse_h),
        fill=(18, 27, 49, rng.randint(38, 62)),
    )
    overlay = overlay.filter(ImageFilter.GaussianBlur(max(7, ellipse_h // 3)))
    image.alpha_composite(overlay)
    return "Sombra suave sin una fuente de luz coherente"


def _repeat_texture(image, rng):
    width, height = image.size
    tile_w = int(width * rng.uniform(0.035, 0.055))
    tile_h = int(height * rng.uniform(0.04, 0.065))
    box = _peripheral_box(rng, width, height, 0.07, 0.10)
    tile = image.crop((box[0], box[1], box[0] + tile_w, box[1] + tile_h))
    cols, rows = rng.choice(((3, 2), (2, 3), (3, 1)))
    repeated = Image.new("RGBA", (tile_w * cols, tile_h * rows))
    for row in range(rows):
        for col in range(cols):
            repeated.paste(tile, (col * tile_w, row * tile_h))
    x = min(box[0], width - repeated.width - 4)
    y = min(box[1], height - repeated.height - 4)
    mask = _feather_mask(repeated.size, max(5, tile_w // 5), 205)
    image.paste(repeated, (x, y), mask)
    return "Patrón del fondo repetido de forma artificial"


def _bend_edge(image, rng):
    width, height = image.size
    box = _peripheral_box(rng, width, height, 0.09, 0.16)
    patch = image.crop(box)
    expanded = patch.resize(
        (patch.width + max(4, patch.width // 12), patch.height),
        Image.Resampling.LANCZOS,
    )
    expanded = expanded.crop((0, 0, patch.width, patch.height))
    expanded = ImageEnhance.Sharpness(expanded).enhance(0.7)
    mask = _feather_mask(patch.size, max(6, patch.width // 12), 220)
    image.paste(expanded, box[:2], mask)
    return "Borde local estirado o deformado"


def _subtle_reflection_mismatch(image, rng):
    width, height = image.size
    box = _peripheral_box(rng, width, height, 0.08, 0.13)
    original = image.crop(box)
    reflected = ImageEnhance.Brightness(ImageOps.mirror(original)).enhance(
        rng.uniform(0.97, 1.04)
    )
    offset = rng.randint(2, max(3, original.width // 18))
    patch = original.copy()
    patch.paste(reflected.crop((0, 0, patch.width - offset, patch.height)), (offset, 0))
    patch.paste(reflected.crop((patch.width - offset, 0, patch.width, patch.height)), (0, 0))
    mask = _feather_mask(
        patch.size,
        max(8, patch.width // 9),
        rng.randint(48, 72),
    )
    image.paste(patch, box[:2], mask)
    return "Reflejo o textura local apenas desalineado"


TRANSFORMS = (
    _duplicate_object,
    _distort_perspective,
    _add_false_shadow,
    _repeat_texture,
    _bend_edge,
)


def generate_variant(source, destination):
    rng = random.Random(_seed_for(source))
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
        original_size = opened.size

    selected = rng.sample(TRANSFORMS, 4)
    artifacts = [transform(image, rng) for transform in selected]
    artifacts.append(_subtle_reflection_mismatch(image, rng))
    result = image.convert("RGB")
    if result.size != original_size:
        raise RuntimeError(f"La resolución cambió para {source.name}")
    result.save(destination, "JPEG", quality=95, subsampling=0, optimize=True)
    return artifacts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    folder = args.folder.resolve()
    sources = sorted(folder.glob("real_*.jpg"))
    if not sources:
        raise SystemExit(f"No se encontraron archivos real_*.jpg en {folder}")

    manifest = []
    for index, source in enumerate(sources, 1):
        destination = folder / source.name.replace("real_", "ia_", 1)
        artifacts = generate_variant(source, destination)
        manifest.append(
            {
                "real_image": source.name,
                "ai_image": destination.name,
                "artifacts": artifacts,
            }
        )
        print(f"[{index:02d}/{len(sources):02d}] {destination.name}")

    manifest_path = folder / "variantes_ia.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nGeneradas {len(manifest)} variantes. Detalles: {manifest_path}")


if __name__ == "__main__":
    main()
