import random

from flask import Flask

from config import Config
from .extensions import db


def create_app(config_class=Config):
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app.config.from_object(config_class)

    db.init_app(app)

    from . import models  # noqa: F401
    from .admin_auth import bootstrap_admins, configure_admin_context
    from .gamification import purge_admin_game_data
    from .game import game_bp
    from .gamification import gamification_bp
    from .admin import admin_bp
    from .profile_photo import delete_profile_photo, profile_photo_bp
    from .visitor_session import (
        enforce_visitor_session,
        maybe_purge_expired_guests,
        purge_expired_guests,
        visitor_session_bp,
    )

    app.before_request(maybe_purge_expired_guests)
    app.before_request(enforce_visitor_session)
    app.register_blueprint(game_bp)
    app.register_blueprint(gamification_bp)
    app.register_blueprint(visitor_session_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(profile_photo_bp)

    with app.app_context():
        db.create_all()
        models.ensure_schema()
        models.Settings.get()  # asegura que exista la fila de configuración
        bootstrap_admins(app.config.get("ADMIN_BOOTSTRAP_PASSWORD"))
        for filename in purge_admin_game_data():
            delete_profile_photo(filename)
        purge_expired_guests()

    configure_admin_context(app)

    @app.cli.command("purge-expired-guests")
    def purge_expired_guests_command():
        """Remove guest profiles whose 24-hour retention period elapsed."""
        print(f"Purged guest profiles: {purge_expired_guests()}")

    @app.template_filter("shuffled")
    def _shuffled(seq):
        seq = list(seq)
        random.shuffle(seq)
        return seq

    return app
