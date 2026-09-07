import uuid
import math
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, redirect, request, session, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .admin_auth import (
    ADMIN_ACCOUNTS,
    ADMIN_PROFILE_NAMES,
    audit,
    authenticate_admin,
    clear_session_preserving_csrf,
    clear_login_failures,
    login_is_limited,
    login_rate_key,
    record_login_failure,
    start_admin_session,
    start_password_change_session,
    csrf_token,
    current_admin,
    validate_csrf,
)
from .gamification import level_for
from .models import PlayerProfile, VisitorSession


visitor_session_bp = Blueprint("visitor_session", __name__)
SESSION_DURATION_SECONDS = 10 * 60
GUEST_RETENTION_HOURS = 24
VISITOR_HISTORY_ADMINS = frozenset({
    "cmoron",
    "hpinto",
    "lhernandez",
    "emartinez",
})
GUEST_USERNAME_PATTERN = re.compile(
    r"^(?=.{1,30}$)[A-Za-z0-9]+(?: +[A-Za-z0-9]+)*$"
)


def _utcnow():
    return datetime.now(timezone.utc)


def _as_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _valid_name(name):
    return bool(GUEST_USERNAME_PATTERN.fullmatch(name))


def _normalize_name(name):
    return name.strip().casefold()


def _live_elapsed(visitor, now):
    if visitor.ended_at is not None:
        return 0.0
    started_at = _as_utc(visitor.started_at)
    expires_at = _as_utc(visitor.expires_at)
    return max(0.0, (min(now, expires_at) - started_at).total_seconds())


def _remaining_seconds(visitor, now):
    consumed = float(visitor.consumed_seconds or 0.0)
    if visitor.ended_at is None and _as_utc(visitor.expires_at) <= now:
        return 0.0
    return max(
        0.0,
        SESSION_DURATION_SECONDS - consumed - _live_elapsed(visitor, now),
    )


def _settle_visitor(visitor, now, reason):
    visitor.consumed_seconds = (
        float(SESSION_DURATION_SECONDS)
        if reason == "expired"
        else min(
            float(SESSION_DURATION_SECONDS),
            float(visitor.consumed_seconds or 0.0) + _live_elapsed(visitor, now),
        )
    )
    visitor.ended_at = now
    visitor.end_reason = reason
    visitor.session_token = None
    visitor.current_image_path = None
    visitor.current_image_url = None
    visitor.current_score = 0
    visitor.current_round = 0
    visitor.current_total_rounds = 0
    visitor.current_hits = 0
    visitor.current_misses = 0
    visitor.round_expires_at = None


def purge_expired_guests(now=None):
    from .models import MissionResult, PlayerSeenImage
    from .profile_photo import delete_profile_photo

    now = now or _utcnow()
    expired = PlayerProfile.query.filter(
        PlayerProfile.expires_at.is_not(None),
        PlayerProfile.expires_at <= now,
        ~PlayerProfile.id.like("admin-%"),
    ).all()
    purged = 0
    photos = []
    for player in expired:
        if _normalize_name(player.name) in ADMIN_ACCOUNTS:
            continue
        VisitorSession.query.filter_by(player_id=player.id).delete(synchronize_session=False)
        MissionResult.query.filter_by(player_id=player.id).delete(synchronize_session=False)
        PlayerSeenImage.query.filter_by(player_id=player.id).delete(synchronize_session=False)
        if player.photo_filename:
            photos.append(player.photo_filename)
        db.session.delete(player)
        purged += 1
    if purged:
        db.session.commit()
        for filename in photos:
            delete_profile_photo(filename)
    return purged


def maybe_purge_expired_guests():
    now = time.monotonic()
    last_run = current_app.extensions.get("guest_cleanup_last_run", 0)
    if now - last_run >= 60:
        purge_expired_guests()
        current_app.extensions["guest_cleanup_last_run"] = now


def _session_payload(visitor, now=None):
    now = now or _utcnow()
    expires_at = _as_utc(visitor.expires_at)
    remaining = _remaining_seconds(visitor, now)
    active = visitor.ended_at is None and remaining > 0
    active_visitors = (
        VisitorSession.query
        .filter(VisitorSession.ended_at.is_(None), VisitorSession.expires_at > now)
        .order_by(VisitorSession.started_at.asc())
        .all()
    )
    player_number = next(
        (index + 1 for index, item in enumerate(active_visitors) if item.id == visitor.id),
        None,
    )
    return {
        "active": active,
        "name": visitor.player.name,
        "started_at": _as_utc(visitor.started_at).isoformat(),
        "expires_at": expires_at.isoformat(),
        "seconds_remaining": max(0, math.ceil(remaining)),
        "player_number": player_number,
    }


def _admin_session_payload(admin):
    return {
        "active": True,
        "admin": True,
        "unlimited_time": True,
        "can_clear_visitor_history": admin.username in VISITOR_HISTORY_ADMINS,
        "role": "ADMIN",
        "name": admin.full_name,
        "player_number": None,
    }


def current_visitor_session():
    visitor_id = session.get("visitor_session_id")
    if not visitor_id:
        return None
    visitor = db.session.get(VisitorSession, visitor_id)
    if visitor is None:
        clear_session_preserving_csrf()
        return None
    if not visitor.session_token or not secrets.compare_digest(
        visitor.session_token,
        str(session.get("visitor_session_token", "")),
    ):
        clear_session_preserving_csrf()
        return None
    now = _utcnow()
    if visitor.ended_at is not None:
        clear_session_preserving_csrf()
        return None
    if _remaining_seconds(visitor, now) <= 0:
        _settle_visitor(visitor, now, "expired")
        db.session.commit()
        clear_session_preserving_csrf()
        return None
    if visitor.player.expires_at and _as_utc(visitor.player.expires_at) <= now:
        purge_expired_guests(now)
        clear_session_preserving_csrf()
        return None
    if (
        visitor.player.last_activity_at is None
        or now - _as_utc(visitor.player.last_activity_at) >= timedelta(minutes=1)
    ):
        visitor.player.last_activity_at = now
        db.session.commit()
    return visitor


def enforce_visitor_session():
    if current_app.testing and not current_app.config.get(
        "ENFORCE_VISITOR_SESSION_IN_TESTS", False
    ):
        return None

    path = request.path
    protected = (
        path == "/api/profile"
        or path.startswith("/api/game/")
        or path.startswith("/api/progress/")
        or (
            path.startswith("/api/games/")
            and not path.endswith("/config")
        )
    )
    if protected and current_admin() is None and current_visitor_session() is None:
        return jsonify({
            "error": "La sesión de visitante ha expirado después de 10 minutos.",
            "session_expired": True,
        }), 401
    return None


@visitor_session_bp.get("/api/visitor-session")
def api_visitor_session():
    admin = current_admin()
    if admin is not None:
        return jsonify(_admin_session_payload(admin))
    visitor = current_visitor_session()
    if visitor is None:
        return jsonify({"active": False, "seconds_remaining": 0})
    return jsonify(_session_payload(visitor))


@visitor_session_bp.post("/api/visitor-session")
def api_start_visitor_session():
    data = request.get_json(silent=True) if request.is_json else request.form
    data = data or {}
    name = str(data.get("name", "")).strip()
    admin_username = _normalize_name(name)
    if admin_username in ADMIN_ACCOUNTS:
        validate_csrf()
        key = login_rate_key(admin_username)
        if login_is_limited(key):
            return jsonify({
                "error": "No se pudo iniciar sesión. Espera un minuto e inténtalo de nuevo."
            }), 429
        admin = authenticate_admin(admin_username, str(data.get("password", "")))
        if admin is None:
            record_login_failure(key)
            return jsonify({"error": "Usuario o contraseña incorrectos."}), 401
        clear_login_failures(key)
        current = current_visitor_session()
        if current is not None:
            _settle_visitor(current, _utcnow(), "replaced")
        if admin.password_change_required:
            start_password_change_session(admin)
            db.session.commit()
            if not request.is_json:
                return redirect(url_for("admin.first_login"))
            return jsonify({
                "active": False,
                "admin": True,
                "role": "ADMIN",
                "password_change_required": True,
                "redirect_url": url_for("admin.first_login"),
                "csrf_token": csrf_token(),
            })
        start_admin_session(admin)
        audit("login", "admin", admin.id)
        db.session.commit()
        if not request.is_json:
            return redirect(url_for("admin.pairs_list"))
        payload = _admin_session_payload(admin)
        payload["csrf_token"] = csrf_token()
        return jsonify(payload)

    if not _valid_name(name):
        return jsonify({
            "error": "Usa entre 1 y 30 letras o números; se permiten espacios entre palabras."
        }), 400

    now = _utcnow()
    current = current_visitor_session()
    if current is not None:
        _settle_visitor(current, now, "replaced")

    visitor = VisitorSession.query.filter_by(normalized_name=name).first()
    player = visitor.player if visitor else next(
        (profile for profile in PlayerProfile.query.all() if profile.name == name),
        None,
    )
    if visitor is not None and visitor.ended_at is None:
        _settle_visitor(visitor, now, "replaced")
    remaining = (
        SESSION_DURATION_SECONDS - float(visitor.consumed_seconds or 0.0)
        if visitor
        else float(SESSION_DURATION_SECONDS)
    )
    if remaining <= 0:
        db.session.commit()
        return jsonify({
            "error": "Este visitante ya utilizó sus 10 minutos disponibles.",
            "session_expired": True,
        }), 403

    player_id = player.id if player else str(uuid.uuid4())
    token = secrets.token_hex(16)
    if visitor is None:
        visitor = VisitorSession(
            id=str(uuid.uuid4()),
            normalized_name=name,
            player_id=player_id,
            consumed_seconds=0.0,
        )
    visitor.started_at = now
    visitor.expires_at = now + timedelta(seconds=remaining)
    visitor.ended_at = None
    visitor.end_reason = None
    visitor.session_token = token
    if player is None:
        db.session.add(PlayerProfile(
            id=player_id,
            name=name,
            last_activity_at=now,
            expires_at=now + timedelta(hours=GUEST_RETENTION_HOURS),
        ))
    else:
        player.last_activity_at = now
        player.expires_at = now + timedelta(hours=GUEST_RETENTION_HOURS)
    db.session.add(visitor)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "No se pudo reanudar la sesión del visitante."}), 409

    clear_session_preserving_csrf()
    session.permanent = True
    session["player_id"] = player_id
    session["visitor_session_id"] = visitor.id
    session["visitor_session_token"] = token
    return jsonify(_session_payload(visitor, now)), 201


@visitor_session_bp.post("/api/visitor-session/end")
def api_end_visitor_session():
    admin = current_admin()
    if admin is not None:
        validate_csrf()
        audit("logout", "admin", admin.id)
        db.session.commit()
        clear_session_preserving_csrf()
        return jsonify({"active": False, "ended": True})
    visitor_id = session.get("visitor_session_id")
    visitor = db.session.get(VisitorSession, visitor_id) if visitor_id else None
    if visitor is not None and visitor.ended_at is None:
        now = _utcnow()
        reason = "expired" if _remaining_seconds(visitor, now) <= 0 else "manual"
        _settle_visitor(visitor, now, reason)
        db.session.commit()
    clear_session_preserving_csrf()
    return jsonify({"active": False, "ended": visitor is not None})


@visitor_session_bp.get("/api/visitor-ranking")
def api_visitor_ranking():
    now = _utcnow()
    admin_names = tuple(ADMIN_PROFILE_NAMES)
    active_count = VisitorSession.query.join(
        PlayerProfile, VisitorSession.player_id == PlayerProfile.id
    ).filter(
        VisitorSession.ended_at.is_(None),
        VisitorSession.expires_at > now,
        ~VisitorSession.player_id.like("admin-%"),
        ~func.lower(func.trim(PlayerProfile.name)).in_(admin_names),
    ).count()
    visitors = (
        VisitorSession.query
        .join(PlayerProfile, VisitorSession.player_id == PlayerProfile.id)
        .filter(
            ~VisitorSession.player_id.like("admin-%"),
            ~func.lower(func.trim(PlayerProfile.name)).in_(admin_names),
        )
        .order_by(
            PlayerProfile.total_points.desc(),
            PlayerProfile.total_seconds.asc(),
            VisitorSession.started_at.asc(),
        )
        .limit(50)
        .all()
    )
    return jsonify({
        "active_count": active_count,
        "ranking": [
            {
                "position": index + 1,
                "name": visitor.player.name,
                "points": visitor.player.total_points,
                "level": level_for(visitor.player.total_points),
                "missions": visitor.player.mission_count,
                "photo_url": (
                    url_for(
                        "profile_photo.get_photo",
                        player_id=visitor.player.id,
                        v=visitor.player.photo_version,
                    )
                    if visitor.player.photo_filename
                    else None
                ),
                "active": (
                    visitor.ended_at is None
                    and _as_utc(visitor.expires_at) > now
                ),
            }
            for index, visitor in enumerate(visitors)
        ]
    })


@visitor_session_bp.get("/api/online-players")
def api_online_players():
    now = _utcnow()
    projection_number = request.args.get("projection", 1, type=int)
    if projection_number is None or projection_number < 1:
        return jsonify({"error": "La pantalla de proyección debe ser mayor que cero."}), 400
    visitors = (
        VisitorSession.query
        .join(PlayerProfile, VisitorSession.player_id == PlayerProfile.id)
        .filter(
            VisitorSession.ended_at.is_(None),
            VisitorSession.expires_at > now,
            ~VisitorSession.player_id.like("admin-%"),
            ~func.lower(func.trim(PlayerProfile.name)).in_(tuple(ADMIN_PROFILE_NAMES)),
        )
        .order_by(VisitorSession.started_at.asc())
        .offset((projection_number - 1) * 4)
        .limit(4)
        .all()
    )
    return jsonify({
        "projection": projection_number,
        "players": [
            {
                "name": visitor.player.name,
                "image_url": visitor.current_image_url,
                "points": visitor.current_score,
                "round": visitor.current_round,
                "total_rounds": visitor.current_total_rounds,
                "round_seconds_remaining": max(
                    0,
                    math.ceil((_as_utc(visitor.round_expires_at) - now).total_seconds()),
                ) if visitor.round_expires_at else 0,
                "hits": visitor.current_hits,
                "misses": visitor.current_misses,
            }
            for visitor in visitors
        ]
    })


@visitor_session_bp.post("/api/visitor-ranking/clear")
def api_clear_visitor_ranking():
    from .models import MissionResult
    from .profile_photo import delete_profile_photo

    admin = current_admin()
    if admin is None:
        return jsonify({"error": "Se requiere una sesión administrativa."}), 401
    if admin.username not in VISITOR_HISTORY_ADMINS:
        return jsonify({"error": "No tienes permiso para borrar este historial."}), 403
    validate_csrf()

    visitor_player_ids = [
        player_id
        for (player_id,) in (
            db.session.query(VisitorSession.player_id)
            .distinct()
            .all()
        )
        if player_id and not player_id.startswith("admin-")
    ]
    players = (
        PlayerProfile.query
        .filter(PlayerProfile.id.in_(visitor_player_ids))
        .all()
        if visitor_player_ids
        else []
    )
    removable_players = players
    removable_ids = [player.id for player in removable_players]
    photo_filenames = [
        player.photo_filename for player in removable_players if player.photo_filename
    ]

    deleted_results = 0
    if removable_ids:
        deleted_results = MissionResult.query.filter(
            MissionResult.player_id.in_(removable_ids)
        ).delete(synchronize_session=False)
        from .models import PlayerSeenImage
        PlayerSeenImage.query.filter(
            PlayerSeenImage.player_id.in_(removable_ids)
        ).delete(synchronize_session=False)
        VisitorSession.query.filter(
            VisitorSession.player_id.in_(removable_ids)
        ).delete(synchronize_session=False)
        PlayerProfile.query.filter(
            PlayerProfile.id.in_(removable_ids)
        ).delete(synchronize_session=False)

    audit("clear", "visitor_ranking", str(len(removable_ids)))
    db.session.commit()
    for filename in photo_filenames:
        delete_profile_photo(filename)

    return jsonify({
        "cleared": True,
        "deleted_visitors": len(removable_ids),
        "deleted_results": deleted_results,
    })
