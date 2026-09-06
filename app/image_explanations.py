"""Generate image-specific educational feedback from local visual analysis."""

import hashlib
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError


@dataclass(frozen=True)
class VisualProfile:
    brightness: float
    contrast: float
    saturation: float
    detail: float
    symmetry: float
    center_detail: float


DETECTIVE_TIPS = (
    "Compara la dirección de las sombras con la fuente de luz más intensa.",
    "Revisa las transiciones finas entre el sujeto principal y el fondo.",
    "Busca reflejos que no correspondan con los objetos visibles en la escena.",
    "Observa si las texturas cambian de forma abrupta en zonas cercanas.",
    "Examina los contornos pequeños: suelen revelar uniones o recortes extraños.",
    "Evalúa si el desenfoque aumenta de manera natural con la distancia.",
    "Compara detalles repetidos; la realidad rara vez produce copias idénticas.",
    "Mira las zonas oscuras: deberían conservar ruido y detalle de forma coherente.",
    "Comprueba si los brillos siguen la curvatura real de cada superficie.",
    "Busca una simetría excesiva en formas, accesorios o elementos del entorno.",
    "Revisa si la nitidez del sujeto coincide con la del plano donde se encuentra.",
    "Analiza las áreas de alto contraste: bordes y halos pueden delatar una síntesis.",
    "Observa si el color de la luz se mantiene en sujeto, fondo y reflejos.",
    "Inspecciona elementos parcialmente ocultos y verifica que continúen con lógica.",
    "Compara el detalle del centro con las esquinas y el fondo de la fotografía.",
    "Busca pequeñas imperfecciones naturales en materiales, piel o superficies.",
    "Evalúa si cada objeto proyecta una sombra acorde con su volumen y posición.",
    "Revisa patrones finos como hojas, cabello, rejillas, telas o piedras.",
    "Observa la profundidad: los tamaños relativos deben concordar con la distancia.",
    "No te guíes por lo espectacular; verifica primero la coherencia física global.",
)

SIMPLE_AI_CUES = (
    "se ve un borde raro",
    "una textura cambia de golpe",
    "hay un detalle repetido",
    "una sombra no encaja",
    "el fondo pierde su forma",
    "una parte se ve demasiado lisa",
    "la nitidez cambia sin razón",
    "algunos detalles no encajan entre sí",
)

SIMPLE_REAL_CUES = (
    "la luz y las sombras encajan",
    "las texturas tienen cambios naturales",
    "los bordes se ven normales",
    "los reflejos coinciden con la escena",
    "el enfoque cambia poco a poco",
    "hay pequeñas imperfecciones naturales",
    "el fondo mantiene sus formas",
    "los detalles se ven parejos",
)

SIMPLE_NEXT_TIPS = (
    "mira si las sombras siguen la luz",
    "revisa si los bordes se ven raros",
    "compara el sujeto con el fondo",
    "busca detalles repetidos",
    "mira si los reflejos tienen sentido",
    "revisa manos, ojos y cabello",
    "observa si las texturas cambian de golpe",
    "mira si el enfoque cambia de forma natural",
    "busca zonas demasiado lisas",
    "compara los detalles claros y oscuros",
    "revisa si los objetos mantienen su forma",
    "busca pequeñas imperfecciones naturales",
)


def _seed(*parts):
    value = "|".join(str(part) for part in parts)
    return int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big")


def _scaled_detail(image):
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    return min(100.0, ImageStat.Stat(edges).mean[0] / 42.0 * 100.0)


@lru_cache(maxsize=256)
def analyze_image(path_string):
    path = Path(path_string)
    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((320, 240), Image.Resampling.LANCZOS)
    except (OSError, UnidentifiedImageError):
        seeded = random.Random(_seed(path_string))
        return VisualProfile(*(seeded.uniform(35, 75) for _ in range(6)))

    gray = image.convert("L")
    brightness = ImageStat.Stat(gray).mean[0] / 255.0 * 100.0
    contrast = min(100.0, ImageStat.Stat(gray).stddev[0] / 72.0 * 100.0)
    saturation = ImageStat.Stat(image.convert("HSV").getchannel("S")).mean[0] / 255.0 * 100.0
    detail = _scaled_detail(image)

    mirrored = ImageOps.mirror(gray)
    symmetry = 100.0 - ImageStat.Stat(ImageChops.difference(gray, mirrored)).mean[0] / 255.0 * 100.0

    width, height = image.size
    center = image.crop((width // 4, height // 4, width * 3 // 4, height * 3 // 4))
    center_detail = _scaled_detail(center)
    return VisualProfile(brightness, contrast, saturation, detail, symmetry, center_detail)


def _level(value, low, high, labels):
    if value < low:
        return labels[0]
    if value > high:
        return labels[2]
    return labels[1]


def _visual_summary(profile):
    light = _level(profile.brightness, 38, 67, ("luz contenida", "iluminación equilibrada", "luz intensa"))
    contrast = _level(profile.contrast, 35, 63, ("contraste suave", "contraste moderado", "contraste marcado"))
    detail = _level(profile.detail, 24, 50, ("detalle delicado", "detalle definido", "microdetalle abundante"))
    color = _level(profile.saturation, 25, 58, ("color sobrio", "color natural", "color muy saturado"))
    return light, contrast, detail, color


def detective_tip(pair_id, image_id, image_path, used_tips=()):
    profile = analyze_image(str(image_path))
    light, contrast, detail, color = _visual_summary(profile)
    candidates = list(DETECTIVE_TIPS)
    random.Random(_seed(pair_id, image_id, light, contrast, detail, color)).shuffle(candidates)
    used = set(used_tips)
    return next((tip for tip in candidates if tip not in used), candidates[0])


def _simple_next_tip(rng, used_tips):
    candidates = list(SIMPLE_NEXT_TIPS)
    rng.shuffle(candidates)
    used = set(used_tips)
    return next((tip for tip in candidates if tip not in used), candidates[0])


def build_feedback(
    pair,
    image_id,
    image_class,
    image_path,
    used_tips=(),
):
    profile = analyze_image(str(image_path))
    rng = random.Random(
        _seed(pair.id, image_id, image_class, pair.category, *profile.__dict__.values())
    )
    category = (pair.category or "esta escena").lower()

    if image_class == "IA":
        simple_cue = rng.choice(SIMPLE_AI_CUES)
        reason = f"Era IA: {simple_cue} en esta imagen de {category}."
    else:
        simple_cue = rng.choice(SIMPLE_REAL_CUES)
        reason = f"Era REAL: {simple_cue} en esta imagen de {category}."

    next_tip = _simple_next_tip(rng, used_tips)
    summary = f"{reason} Para la próxima, {next_tip}."
    return {
        "reason": reason,
        "explanation": summary,
        "next_tip": next_tip,
        "summary": summary,
    }
