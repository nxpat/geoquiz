"""Database models."""

import json
from datetime import datetime, timezone

from .extensions import db


class Question(db.Model):
    __tablename__ = "question"

    # 1. Language-Agnostic Core Data
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    rue = db.Column(db.String(100), nullable=False)
    active = db.Column(db.Boolean, default=True)
    ordre = db.Column(db.Integer, default=0)

    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)

    # Media Fields (Store lists of URLs/IDs as JSON strings)
    media_images = db.Column(db.Text, nullable=True)
    media_videos = db.Column(db.Text, nullable=True)

    # 2. Relationship to Translations
    # cascade="all, delete-orphan" ensures translations are deleted if the question is deleted
    translations = db.relationship(
        "QuestionTranslation",
        backref="question",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    def get_translation(self, lang_code):
        """Fetches the requested translation, or falls back to French."""
        for t in self.translations:
            if t.language_code == lang_code:
                return t

        # Fallback to French if the requested language isn't found
        for t in self.translations:
            if t.language_code == "fr":
                return t

        return None  # Failsafe if no translations exist at all

    def to_dict(self, lang="fr"):
        trans = self.get_translation(lang)

        # Safely parse JSON choices
        choix_list = []
        if trans and trans.choix:
            try:
                choix_list = json.loads(trans.choix)
            except Exception:
                choix_list = []

        # Safely parse media strings back into Python lists
        images_list = []
        if self.media_images:
            try:
                images_list = json.loads(self.media_images)
            except Exception:
                pass

        videos_list = []
        if self.media_videos:
            try:
                videos_list = json.loads(self.media_videos)
            except Exception:
                pass

        return {
            "id": self.id,
            "code": self.code,
            "rue": self.rue,
            "active": self.active,
            "question": trans.question_text if trans else "",
            "choix": choix_list,
            "reponse": trans.reponse if trans else "",
            "commentaire_bon": trans.commentaire_bon if trans else "",
            "commentaire_mauvais": trans.commentaire_mauvais if trans else "",
            "media_images": images_list,
            "media_videos": videos_list,
        }


class QuestionTranslation(db.Model):
    __tablename__ = "question_translation"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)

    # e.g., 'fr', 'en', 'ko'
    language_code = db.Column(db.String(5), nullable=False)

    # 3. Localized Data Fields
    question_text = db.Column(db.Text, nullable=False)
    choix = db.Column(db.Text, nullable=False)  # Stored as JSON string
    reponse = db.Column(db.String(255), nullable=False)
    commentaire_bon = db.Column(db.Text)
    commentaire_mauvais = db.Column(db.Text)

    # Prevent duplicate translations for the same language on a single question
    __table_args__ = (
        db.UniqueConstraint(
            "question_id", "language_code", name="uix_question_language"
        ),
    )


class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    prenom = db.Column(db.String(100), nullable=False)
    nom = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    score = db.Column(db.Integer, default=0)
    nb_reponses = db.Column(db.Integer, default=0)
    date_debut = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    termine = db.Column(db.Boolean, default=False)


class ReponseLog(db.Model):
    __tablename__ = "reponse_log"
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=True)
    reponse = db.Column(db.String(300))
    bonne = db.Column(db.Boolean, default=False)
    date = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    question = db.relationship("Question", backref="logs")
