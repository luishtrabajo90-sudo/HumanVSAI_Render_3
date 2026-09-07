import random
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

from .extensions import db
from .image_explanations import build_feedback, detective_tip
from .game_catalog import get_game_catalog
from .models import GameImage, ImagePair, MissionResult, PlayerProfile, PlayerSeenImage, Settings

game_bp = Blueprint("game", __name__)

ROUNDS_PER_GAME = 5
BASE_POINTS_PER_ANSWER = 50
POINTS_PER_SECOND_REMAINING = 10
STREAK_BONUS_POINTS = 25
AI_FEST_QUESTIONS_PATH = Path(__file__).with_name("data") / "ai_fest_questions.json"


def load_ai_fest_questions(path=AI_FEST_QUESTIONS_PATH):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"No se pudieron cargar las preguntas AI Fest: {error}") from error
    questions = data.get("questions")
    if data.get("version") != 1 or not isinstance(questions, list) or len(questions) != 5:
        raise ValueError("AI Fest requiere exactamente cinco preguntas versión 1.")
    ids = set()
    for question in questions:
        required = {"id", "question", "options", "correct", "explanation"}
        if not required.issubset(question) or question["id"] in ids:
            raise ValueError("Hay una pregunta AI Fest incompleta o duplicada.")
        ids.add(question["id"])
        options = question["options"]
        if len(options) != 4 or not all({"id", "label"}.issubset(option) for option in options):
            raise ValueError(f"La pregunta {question['id']} debe tener cuatro opciones.")
        option_ids = [option["id"] for option in options]
        if len(set(option_ids)) != 4 or question["correct"] not in option_ids:
            raise ValueError(f"La pregunta {question['id']} no tiene una única respuesta válida.")
    return questions


def _rank_for(acc):
    if acc == 100:
        return "🏆 Detector Maestro", "¡Perfecto! Tienes un ojo entrenadísimo para la IA."
    if acc >= 80:
        return "🥇 Ojo Experto", "Excelente. Detectas casi todas las trampas."
    if acc >= 60:
        return "🥈 Buen Observador", "Bien encaminado. Repasa la guía y subirás de nivel."
    if acc >= 40:
        return "🥉 Aprendiz", "Vas aprendiendo. Fíjate en manos, ojos y texto."
    return "🔍 Sigue practicando", "La IA te engañó esta vez. Abre la guía y vuelve a intentarlo."


def _reset_state(deck_ids):
    session["deck"] = deck_ids
    session["i"] = 0
    session["score"] = 0
    session["streak"] = 0
    session["best"] = 0
    session["hits"] = 0
    session["misses"] = 0
    session["answered"] = False
    session["image_index"] = None
    session["detective_tips"] = []
    session["round_detective_tip"] = None
    session["round_started_at"] = None
    session["human_run_id"] = uuid.uuid4().hex
    session["human_started"] = time.time()
    session["human_result_recorded"] = False


def _current_pair():
    deck = session.get("deck") or []
    i = session.get("i", 0)
    if i >= len(deck):
        return None
    return db.session.get(ImagePair, deck[i])


def _current_challenge():
    deck = session.get("deck") or []
    index = session.get("i", 0)
    if index >= len(deck):
        return None
    challenge_id = deck[index]
    if isinstance(challenge_id, str) and challenge_id.startswith("image:"):
        return db.session.get(GameImage, int(challenge_id.split(":", 1)[1]))
    return db.session.get(ImagePair, challenge_id)


@game_bp.route("/")
def index():
    from .admin_auth import current_admin

    if request.args.get("modo") != "movil" and current_admin() is not None:
        return redirect(url_for("game.index", modo="movil"))
    return render_template(
        "index.html",
        game_catalog=get_game_catalog(),
        mobile_controller=request.args.get("modo") == "movil",
    )


@game_bp.route("/proyeccion")
def projection():
    return render_template("projection.html", projection_number=1)


@game_bp.route("/proyeccion<int:projection_number>")
def numbered_projection(projection_number):
    return render_template("projection.html", projection_number=projection_number)


@game_bp.route("/ranking")
def ranking():
    return render_template("ranking.html")


@game_bp.route("/api/settings")
def api_settings():
    return jsonify(Settings.get().to_dict())


@game_bp.route("/api/exhibition")
def api_exhibition():
    metadata_path = Path(current_app.static_folder) / "runtime" / "exhibition.json"
    if not metadata_path.exists():
        return jsonify({"active": False})
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        current_app.logger.error("No se pudo leer la información de exposición: %s", error)
        return jsonify({"error": "La información de exposición no es válida."}), 500
    public_url = metadata.get("public_url", "")
    parsed = urlparse(public_url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".trycloudflare.com"):
        current_app.logger.error("URL de exposición rechazada: %r", public_url)
        return jsonify({"error": "La URL pública de exposición no es válida."}), 500
    return jsonify({
        "active": True,
        "public_url": public_url,
        "qr_url": "/static/runtime/exhibition-qr.png",
    })


def _select_unseen_images(playable, player_id):
    pool = list(playable)
    if not player_id or not pool:
        random.shuffle(pool)
        return pool[:ROUNDS_PER_GAME]

    by_id = {image.id: image for image in pool}
    seen_rows = {
        row.image_id: row
        for row in PlayerSeenImage.query.filter_by(player_id=player_id).all()
        if row.image_id in by_id
    }
    least_recently_shown = sorted(seen_rows.values(), key=lambda row: row.seen_at or datetime.min)

    unseen = [image for image in pool if image.id not in seen_rows]
    random.shuffle(unseen)
    selected = unseen[:ROUNDS_PER_GAME]
    selected_ids = {image.id for image in selected}

    needed = ROUNDS_PER_GAME - len(selected)
    if needed > 0:
        for row in least_recently_shown:
            if needed <= 0:
                break
            if row.image_id in selected_ids:
                continue
            selected.append(by_id[row.image_id])
            selected_ids.add(row.image_id)
            needed -= 1

    now = datetime.now(timezone.utc)
    for image in selected:
        row = seen_rows.get(image.id)
        if row is not None:
            row.seen_at = now
        else:
            db.session.add(PlayerSeenImage(player_id=player_id, image_id=image.id, seen_at=now))
    return selected


@game_bp.route("/api/game/start", methods=["POST"])
def api_start():
    from .admin_auth import current_admin
    from .gamification import current_player_id

    images = GameImage.query.filter_by(active=True).all()
    playable = [image for image in images if image.is_playable]
    if not playable:
        return jsonify({"error": "No hay imágenes individuales listas para jugar."}), 400
    player_id = None if current_admin() is not None else current_player_id()
    selected = _select_unseen_images(playable, player_id)
    deck_ids = [f"image:{image.id}" for image in selected]
    db.session.commit()
    _reset_state(deck_ids)
    _publish_game_state()
    return jsonify({"total": len(deck_ids)})


def _round_image(challenge):
    if isinstance(challenge, GameImage):
        return {
            "id": str(challenge.id),
            "path": challenge.image_url,
            "class": challenge.image_class,
        }
    images = [
        {"id": "A", "path": challenge.ai_image_path, "class": challenge.image_classes[0]},
        {"id": "B", "path": challenge.real_image_path, "class": challenge.image_classes[1]},
    ]
    return images[session["image_index"]]


def _publish_game_state(image_url=None, reset_round_timer=False):
    from .visitor_session import current_visitor_session

    visitor = current_visitor_session()
    if visitor is not None:
        current_round = session.get("i", 0) + 1 if image_url else 0
        if reset_round_timer and (
            visitor.current_image_url != image_url
            or visitor.current_round != current_round
        ):
            visitor.round_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=Settings.get().timer_seconds
            )
        visitor.current_image_url = image_url
        visitor.current_score = session.get("score", 0)
        visitor.current_round = current_round
        visitor.current_total_rounds = len(session.get("deck") or [])
        visitor.current_hits = session.get("hits", 0)
        visitor.current_misses = session.get("misses", 0)
        db.session.commit()


def _public_image_url(image_path):
    return image_path if image_path.startswith(("https://", "http://")) else "/static/" + image_path


@game_bp.route("/api/game/round")
def api_round():
    challenge = _current_challenge()
    if challenge is None:
        return jsonify({"error": "No hay ronda activa."}), 400

    if not isinstance(challenge, GameImage) and session.get("image_index") is None:
        session["image_index"] = random.randrange(2)
        session["answered"] = False

    image = _round_image(challenge)
    if session.get("round_started_at") is None:
        session["round_started_at"] = time.time()
    _publish_game_state(_public_image_url(image["path"]), reset_round_timer=True)
    if session.get("round_detective_tip") is None:
        image_path = Path(current_app.static_folder) / image["path"]
        tip = detective_tip(
            challenge.id,
            image["id"],
            image_path,
            session.get("detective_tips", ()),
        )
        session["round_detective_tip"] = tip
        session["detective_tips"] = [*session.get("detective_tips", ()), tip]

    settings = Settings.get()
    deck = session["deck"]
    return jsonify({
        "category": challenge.category,
        "question": "¿Esta imagen es real o fue creada por IA?",
        "instruction": "Elige IA o REAL",
        "image": {"id": image["id"], "src": _public_image_url(image["path"])},
        "round": session["i"] + 1,
        "total": len(deck),
        "timer_seconds": settings.timer_seconds,
        "sound_effects_enabled": settings.sound_effects_enabled,
        "visual_effects_enabled": settings.visual_effects_enabled,
        "score": session["score"],
        "streak": session["streak"],
        "answered": session["answered"],
        "detective_tip": session["round_detective_tip"],
    })


def _resolve_answer(choice):
    challenge = _current_challenge()
    if challenge is None:
        return jsonify({"error": "No hay ronda activa."}), 400
    if session.get("answered"):
        return jsonify({"error": "Esta ronda ya fue respondida."}), 400

    image = _round_image(challenge)
    correct_choice = image["class"].lower()
    correct = choice is not None and choice == correct_choice
    gain = 0
    if correct:
        elapsed_seconds = max(
            0,
            time.time() - session.get("round_started_at", time.time()),
        )
        remaining_seconds = max(0, Settings.get().timer_seconds - elapsed_seconds)
        gain = (
            BASE_POINTS_PER_ANSWER
            + round(remaining_seconds) * POINTS_PER_SECOND_REMAINING
            + session["streak"] * STREAK_BONUS_POINTS
        )
        session["score"] += gain
        session["hits"] += 1
        session["streak"] += 1
        if session["streak"] > session["best"]:
            session["best"] = session["streak"]
    else:
        session["streak"] = 0
        session["misses"] = session.get("misses", 0) + 1

    session["answered"] = True
    session["round_started_at"] = None
    _publish_game_state(_public_image_url(image["path"]))
    is_last = (session["i"] + 1) >= len(session["deck"])
    feedback = build_feedback(
        challenge,
        image["id"],
        image["class"],
        Path(current_app.static_folder) / image["path"],
        session.get("detective_tips", ()),
    )
    if feedback["next_tip"] not in session.get("detective_tips", ()):
        session["detective_tips"] = [
            *session.get("detective_tips", ()),
            feedback["next_tip"],
        ]
    return jsonify({
        "correct": correct,
        "gain": gain,
        "correct_choice": correct_choice,
        "image": {
            "id": image["id"],
            "src": _public_image_url(image["path"]),
            "isAI": image["class"] == "IA",
        },
        **feedback,
        "score": session["score"],
        "streak": session["streak"],
        "is_last": is_last,
    })


@game_bp.route("/api/game/answer", methods=["POST"])
def api_answer():
    data = request.get_json(silent=True) or {}
    choice = data.get("choice")
    if choice not in ("ia", "real"):
        return jsonify({"error": "choice debe ser ia o real"}), 400
    return _resolve_answer(choice)


@game_bp.route("/api/game/timeout", methods=["POST"])
def api_timeout():
    return _resolve_answer(None)


@game_bp.route("/api/game/next", methods=["POST"])
def api_next():
    deck = session.get("deck") or []
    if session.get("i", 0) + 1 >= len(deck):
        session["i"] = len(deck)
        return jsonify({"finished": True})
    session["i"] += 1
    session["answered"] = False
    session["image_index"] = None
    session["round_detective_tip"] = None
    session["round_started_at"] = None
    return jsonify({"finished": False})


@game_bp.route("/api/game/result")
def api_result():
    from .gamification import current_profile_dict, record_result
    deck = session.get("deck") or []
    total = len(deck)
    hits = session.get("hits", 0)
    acc = round((hits / total) * 100) if total else 0
    rank, msg = _rank_for(acc)
    run_token = session.get("human_run_id")
    if not run_token or not total or session.get("i", 0) < total:
        return jsonify({"error": "La partida todavia no ha terminado."}), 409
    result, saved = record_result(
        run_token,
        "human-vs-ai",
        "",
        session.get("score", 0),
        int(max(0, time.time() - session.get("human_started", time.time()))),
        True,
    )
    if result is None:
        return jsonify({
            "score": session.get("score", 0),
            "accuracy": acc,
            "hits": hits,
            "total": total,
            "best_streak": session.get("best", 0),
            "rank": "Práctica administrativa",
            "message": "Resultado de prueba no incluido en el ranking.",
            "result_status": "practice",
            "profile": current_profile_dict(),
        })
    session["human_result_recorded"] = True
    return jsonify({
        "score": result.score,
        "accuracy": acc,
        "hits": hits,
        "total": total,
        "best_streak": session.get("best", 0),
        "rank": rank,
        "message": msg,
        "result_status": "saved" if saved else "already_saved",
        "profile": current_profile_dict(),
    })


@game_bp.route("/api/game/result/discard", methods=["POST"])
def api_discard_result():
    run_token = session.get("human_run_id")
    player_id = session.get("player_id")
    result = MissionResult.query.filter_by(run_token=run_token).first() if run_token else None
    player = db.session.get(PlayerProfile, player_id) if player_id else None
    if result is not None and player is not None and result.player_id == player.id:
        player.total_seconds = max(0, player.total_seconds - result.duration_seconds)
        player.mission_count = max(0, player.mission_count - 1)
        db.session.delete(result)
        db.session.flush()
        player.total_points = max(
            [item.score for item in MissionResult.query.filter_by(player_id=player.id).all()] or [0]
        )
        db.session.commit()
    return jsonify({"discarded": result is not None})
