"""Database models."""

import json
from datetime import datetime

from .extensions import db


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), nullable=False, unique=True)
    rue = db.Column(db.String(200), nullable=False)
    # French (obligatoire)
    question = db.Column(db.Text, nullable=False)
    choix = db.Column(db.Text, nullable=False)
    reponse = db.Column(db.String(300), nullable=False)
    commentaire_bon = db.Column(db.Text, nullable=False)
    commentaire_mauvais = db.Column(db.Text, nullable=False)
    # English (optionnel)
    question_en = db.Column(db.Text, nullable=True)
    choix_en = db.Column(db.Text, nullable=True)
    reponse_en = db.Column(db.String(300), nullable=True)
    commentaire_bon_en = db.Column(db.Text, nullable=True)
    commentaire_mauvais_en = db.Column(db.Text, nullable=True)
    # Korean (optionnel)
    question_ko = db.Column(db.Text, nullable=True)
    choix_ko = db.Column(db.Text, nullable=True)
    reponse_ko = db.Column(db.String(300), nullable=True)
    commentaire_bon_ko = db.Column(db.Text, nullable=True)
    commentaire_mauvais_ko = db.Column(db.Text, nullable=True)
    # Meta
    active = db.Column(db.Boolean, default=True)
    ordre = db.Column(db.Integer, default=0)

    def choix_list(self, lang="fr"):
        raw = None
        if lang == "en" and self.choix_en:
            raw = self.choix_en
        elif lang == "ko" and self.choix_ko:
            raw = self.choix_ko

        if not raw:
            raw = self.choix

        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            # This print will instantly tell you if a database row has broken JSON
            print(
                f"[debug] Invalid JSON in choix for lang={lang}, Question Code={self.code}: {raw}"
            )
            return json.loads(self.choix)

    def to_dict(self, lang="fr"):
        # Added .strip() to ensure empty string rows don't cause false positives
        if lang == "en" and self.question_en and self.question_en.strip():
            question = self.question_en
            choix = self.choix_list("en")
            reponse = self.reponse_en or self.reponse
            comm_bon = self.commentaire_bon_en or self.commentaire_bon
            comm_mauv = self.commentaire_mauvais_en or self.commentaire_mauvais

        elif lang == "ko" and self.question_ko and self.question_ko.strip():
            question = self.question_ko
            choix = self.choix_list("ko")
            reponse = self.reponse_ko or self.reponse
            comm_bon = self.commentaire_bon_ko or self.commentaire_bon
            comm_mauv = self.commentaire_mauvais_ko or self.commentaire_mauvais

        else:
            question = self.question
            choix = self.choix_list("fr")
            reponse = self.reponse
            comm_bon = self.commentaire_bon
            comm_mauv = self.commentaire_mauvais

        return {
            "id": self.id,
            "code": self.code,
            "rue": self.rue,
            "question": question,
            "choix": choix,
            "reponse": reponse,
            "commentaire_bon": comm_bon,
            "commentaire_mauvais": comm_mauv,
            "active": self.active,
        }


class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    prenom = db.Column(db.String(100), nullable=False)
    nom = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    score = db.Column(db.Integer, default=0)
    nb_reponses = db.Column(db.Integer, default=0)
    date_debut = db.Column(db.DateTime, default=datetime.utcnow)
    termine = db.Column(db.Boolean, default=False)


class ReponseLog(db.Model):
    __tablename__ = "reponse_log"
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=True)
    reponse = db.Column(db.String(300))
    bonne = db.Column(db.Boolean, default=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    question = db.relationship("Question", backref="logs")
