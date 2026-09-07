import uuid

from flask import Blueprint, jsonify, request, session, url_for
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .admin_auth import ADMIN_PROFILE_NAMES, current_admin
from .models import MissionResult, PlayerProfile, VisitorSession


gamification_bp = Blueprint("gamification", __name__)
LEVELS = (
    (0, "Visitante"),
    (300, "Explorador Digital"),
    (900, "Analista"),
    (1800, "Especialista"),
    (3200, "Champion IA"),
)


def current_player_id():
    player_id = session.get("player_id")
    if not player_id:
        player_id = str(uuid.uuid4())
        session["player_id"] = player_id
    return player_id


def get_profile():
    if current_admin() is not None:
        raise RuntimeError("Las cuentas administrativas no tienen perfil de jugador.")
    player_id = current_player_id()
    profile = db.session.get(PlayerProfile, player_id)
    if profile is None:
        admin = current_admin()
        profile = PlayerProfile(
            id=player_id,
            name=admin.full_name if admin is not None else "Visitante",
        )
        db.session.add(profile)
        db.session.commit()
    return profile


def admin_profile_dict(admin):
    return {
        "id": None,
        "name": admin.full_name,
        "points": 0,
        "level": "Administrador",
        "missions": 0,
        "total_seconds": 0,
        "achievements": [],
        "history": [],
        "mission_streak": 0,
        "photo_url": None,
        "level_number": 0,
        "level_progress": 0,
        "level_floor": 0,
        "next_level_points": 0,
        "points_to_next_level": 0,
        "admin": True,
    }


def current_profile_dict():
    admin = current_admin()
    if admin is not None:
        return admin_profile_dict(admin)
    return profile_dict(get_profile())


def purge_admin_game_data():
    normalized_admins = tuple(ADMIN_PROFILE_NAMES)
    profiles = PlayerProfile.query.filter(or_(
        PlayerProfile.id.like("admin-%"),
        func.lower(func.trim(PlayerProfile.name)).in_(normalized_admins),
    )).all()
    if not profiles:
        return []
    player_ids = [profile.id for profile in profiles]
    photo_filenames = [
        profile.photo_filename for profile in profiles if profile.photo_filename
    ]
    VisitorSession.query.filter(
        VisitorSession.player_id.in_(player_ids)
    ).delete(synchronize_session=False)
    MissionResult.query.filter(
        MissionResult.player_id.in_(player_ids)
    ).delete(synchronize_session=False)
    PlayerProfile.query.filter(
        PlayerProfile.id.in_(player_ids)
    ).delete(synchronize_session=False)
    db.session.commit()
    return photo_filenames


def level_for(points):
    return next(name for threshold, name in reversed(LEVELS) if points >= threshold)


def level_progress_for(points):
    current_index = max(
        index for index, (threshold, _) in enumerate(LEVELS) if points >= threshold
    )
    current_threshold = LEVELS[current_index][0]
    if current_index == len(LEVELS) - 1:
        return {
            "level_number": current_index + 1,
            "level_progress": 100,
            "level_floor": current_threshold,
            "next_level_points": current_threshold,
            "points_to_next_level": 0,
        }
    next_threshold = LEVELS[current_index + 1][0]
    progress = round(
        (points - current_threshold) / (next_threshold - current_threshold) * 100
    )
    return {
        "level_number": current_index + 1,
        "level_progress": max(0, min(100, progress)),
        "level_floor": current_threshold,
        "next_level_points": next_threshold,
        "points_to_next_level": max(0, next_threshold - points),
    }


def achievements_for(player_id):
    results = MissionResult.query.filter_by(player_id=player_id, completed=True).all()
    games = {result.game_id for result in results}
    unlocked = []
    if results:
        unlocked.append("Primer Desafío")
    if "human-vs-ai" in games:
        unlocked.append("Detector de IA")
    return unlocked


def profile_dict(profile, include_history=True):
    data = {
        "id": profile.id,
        "name": profile.name,
        "points": profile.total_points,
        "level": level_for(profile.total_points),
        "missions": profile.mission_count,
        "total_seconds": profile.total_seconds,
        "achievements": achievements_for(profile.id),
        "photo_url": (
            url_for(
                "profile_photo.get_photo",
                player_id=profile.id,
                v=profile.photo_version,
            )
            if profile.photo_filename
            else None
        ),
    }
    data.update(level_progress_for(profile.total_points))
    if include_history:
        history = (
            MissionResult.query.filter_by(player_id=profile.id)
            .order_by(MissionResult.created_at.desc())
            .limit(20)
            .all()
        )
        streak = 0
        for item in history:
            if not item.completed:
                break
            streak += 1
        data["mission_streak"] = streak
        data["history"] = [
            {
                "game_id": item.game_id,
                "mission_id": item.mission_id,
                "score": item.score,
                "seconds": item.duration_seconds,
                "completed": item.completed,
                "created_at": item.created_at.isoformat(),
            }
            for item in history
        ]
    return data


def record_result(run_token, game_id, mission_id, score, duration_seconds, completed):
    if current_admin() is not None:
        return None, False
    existing = MissionResult.query.filter_by(run_token=run_token).first()
    if existing:
        return existing, False
    profile = get_profile()
    result = MissionResult(
        player_id=profile.id,
        run_token=run_token,
        game_id=game_id,
        mission_id=mission_id or "",
        score=max(0, int(score)),
        duration_seconds=max(0, int(duration_seconds)),
        completed=bool(completed),
    )
    profile.total_points = max(profile.total_points, result.score)
    profile.total_seconds += result.duration_seconds
    profile.mission_count += 1
    db.session.add(result)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return MissionResult.query.filter_by(run_token=run_token).one(), False
    return result, True


@gamification_bp.get("/api/profile")
def api_profile():
    return jsonify(current_profile_dict())


@gamification_bp.patch("/api/profile")
def api_update_profile():
    if current_admin() is not None:
        return jsonify({"error": "Las cuentas administrativas no tienen perfil de jugador."}), 403
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not 1 <= len(name) <= 30 or any(ord(char) < 32 for char in name):
        return jsonify({"error": "El nombre debe contener entre 1 y 30 caracteres."}), 400
    profile = get_profile()
    if VisitorSession.query.filter_by(player_id=profile.id).first():
        return jsonify({
            "error": "El nombre del visitante queda fijado al iniciar la sesión."
        }), 400
    profile.name = name
    db.session.commit()
    return jsonify(profile_dict(profile))


@gamification_bp.get("/api/ranking")
def api_ranking():
    profiles = (
        PlayerProfile.query.filter(
            PlayerProfile.mission_count > 0,
            ~PlayerProfile.id.like("admin-%"),
            ~func.lower(func.trim(PlayerProfile.name)).in_(tuple(ADMIN_PROFILE_NAMES)),
        )
        .order_by(PlayerProfile.total_points.desc(), PlayerProfile.total_seconds.asc())
        .limit(20)
        .all()
    )
    return jsonify({
        "ranking": [
            {
                "position": index + 1,
                "name": profile.name,
                "points": profile.total_points,
                "level": level_for(profile.total_points),
                "missions": profile.mission_count,
                "photo_url": (
                    url_for(
                        "profile_photo.get_photo",
                        player_id=profile.id,
                        v=profile.photo_version,
                    )
                    if profile.photo_filename
                    else None
                ),
            }
            for index, profile in enumerate(profiles)
        ]
    })

