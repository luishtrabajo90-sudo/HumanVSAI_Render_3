import os
import uuid

from flask import current_app
from werkzeug.utils import secure_filename


def allowed_file(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in current_app.config["ALLOWED_EXTENSIONS"]


def save_pair_image(file_storage, pair_id, role):
    """Guarda una imagen subida para un par en static/uploads/pairs/<pair_id>/<role>.<ext>.

    role es 'ai' o 'real'. Devuelve la ruta relativa (para servir vía /static/...)
    o None si no se proporcionó archivo válido.
    """
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        raise ValueError("Extensión de archivo no permitida. Usa png, jpg, jpeg o webp.")

    ext = secure_filename(file_storage.filename).rsplit(".", 1)[-1].lower()
    pair_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(pair_id))
    os.makedirs(pair_dir, exist_ok=True)

    # nombre único para evitar problemas de caché del navegador al reemplazar
    filename = f"{role}_{uuid.uuid4().hex[:8]}.{ext}"
    abs_path = os.path.join(pair_dir, filename)
    file_storage.save(abs_path)

    rel_path = f"uploads/pairs/{pair_id}/{filename}"
    return rel_path


def delete_pair_files(pair):
    base = current_app.config["UPLOAD_FOLDER"]
    pair_dir = os.path.join(base, str(pair.id))
    if os.path.isdir(pair_dir):
        for name in os.listdir(pair_dir):
            try:
                os.remove(os.path.join(pair_dir, name))
            except OSError:
                pass
        try:
            os.rmdir(pair_dir)
        except OSError:
            pass


def remove_old_image(rel_path):
    if not rel_path:
        return
    from flask import current_app as app

    abs_path = os.path.join(app.static_folder, rel_path)
    if os.path.isfile(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass
