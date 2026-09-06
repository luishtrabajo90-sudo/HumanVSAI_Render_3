import hmac
import secrets
import time
from functools import wraps

from datetime import datetime, timezone

from flask import abort, current_app, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .models import AdminAudit, AdminUser


ROLE_ADMIN = "ADMIN"
ROLE_GUEST = "GUEST"
ADMIN_ACCOUNTS = {
    "admin": "Administrador",
    "dcanache": "David Canache",
    "lhernandez": "Luis Hernandez",
    "cmoron": "Carlos Moron",
    "emartinez": "Esdras Martinez",
    "hpinto": "H Pinto",
    "epinto": "E Pinto",
}
ADMIN_INITIAL_PASSWORDS = {
    "admin": "admin",
    "dcanache": "12345677",
    "cmoron": "12345677",
    "emartinez": "12345677",
    "lhernandez": "12345677",
    "hpinto": "12345677",
    "epinto": "12345677",
}
SHARED_PASSWORD_ADMINS = frozenset({
    "cmoron",
    "lhernandez",
    "emartinez",
    "hpinto",
})
LOGIN_WINDOW_SECONDS = 60
LOGIN_MAX_FAILURES = 5
_login_failures = {}


def normalize_username(value):
    return str(value or "").strip().casefold()


ADMIN_PROFILE_NAMES = frozenset(
    normalize_username(value)
    for value in (*ADMIN_ACCOUNTS.keys(), *ADMIN_ACCOUNTS.values())
)


def bootstrap_admins(password):
    for username, full_name in ADMIN_ACCOUNTS.items():
        initial_password = ADMIN_INITIAL_PASSWORDS[username]
        require_password_change = username not in SHARED_PASSWORD_ADMINS
        admin = AdminUser.query.filter_by(username=username).first()
        if admin is None:
            admin = AdminUser(
                username=username,
                password_hash=generate_password_hash(initial_password, method="scrypt"),
                role=ROLE_ADMIN,
                password_change_required=require_password_change,
                active=True,
            )
            db.session.add(admin)
        elif check_password_hash(admin.password_hash, initial_password):
            admin.password_change_required = require_password_change
        admin.full_name = full_name
        admin.role = ROLE_ADMIN
        admin.active = True
    db.session.commit()


def current_admin():
    admin_id = session.get("admin_id")
    if not admin_id or session.get("role") not in {ROLE_ADMIN, "admin"}:
        return None
    admin = db.session.get(AdminUser, admin_id)
    if (
        admin is None
        or not admin.active
        or admin.username not in ADMIN_ACCOUNTS
        or admin.role != ROLE_ADMIN
        or admin.password_change_required
    ):
        session.clear()
        return None
    return admin


def authenticate_admin(username, password):
    normalized = normalize_username(username)
    if normalized not in ADMIN_ACCOUNTS:
        return None
    admin = AdminUser.query.filter_by(username=normalized, active=True).first()
    if admin is None or not check_password_hash(admin.password_hash, password or ""):
        return None
    return admin


def start_admin_session(admin):
    session.clear()
    session.permanent = False
    session["admin_id"] = admin.id
    session["role"] = ROLE_ADMIN
    session["display_name"] = admin.full_name
    session["admin_csrf_token"] = secrets.token_urlsafe(32)
    session["admin_authenticated_at"] = datetime.now(timezone.utc).isoformat()


def start_password_change_session(admin):
    session.clear()
    session.permanent = False
    session["pending_admin_id"] = admin.id
    session["role"] = ROLE_ADMIN
    session["display_name"] = admin.full_name
    session["admin_csrf_token"] = secrets.token_urlsafe(32)
    session["admin_authenticated_at"] = datetime.now(timezone.utc).isoformat()


def current_pending_admin():
    admin_id = session.get("pending_admin_id")
    if not admin_id or session.get("role") != ROLE_ADMIN:
        return None
    admin = db.session.get(AdminUser, admin_id)
    if (
        admin is None
        or not admin.active
        or admin.username not in ADMIN_ACCOUNTS
        or admin.role != ROLE_ADMIN
    ):
        session.clear()
        return None
    return admin


def set_admin_password(admin, password, require_change=False):
    admin.password_hash = generate_password_hash(password, method="scrypt")
    admin.password_change_required = require_change
    admin.updated_at = datetime.now(timezone.utc)


def clear_session_preserving_csrf():
    token = session.get("admin_csrf_token")
    session.clear()
    if token:
        session["admin_csrf_token"] = token


def csrf_token():
    token = session.get("admin_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["admin_csrf_token"] = token
    return token


def validate_csrf():
    json_data = request.get_json(silent=True) if request.is_json else {}
    supplied = (
        request.form.get("csrf_token")
        or (json_data or {}).get("csrf_token")
        or request.headers.get("X-CSRF-Token")
    )
    expected = session.get("admin_csrf_token")
    if not supplied or not expected or not hmac.compare_digest(supplied, expected):
        abort(403, description="Solicitud administrativa inválida.")


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_admin() is None:
            if request.method != "GET":
                abort(401)
            return redirect(url_for("admin.login"))
        return view(*args, **kwargs)
    return wrapped


def audit(action, entity_type, entity_id=""):
    admin = current_admin()
    if admin is None:
        abort(401)
    db.session.add(AdminAudit(
        admin_id=admin.id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
    ))


def login_rate_key(username):
    return (request.remote_addr or "local", normalize_username(username))


def login_is_limited(key):
    now = time.monotonic()
    attempts = [stamp for stamp in _login_failures.get(key, []) if now - stamp < LOGIN_WINDOW_SECONDS]
    _login_failures[key] = attempts
    return len(attempts) >= LOGIN_MAX_FAILURES


def record_login_failure(key):
    if len(_login_failures) >= 1000:
        now = time.monotonic()
        expired = [
            stored_key for stored_key, attempts in _login_failures.items()
            if not attempts or now - attempts[-1] >= LOGIN_WINDOW_SECONDS
        ]
        for stored_key in expired:
            _login_failures.pop(stored_key, None)
    _login_failures.setdefault(key, []).append(time.monotonic())


def clear_login_failures(key):
    _login_failures.pop(key, None)


def configure_admin_context(app):
    @app.context_processor
    def admin_template_context():
        return {
            "admin_user": current_admin(),
            "admin_usernames": tuple(ADMIN_ACCOUNTS),
            "csrf_token": csrf_token,
            "ROLE_ADMIN": ROLE_ADMIN,
            "ROLE_GUEST": ROLE_GUEST,
        }
