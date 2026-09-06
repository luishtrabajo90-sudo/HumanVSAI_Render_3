import io
import os
import uuid

from flask import Blueprint, abort, current_app, jsonify, request, send_from_directory, session
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.exc import SQLAlchemyError

from .admin_auth import current_admin, validate_csrf
from .extensions import db
from .gamification import get_profile, profile_dict
from .models import PlayerProfile
from .visitor_session import current_visitor_session


profile_photo_bp = Blueprint("profile_photo", __name__)
MAX_PHOTO_BYTES = 2 * 1024 * 1024
MAX_PHOTO_DIMENSION = 8192
MAX_PHOTO_PIXELS = 40_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
FORMAT_MIME_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def _photo_directory():
    path = current_app.config.get(
        "PROFILE_PHOTO_FOLDER",
        os.path.join(current_app.instance_path, "profile_photos"),
    )
    os.makedirs(path, exist_ok=True)
    return path


def delete_profile_photo(filename):
    if not filename or os.path.basename(filename) != filename:
        return
    try:
        os.remove(os.path.join(_photo_directory(), filename))
    except FileNotFoundError:
        pass


def _current_profile():
    if current_admin() is not None:
        abort(403)
    if current_visitor_session() is None:
        abort(401)
    return get_profile()


@profile_photo_bp.get("/api/profile-photo/<string:player_id>")
def get_photo(player_id):
    player = db.session.get(PlayerProfile, player_id)
    if player is None or not player.photo_filename:
        abort(404)
    response = send_from_directory(
        _photo_directory(),
        player.photo_filename,
        mimetype="image/webp",
        conditional=True,
    )
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@profile_photo_bp.post("/api/profile/photo")
def upload_photo():
    player = _current_profile()
    validate_csrf()
    upload = request.files.get("photo")
    if upload is None or upload.mimetype not in ALLOWED_MIME_TYPES:
        return jsonify({"error": "La fotografía debe ser JPEG, PNG o WebP."}), 400
    raw = upload.stream.read(MAX_PHOTO_BYTES + 1)
    if len(raw) > MAX_PHOTO_BYTES:
        return jsonify({"error": "La fotografía supera el límite de 2 MB."}), 413
    temporary = None
    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.verify()
        with Image.open(io.BytesIO(raw)) as source:
            if (
                source.format not in ALLOWED_FORMATS
                or FORMAT_MIME_TYPES[source.format] != upload.mimetype
            ):
                raise ValueError("Formato no permitido.")
            if (
                min(source.size) < 32
                or max(source.size) > MAX_PHOTO_DIMENSION
                or source.width * source.height > MAX_PHOTO_PIXELS
            ):
                raise ValueError("Dimensiones no permitidas.")
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((512, 512), Image.Resampling.LANCZOS)
            filename = f"{uuid.uuid4().hex}.webp"
            temporary = os.path.join(_photo_directory(), f".{filename}.tmp")
            image.save(temporary, "WEBP", quality=82, method=6)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        if temporary:
            try:
                os.remove(temporary)
            except FileNotFoundError:
                pass
        return jsonify({"error": "La fotografía no es una imagen válida."}), 400

    final_path = os.path.join(_photo_directory(), filename)
    old_filename = player.photo_filename
    try:
        os.replace(temporary, final_path)
        player.photo_filename = filename
        player.photo_version = (player.photo_version or 0) + 1
        db.session.commit()
    except (OSError, SQLAlchemyError):
        db.session.rollback()
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass
        try:
            os.remove(final_path)
        except FileNotFoundError:
            pass
        current_app.logger.exception("No se pudo guardar la fotografía de perfil.")
        return jsonify({"error": "No se pudo guardar la fotografía."}), 500
    delete_profile_photo(old_filename)
    return jsonify({"profile": profile_dict(player)})


@profile_photo_bp.delete("/api/profile/photo")
def remove_photo():
    player = _current_profile()
    validate_csrf()
    old_filename = player.photo_filename
    player.photo_filename = None
    player.photo_version = (player.photo_version or 0) + 1
    db.session.commit()
    delete_profile_photo(old_filename)
    return jsonify({"profile": profile_dict(player)})
