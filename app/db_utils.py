"""Database migration & seeding helpers."""

import json
import os
import sqlite3

from flask import current_app

from .extensions import db
from .models import Question, QuestionTranslation


def migrate_db():
    """Add any missing multilingual columns on an existing SQLite DB."""
    # Flask-SQLAlchemy stocke la DB dans instance/ ou à la racine
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    possible_paths = [
        os.path.join(project_root, "instance", "quiz.db"),
        os.path.join(project_root, "quiz.db"),
    ]
    db_path = next((p for p in possible_paths if os.path.exists(p)), None)
    if not db_path:
        return
    new_cols = [
        ("question_en", "TEXT"),
        ("choix_en", "TEXT"),
        ("reponse_en", "VARCHAR(300)"),
        ("commentaire_bon_en", "TEXT"),
        ("commentaire_mauvais_en", "TEXT"),
        ("question_ko", "TEXT"),
        ("choix_ko", "TEXT"),
        ("reponse_ko", "VARCHAR(300)"),
        ("commentaire_bon_ko", "TEXT"),
        ("commentaire_mauvais_ko", "TEXT"),
    ]
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(question)")
        existing = {row[1] for row in cur.fetchall()}
        for col, typ in new_cols:
            if col not in existing:
                cur.execute(f"ALTER TABLE question ADD COLUMN {col} {typ}")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Migration warning: {e}")


def seed_questions():
    """Seeds the database with questions from a JSON file if the table is empty."""
    if Question.query.count() > 0:
        return  # Database already seeded

    json_path = os.path.join(current_app.root_path, "..", "questions_seed.json")
    if not os.path.exists(json_path):
        print(f"[seed] No seed file found at {json_path}")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data:
        # 1. Create the core question
        q = Question(
            code=item.get("code"),
            rue=item.get("rue"),
            active=item.get("active", True),
            ordre=item.get("ordre", 0),
            lat=item.get("lat"),
            lng=item.get("lng"),
        )
        db.session.add(q)
        db.session.flush()  # Get the new question ID before committing

        # Helper to safely extract and add a translation
        def add_translation(item, q, lang, prefix=""):
            q_text = item.get(f"question{prefix}")
            if not q_text and lang != "fr":
                return  # Skip empty optional translations

            t = QuestionTranslation(
                question_id=q.id,
                language_code=lang,
                question_text=q_text or "",
                choix=item.get(f"choix{prefix}", "[]"),
                reponse=item.get(f"reponse{prefix}", ""),
                commentaire_bon=item.get(f"commentaire_bon{prefix}"),
                commentaire_mauvais=item.get(f"commentaire_mauvais{prefix}"),
            )
            db.session.add(t)

        # 2. Add the translations
        add_translation(item, q, "fr", "")
        add_translation(item, q, "en", "_en")
        add_translation(item, q, "ko", "_ko")

    db.session.commit()
    print(
        f"[seed] Successfully loaded {len(data)} questions into the relational database."
    )
