from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect, text

from .extensions import db

IMAGE_CLASSES = ("IA", "REAL")


class ImagePair(db.Model):
    __tablename__ = "image_pairs"

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(120), nullable=False, default="")
    ai_image_path = db.Column(db.String(255), nullable=True)
    real_image_path = db.Column(db.String(255), nullable=True)
    ai_image_class = db.Column(db.String(8), nullable=False, default="IA")
    real_image_class = db.Column(db.String(8), nullable=False, default="REAL")
    tell = db.Column(db.Text, nullable=False, default="")
    realtip = db.Column(db.Text, nullable=False, default="")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def is_playable(self):
        return bool(self.ai_image_path and self.real_image_path and self.active)

    @property
    def image_classes(self):
        return (
            self.ai_image_class if self.ai_image_class in IMAGE_CLASSES else "IA",
            self.real_image_class if self.real_image_class in IMAGE_CLASSES else "REAL",
        )

    def to_dict(self):
        return {
            "id": self.id,
            "category": self.category,
            "ai_image_path": self.ai_image_path,
            "real_image_path": self.real_image_path,
            "ai_image_class": self.image_classes[0],
            "real_image_class": self.image_classes[1],
            "tell": self.tell,
            "realtip": self.realtip,
            "active": self.active,
        }


class GameImage(db.Model):
    __tablename__ = "game_images"

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(120), nullable=False, default="")
    image_url = db.Column(db.String(1000), nullable=False)
    image_class = db.Column(db.String(8), nullable=False)
    source_name = db.Column(db.String(255), nullable=False, default="")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def is_playable(self):
        return self.active and self.image_class in IMAGE_CLASSES and bool(self.image_url)


class Settings(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    timer_seconds = db.Column(db.Integer, nullable=False, default=15)
    sound_effects_enabled = db.Column(db.Boolean, nullable=False, default=True)
    visual_effects_enabled = db.Column(db.Boolean, nullable=False, default=True)

    @classmethod
    def get(cls):
        row = cls.query.first()
        if row is None:
            row = cls(timer_seconds=15, sound_effects_enabled=True, visual_effects_enabled=True)
            db.session.add(row)
            db.session.commit()
        return row

    def to_dict(self):
        return {
            "timer_seconds": self.timer_seconds,
            "sound_effects_enabled": self.sound_effects_enabled,
            "visual_effects_enabled": self.visual_effects_enabled,
        }


class PlayerProfile(db.Model):
    __tablename__ = "player_profiles"

    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(40), nullable=False, default="Visitante")
    total_points = db.Column(db.Integer, nullable=False, default=0)
    total_seconds = db.Column(db.Integer, nullable=False, default=0)
    mission_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_activity_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    photo_filename = db.Column(db.String(80), nullable=True)
    photo_version = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class PlayerSeenImage(db.Model):
    """Tracks which GameImage rows a player has already been shown, so future
    rounds avoid repeating them until the whole pool has been exhausted."""

    __tablename__ = "player_seen_images"

    player_id = db.Column(db.String(36), db.ForeignKey("player_profiles.id"), primary_key=True)
    image_id = db.Column(db.Integer, db.ForeignKey("game_images.id"), primary_key=True)
    seen_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class VisitorSession(db.Model):
    __tablename__ = "visitor_sessions"

    id = db.Column(db.String(36), primary_key=True)
    normalized_name = db.Column(db.String(80), nullable=False, unique=True)
    player_id = db.Column(
        db.String(36),
        db.ForeignKey("player_profiles.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    started_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    ended_at = db.Column(db.DateTime(timezone=True), nullable=True)
    end_reason = db.Column(db.String(20), nullable=True)
    consumed_seconds = db.Column(db.Float, nullable=False, default=0.0)
    session_token = db.Column(db.String(32), nullable=True)
    current_image_path = db.Column(db.String(255), nullable=True)
    current_image_url = db.Column(db.String(1000), nullable=True)
    current_score = db.Column(db.Integer, nullable=False, default=0)
    current_round = db.Column(db.Integer, nullable=False, default=0)
    current_total_rounds = db.Column(db.Integer, nullable=False, default=0)
    current_hits = db.Column(db.Integer, nullable=False, default=0)
    current_misses = db.Column(db.Integer, nullable=False, default=0)
    round_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)

    player = db.relationship("PlayerProfile", lazy="joined")


class MissionResult(db.Model):
    __tablename__ = "mission_results"

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.String(36), db.ForeignKey("player_profiles.id"), nullable=False, index=True)
    run_token = db.Column(db.String(64), nullable=False, unique=True)
    game_id = db.Column(db.String(40), nullable=False, index=True)
    mission_id = db.Column(db.String(60), nullable=False, default="")
    score = db.Column(db.Integer, nullable=False, default=0)
    duration_seconds = db.Column(db.Integer, nullable=False, default=0)
    completed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class AdminUser(db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), nullable=False, unique=True, index=True)
    full_name = db.Column(db.String(80), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="ADMIN")
    password_hash = db.Column(db.String(255), nullable=False)
    password_change_required = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AdminAudit(db.Model):
    __tablename__ = "admin_audit"

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("admin_users.id"), nullable=False, index=True)
    action = db.Column(db.String(60), nullable=False)
    entity_type = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.String(64), nullable=False, default="")
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    admin = db.relationship("AdminUser", lazy="joined")


def ensure_schema():
    """Add columns introduced after the initial database release."""
    columns = {column["name"] for column in inspect(db.engine).get_columns(ImagePair.__tablename__)}
    additions = {
        "ai_image_class": "VARCHAR(8) NOT NULL DEFAULT 'IA'",
        "real_image_class": "VARCHAR(8) NOT NULL DEFAULT 'REAL'",
    }
    for name, definition in additions.items():
        if name not in columns:
            db.session.execute(text(f"ALTER TABLE {ImagePair.__tablename__} ADD COLUMN {name} {definition}"))

    player_columns = {
        column["name"]
        for column in inspect(db.engine).get_columns(PlayerProfile.__tablename__)
    }
    if "last_activity_at" not in player_columns:
        db.session.execute(
            text(f"ALTER TABLE {PlayerProfile.__tablename__} ADD COLUMN last_activity_at DATETIME")
        )
    if "expires_at" not in player_columns:
        db.session.execute(
            text(f"ALTER TABLE {PlayerProfile.__tablename__} ADD COLUMN expires_at DATETIME")
        )
    if "photo_filename" not in player_columns:
        db.session.execute(
            text(f"ALTER TABLE {PlayerProfile.__tablename__} ADD COLUMN photo_filename VARCHAR(80)")
        )
    if "photo_version" not in player_columns:
        db.session.execute(
            text(
                f"ALTER TABLE {PlayerProfile.__tablename__} "
                "ADD COLUMN photo_version INTEGER NOT NULL DEFAULT 0"
            )
        )
    db.session.commit()
    for player in PlayerProfile.query.all():
        if player.last_activity_at is None:
            player.last_activity_at = player.updated_at or player.created_at
        if player.expires_at is None and not player.id.startswith("admin-"):
            created = player.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            player.expires_at = created + timedelta(hours=24)

    visitor_columns = {
        column["name"]
        for column in inspect(db.engine).get_columns(VisitorSession.__tablename__)
    }
    normalized_name_added = "normalized_name" not in visitor_columns
    if normalized_name_added:
        db.session.execute(
            text(
                f"ALTER TABLE {VisitorSession.__tablename__} "
                "ADD COLUMN normalized_name VARCHAR(80)"
            )
        )
    if "consumed_seconds" not in visitor_columns:
        db.session.execute(
            text(
                f"ALTER TABLE {VisitorSession.__tablename__} "
                "ADD COLUMN consumed_seconds FLOAT NOT NULL DEFAULT 0"
            )
        )
    if "session_token" not in visitor_columns:
        db.session.execute(
            text(
                f"ALTER TABLE {VisitorSession.__tablename__} "
                "ADD COLUMN session_token VARCHAR(32)"
            )
        )
    if "current_image_path" not in visitor_columns:
        db.session.execute(
            text(
                f"ALTER TABLE {VisitorSession.__tablename__} "
                "ADD COLUMN current_image_path VARCHAR(255)"
            )
        )
    if "current_image_url" not in visitor_columns:
        db.session.execute(
            text(
                f"ALTER TABLE {VisitorSession.__tablename__} "
                "ADD COLUMN current_image_url VARCHAR(1000)"
            )
        )
    visitor_additions = {
        "current_score": "INTEGER NOT NULL DEFAULT 0",
        "current_round": "INTEGER NOT NULL DEFAULT 0",
        "current_total_rounds": "INTEGER NOT NULL DEFAULT 0",
        "current_hits": "INTEGER NOT NULL DEFAULT 0",
        "current_misses": "INTEGER NOT NULL DEFAULT 0",
        "round_expires_at": "DATETIME",
    }
    for name, definition in visitor_additions.items():
        if name not in visitor_columns:
            db.session.execute(
                text(
                    f"ALTER TABLE {VisitorSession.__tablename__} "
                    f"ADD COLUMN {name} {definition}"
                )
            )
    db.session.commit()
    if normalized_name_added:
        used_names = set()
        for visitor in VisitorSession.query.order_by(VisitorSession.started_at).all():
            normalized = (
                " ".join(visitor.player.name.split()).casefold()
                if visitor.player is not None
                else f"orphan#{visitor.id}"
            )
            unique_value = normalized
            if unique_value in used_names:
                unique_value = f"{normalized}#{visitor.id}"
            visitor.normalized_name = unique_value
            used_names.add(unique_value)
        db.session.commit()
    for visitor in VisitorSession.query.all():
        started = visitor.started_at
        ended = visitor.ended_at
        if started is None:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if ended is not None:
            if ended.tzinfo is None:
                ended = ended.replace(tzinfo=timezone.utc)
            visitor.consumed_seconds = max(
                float(visitor.consumed_seconds or 0.0),
                min(600.0, max(0.0, (ended - started).total_seconds())),
            )
        elif visitor.expires_at is not None:
            expires = visitor.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= datetime.now(timezone.utc):
                visitor.consumed_seconds = 600.0
    db.session.commit()
    db.session.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_visitor_sessions_normalized_name "
            f"ON {VisitorSession.__tablename__} (normalized_name)"
        )
    )
    db.session.commit()

    admin_columns = {
        column["name"]
        for column in inspect(db.engine).get_columns(AdminUser.__tablename__)
    }
    if "role" not in admin_columns:
        db.session.execute(
            text(
                f"ALTER TABLE {AdminUser.__tablename__} "
                "ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'ADMIN'"
            )
        )
    if "password_change_required" not in admin_columns:
        db.session.execute(
            text(
                f"ALTER TABLE {AdminUser.__tablename__} "
                "ADD COLUMN password_change_required BOOLEAN NOT NULL DEFAULT 0"
            )
        )
    db.session.commit()
