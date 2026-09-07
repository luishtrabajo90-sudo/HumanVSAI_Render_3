"""Keep the GameImage catalog in sync with the local IA/Real image folders.

Drop image files into static/assets/images/Real (class REAL) or
static/assets/images/IA (class IA) and this sync makes them playable
automatically on the next app start, without running any script.
"""

from pathlib import Path

from .extensions import db
from .models import GameImage

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
FOLDER_CLASSES = (("Real", "REAL"), ("IA", "IA"))


def sync_game_images_from_folders(app):
    images_root = Path(app.static_folder) / "assets" / "images"
    found_urls = set()

    for folder_name, image_class in FOLDER_CLASSES:
        folder = images_root / folder_name
        if not folder.is_dir():
            continue
        for file_path in sorted(folder.iterdir()):
            if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            image_url = f"assets/images/{folder_name}/{file_path.name}"
            found_urls.add(image_url)
            existing = GameImage.query.filter_by(image_url=image_url).first()
            if existing is None:
                db.session.add(GameImage(
                    category=folder_name,
                    image_url=image_url,
                    image_class=image_class,
                    source_name="Carpeta local",
                    active=True,
                ))
            elif not existing.active:
                existing.active = True

    stale_query = GameImage.query.filter(GameImage.image_url.like("assets/images/%"))
    if found_urls:
        stale_query = stale_query.filter(~GameImage.image_url.in_(found_urls))
    for image in stale_query.all():
        image.active = False

    db.session.commit()
