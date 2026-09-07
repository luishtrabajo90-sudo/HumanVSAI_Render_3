"""Generate new AI variants without modifying source real images."""
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "static" / "assets" / "images" / "IA"
GENERATOR_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(GENERATOR_DIR))
from generate_ai_variants import generate_variant

START_AI = 101


def main():
    sources = sorted(SOURCE_DIR.glob("real_*.jpg"))
    if not sources:
        raise SystemExit("No se encontraron fotos reales.")
    existing_ai = sorted(SOURCE_DIR.glob("ia_*.jpg"))
    next_index = START_AI
    generated = []
    for source in sources:
        destination = SOURCE_DIR / f"ia_{next_index:03d}.jpg"
        if destination.exists():
            raise SystemExit(f"El destino ya existe; no se sobrescribe: {destination.name}")
        artifacts = generate_variant(source, destination)
        generated.append({
            "source_real": source.name,
            "ai_image": destination.name,
            "artifacts": artifacts,
        })
        next_index += 1
        print(f"{source.name} -> {destination.name}", flush=True)

    manifest_path = SOURCE_DIR / "variantes_ia_append.json"
    manifest_path.write_text(json.dumps(generated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"EXISTING_AI={len(existing_ai)}")
    print(f"GENERATED_AI={len(generated)}")
    print(f"TOTAL_AI={len(existing_ai) + len(generated)}")
    print(f"MANIFEST={manifest_path}")


if __name__ == "__main__":
    main()
