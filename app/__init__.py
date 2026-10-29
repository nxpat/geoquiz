"""Application factory for France Seorae Quiz.

Creates the Flask app, binds extensions, registers blueprints,
runs DB migration / seeding, and kicks off the KML sync at startup.
"""

import os

from dotenv import load_dotenv
from flask import Flask

from .config import Config
from .extensions import db

# Load .env at import time so os.environ is populated before Config is read
load_dotenv()

# Templates + static live at the project root, next to run.py
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, "templates")
_STATIC_DIR = os.path.join(_PROJECT_ROOT, "static")


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__, template_folder=_TEMPLATE_DIR, static_folder=_STATIC_DIR)
    app.config.from_object(config_class)

    # ── Extensions ─────────────────────────────────────────
    db.init_app(app)

    # ── Context processor: expose translations to templates ─
    from .translations import SUPPORTED_LANGS, TRANSLATIONS, get_lang, t

    @app.context_processor
    def inject_globals():
        lang = get_lang()
        return {
            "t": t,
            "current_lang": lang,
            "supported_langs": SUPPORTED_LANGS,
            "translations": TRANSLATIONS,
        }

    # ── Security headers ───────────────────────────────────
    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    # ── Template global: proxy_img(url) ────────────────────
    from .helpers import media_proxy_view, proxy_img

    app.add_template_global(proxy_img, "proxy_img")

    # /media-proxy is a plain view (not part of any blueprint) so it can
    # be called via the helper without importing a blueprint's endpoint.
    app.add_url_rule("/media-proxy", endpoint="media_proxy", view_func=media_proxy_view)

    # ── Blueprints ─────────────────────────────────────────
    from .routes.admin import bp as admin_bp
    from .routes.api import bp as api_bp
    from .routes.api import register_error_handlers
    from .routes.main import bp as main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    register_error_handlers(app)

    # ── DB init + seed + KML sync ──────────────────────────
    from .db_utils import migrate_db, seed_questions
    from .kml import sync_plaque_coords

    with app.app_context():
        db.create_all()
        migrate_db()
        seed_questions()
        # Synchronise les coordonnées depuis Google My Maps
        print("[startup] Synchronisation des coordonnées depuis Google My Maps...")
        try:
            sync_plaque_coords()
        except Exception as e:
            print(f"[startup] KML sync failed: {e}")

    return app
