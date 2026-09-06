import os
import secrets
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "pairs")

os.makedirs(INSTANCE_DIR, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _secret_key():
    configured = os.environ.get("SECRET_KEY")
    if configured:
        return configured
    path = os.path.join(INSTANCE_DIR, ".secret-key")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as secret_file:
            return secret_file.read().strip()
    generated = secrets.token_urlsafe(48)
    with open(path, "x", encoding="utf-8") as secret_file:
        secret_file.write(generated)
    return generated


class Config:
    SECRET_KEY = _secret_key()
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(INSTANCE_DIR, "app.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = UPLOAD_FOLDER
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024  # 12 MB por request
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=10)
    SESSION_REFRESH_EACH_REQUEST = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in {
        "1", "true", "yes"
    }
    ADMIN_BOOTSTRAP_PASSWORD = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD")
    ADMIN_SESSION_LIFETIME = timedelta(hours=8)
    PROFILE_PHOTO_FOLDER = os.path.join(INSTANCE_DIR, "profile_photos")
