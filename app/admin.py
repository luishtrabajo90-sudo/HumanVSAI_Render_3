import uuid
import re
from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, session, url_for,
)
from sqlalchemy import func

from .admin_auth import (
    ADMIN_ACCOUNTS,
    ADMIN_PROFILE_NAMES,
    ADMIN_INITIAL_PASSWORDS,
    admin_required,
    authenticate_admin,
    audit,
    clear_login_failures,
    csrf_token,
    current_admin,
    current_pending_admin,
    login_is_limited,
    login_rate_key,
    normalize_username,
    record_login_failure,
    set_admin_password,
    start_admin_session,
    start_password_change_session,
    validate_csrf,
)
from .extensions import db
from .models import (
    IMAGE_CLASSES, AdminUser, ImagePair, PlayerProfile, Settings, VisitorSession,
)
from .utils import delete_pair_files, remove_old_image, save_pair_image

admin_bp = Blueprint("admin", __name__)
PLAYER_NAME_PATTERN = re.compile(
    r"^(?=.{1,30}$)[A-Za-z0-9]+(?: +[A-Za-z0-9]+)*$"
)


@admin_bp.before_request
def protect_admin():
    if request.endpoint in {"admin.login", "admin.first_login", "admin.forgot_password"}:
        if request.method == "POST":
            validate_csrf()
        return None
    if current_admin() is None:
        if request.method != "GET":
            abort(401, description="Acceso restringido. No posee permisos de administrador.")
        flash("Acceso restringido. No posee permisos de administrador.", "error")
        return redirect(url_for("admin.login"))
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        validate_csrf()
    return None


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_admin() is not None:
        return redirect(url_for("admin.pairs_list"))
    error = None
    if request.method == "POST":
        username = normalize_username(request.form.get("username"))
        key = login_rate_key(username)
        if login_is_limited(key):
            error = "No se pudo iniciar sesión. Espera un minuto e inténtalo de nuevo."
            return render_template("admin/login.html", error=error), 429
        admin = authenticate_admin(username, request.form.get("password", ""))
        if admin is None:
            if username in ADMIN_ACCOUNTS:
                record_login_failure(key)
            error = "Usuario o contraseña incorrectos."
        else:
            clear_login_failures(key)
            if admin.password_change_required:
                start_password_change_session(admin)
                return redirect(url_for("admin.first_login"))
            start_admin_session(admin)
            audit("login", "admin", admin.id)
            db.session.commit()
            return redirect(url_for("admin.pairs_list"))
    csrf_token()
    return render_template("admin/login.html", error=error)


@admin_bp.route("/first-login", methods=["GET", "POST"])
def first_login():
    admin = current_pending_admin()
    if admin is None:
        return redirect(url_for("admin.login"))
    error = None
    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        initial_password = ADMIN_INITIAL_PASSWORDS.get(admin.username, "")
        if len(new_password) < 8:
            error = "La nueva contraseña debe tener al menos 8 caracteres."
        elif new_password != confirm_password:
            error = "Las contraseñas no coinciden."
        elif new_password == initial_password:
            error = "La nueva contraseña debe ser distinta a la contraseña inicial."
        else:
            set_admin_password(admin, new_password, require_change=False)
            db.session.commit()
            start_admin_session(admin)
            audit("password_change", "admin", admin.id)
            db.session.commit()
            flash("Contraseña actualizada correctamente.", "success")
            return redirect(url_for("admin.pairs_list"))
    csrf_token()
    return render_template("admin/first_login.html", admin=admin, error=error)


@admin_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    message = None
    if request.method == "POST":
        username = normalize_username(request.form.get("username"))
        if username in ADMIN_ACCOUNTS:
            message = (
                "Solicite a un administrador autorizado restablecer su contraseña "
                "desde el panel administrativo."
            )
        else:
            message = "Si el usuario es administrador, recibirá instrucciones de restablecimiento."
    csrf_token()
    return render_template("admin/forgot_password.html", message=message)


@admin_bp.route("/change-password", methods=["GET", "POST"])
@admin_required
def change_password():
    admin = current_admin()
    error = None
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not authenticate_admin(admin.username, current_password):
            error = "Usuario o contraseña incorrectos."
        elif len(new_password) < 8:
            error = "La nueva contraseña debe tener al menos 8 caracteres."
        elif new_password != confirm_password:
            error = "Las contraseñas no coinciden."
        elif new_password == current_password:
            error = "La nueva contraseña debe ser distinta a la actual."
        else:
            set_admin_password(admin, new_password, require_change=False)
            audit("password_change", "admin", admin.id)
            db.session.commit()
            flash("Contraseña actualizada correctamente.", "success")
            return redirect(url_for("admin.pairs_list"))
    return render_template("admin/change_password.html", error=error)


@admin_bp.route("/admins/password-reset", methods=["GET", "POST"])
@admin_required
def reset_admin_password():
    admins = AdminUser.query.filter(AdminUser.username.in_(ADMIN_ACCOUNTS)).order_by(AdminUser.username).all()
    if request.method == "POST":
        username = normalize_username(request.form.get("username"))
        if username not in ADMIN_ACCOUNTS:
            flash("Acceso restringido. No posee permisos de administrador.", "error")
            return render_template("admin/reset_password.html", admins=admins), 403
        target = AdminUser.query.filter_by(username=username, active=True).first()
        if target is None:
            flash("Administrador no encontrado.", "error")
            return render_template("admin/reset_password.html", admins=admins), 404
        temporary_password = ADMIN_INITIAL_PASSWORDS[username]
        set_admin_password(target, temporary_password, require_change=True)
        audit("password_reset", "admin", target.id)
        db.session.commit()
        flash(
            f"Contraseña restablecida para {target.username}. Debe cambiarla en el próximo inicio.",
            "success",
        )
        return redirect(url_for("admin.reset_admin_password"))
    return render_template("admin/reset_password.html", admins=admins)


@admin_bp.post("/logout")
@admin_required
def logout():
    audit("logout", "admin", current_admin().id)
    db.session.commit()
    session.clear()
    return redirect(url_for("game.index"))


def _image_class(field, default):
    value = request.form.get(field, default).upper()
    return value if value in IMAGE_CLASSES else default


def _valid_player_name(name):
    return bool(PLAYER_NAME_PATTERN.fullmatch(name))


def _player_name_exists(name, exclude_id=None):
    return (
        PlayerProfile.query
        .filter(PlayerProfile.id != exclude_id, PlayerProfile.name == name)
        .first()
        is not None
    )


@admin_bp.route("/pairs")
@admin_required
def pairs_list():
    pairs = ImagePair.query.order_by(ImagePair.id.desc()).all()
    return render_template("admin/pairs_list.html", pairs=pairs)


@admin_bp.route("/pairs/new", methods=["GET", "POST"])
@admin_required
def pair_new():
    if request.method == "POST":
        pair = ImagePair(
            category=request.form.get("category", "").strip(),
            tell="",
            realtip="",
            ai_image_class=_image_class("ai_image_class", "IA"),
            real_image_class=_image_class("real_image_class", "REAL"),
            active=bool(request.form.get("active")),
        )
        db.session.add(pair)
        db.session.flush()
        try:
            ai_path = save_pair_image(request.files.get("ai_image"), pair.id, "ai")
            real_path = save_pair_image(request.files.get("real_image"), pair.id, "real")
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "error")
            return render_template("admin/pair_form.html", pair=None), 400
        pair.ai_image_path = ai_path or pair.ai_image_path
        pair.real_image_path = real_path or pair.real_image_path
        audit("create", "image_pair", pair.id)
        db.session.commit()
        flash("Par creado correctamente.", "success")
        return redirect(url_for("admin.pairs_list"))
    return render_template("admin/pair_form.html", pair=None)


@admin_bp.route("/pairs/<int:pair_id>/edit", methods=["GET", "POST"])
@admin_required
def pair_edit(pair_id):
    pair = ImagePair.query.get_or_404(pair_id)
    if request.method == "POST":
        pair.category = request.form.get("category", "").strip()
        pair.ai_image_class = _image_class("ai_image_class", "IA")
        pair.real_image_class = _image_class("real_image_class", "REAL")
        pair.active = bool(request.form.get("active"))
        try:
            ai_path = save_pair_image(request.files.get("ai_image"), pair.id, "ai")
            real_path = save_pair_image(request.files.get("real_image"), pair.id, "real")
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "error")
            return render_template("admin/pair_form.html", pair=pair), 400
        if ai_path:
            remove_old_image(pair.ai_image_path)
            pair.ai_image_path = ai_path
        if real_path:
            remove_old_image(pair.real_image_path)
            pair.real_image_path = real_path
        audit("update", "image_pair", pair.id)
        db.session.commit()
        flash("Par actualizado.", "success")
        return redirect(url_for("admin.pairs_list"))
    return render_template("admin/pair_form.html", pair=pair)


@admin_bp.post("/pairs/<int:pair_id>/delete")
@admin_required
def pair_delete(pair_id):
    pair = ImagePair.query.get_or_404(pair_id)
    audit("delete", "image_pair", pair.id)
    delete_pair_files(pair)
    db.session.delete(pair)
    db.session.commit()
    flash("Par eliminado.", "success")
    return redirect(url_for("admin.pairs_list"))


@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings_view():
    settings = Settings.get()
    if request.method == "POST":
        try:
            timer = int(request.form.get("timer_seconds", 15))
        except ValueError:
            timer = 15
        settings.timer_seconds = max(3, min(120, timer))
        settings.sound_effects_enabled = bool(request.form.get("sound_effects_enabled"))
        settings.visual_effects_enabled = bool(request.form.get("visual_effects_enabled"))
        audit("update", "settings", settings.id)
        db.session.commit()
        flash("Configuración guardada.", "success")
        return redirect(url_for("admin.settings_view"))
    return render_template("admin/settings.html", settings=settings)


@admin_bp.get("/players")
@admin_required
def players_list():
    players = (
        PlayerProfile.query
        .filter(
            ~PlayerProfile.id.like("admin-%"),
            ~func.lower(func.trim(PlayerProfile.name)).in_(tuple(ADMIN_PROFILE_NAMES)),
        )
        .order_by(PlayerProfile.created_at.desc())
        .all()
    )
    visitors = {
        visitor.player_id: visitor
        for visitor in VisitorSession.query.filter(
            VisitorSession.player_id.in_([player.id for player in players])
        ).all()
    } if players else {}
    return render_template(
        "admin/players_list.html",
        players=players,
        visitors=visitors,
        now=datetime.now(timezone.utc).replace(tzinfo=None),
    )


@admin_bp.route("/players/new", methods=["GET", "POST"])
@admin_required
def player_new():
    if request.method == "POST":
        name = " ".join(request.form.get("name", "").split())
        if not _valid_player_name(name):
            flash("Usa entre 1 y 30 letras o números, sin espacios ni símbolos.", "error")
            return render_template("admin/player_form.html", player=None, entered_name=name), 400
        if normalize_username(name) in ADMIN_ACCOUNTS:
            flash("Ese nombre está reservado para una cuenta administrativa.", "error")
            return render_template("admin/player_form.html", player=None, entered_name=name), 409
        if _player_name_exists(name):
            flash("Ya existe un jugador con ese nombre.", "error")
            return render_template("admin/player_form.html", player=None, entered_name=name), 409
        now = datetime.now(timezone.utc)
        player = PlayerProfile(
            id=str(uuid.uuid4()),
            name=name,
            last_activity_at=now,
            expires_at=now + timedelta(hours=24),
        )
        db.session.add(player)
        db.session.flush()
        audit("create", "player", player.id)
        db.session.commit()
        flash("Jugador creado.", "success")
        return redirect(url_for("admin.players_list"))
    return render_template("admin/player_form.html", player=None, entered_name="")


@admin_bp.route("/players/<string:player_id>/edit", methods=["GET", "POST"])
@admin_required
def player_edit(player_id):
    player = db.get_or_404(PlayerProfile, player_id)
    if request.method == "POST":
        name = " ".join(request.form.get("name", "").split())
        if not _valid_player_name(name):
            flash("Usa entre 1 y 30 letras o números, sin espacios ni símbolos.", "error")
            return render_template("admin/player_form.html", player=player, entered_name=name), 400
        if normalize_username(name) in ADMIN_ACCOUNTS:
            flash("Ese nombre está reservado para una cuenta administrativa.", "error")
            return render_template("admin/player_form.html", player=player, entered_name=name), 409
        if _player_name_exists(name, player.id):
            flash("Ya existe un jugador con ese nombre.", "error")
            return render_template("admin/player_form.html", player=player, entered_name=name), 409
        player.name = name
        visitor = VisitorSession.query.filter_by(player_id=player.id).first()
        if visitor:
            visitor.normalized_name = name
        audit("update", "player", player.id)
        db.session.commit()
        flash("Jugador actualizado.", "success")
        return redirect(url_for("admin.players_list"))
    return render_template("admin/player_form.html", player=player, entered_name=player.name)


@admin_bp.post("/players/<string:player_id>/delete")
@admin_required
def player_delete(player_id):
    if player_id.startswith("admin-"):
        abort(403)
    player = db.get_or_404(PlayerProfile, player_id)
    photo_filename = player.photo_filename
    audit("delete", "player", player.id)
    VisitorSession.query.filter_by(player_id=player.id).delete(synchronize_session=False)
    from .models import MissionResult, PlayerSeenImage
    MissionResult.query.filter_by(player_id=player.id).delete(synchronize_session=False)
    PlayerSeenImage.query.filter_by(player_id=player.id).delete(synchronize_session=False)
    db.session.delete(player)
    db.session.commit()
    if photo_filename:
        from .profile_photo import delete_profile_photo
        delete_profile_photo(photo_filename)
    flash("Jugador eliminado. El nombre puede registrarse nuevamente.", "success")
    return redirect(url_for("admin.players_list"))


@admin_bp.post("/players/<string:player_id>/end-session")
@admin_required
def player_end_session(player_id):
    if player_id.startswith("admin-"):
        abort(403)
    visitor = VisitorSession.query.filter_by(player_id=player_id).first_or_404()
    now = datetime.now(timezone.utc)
    if visitor.ended_at is None:
        visitor.ended_at = now
        visitor.end_reason = "admin"
        visitor.session_token = None
        visitor.current_image_path = None
        visitor.current_image_url = None
        visitor.round_expires_at = None
        audit("end_session", "visitor_session", visitor.id)
        db.session.commit()
        flash("Sesión del jugador cerrada.", "success")
    else:
        flash("La sesión del jugador ya estaba finalizada.", "info")
    return redirect(url_for("admin.players_list"))
