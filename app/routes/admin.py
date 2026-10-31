"""Admin routes: dashboard, questions CRUD, logs, sync."""

import json
import re
from collections import defaultdict

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..extensions import db
from ..helpers import admin_required
from ..models import Participant, Question, QuestionTranslation, ReponseLog

bp = Blueprint("admin", __name__)


@bp.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        if request.form.get("password", "") == current_app.config["ADMIN_PASSWORD"]:
            session["admin_ok"] = True
        else:
            return render_template("admin_login.html", erreur="Mot de passe incorrect.")
    if not admin_required():
        return render_template("admin_login.html")

    participants = Participant.query.order_by(Participant.score.desc()).all()
    total = Question.query.filter_by(active=True).count()
    total_logs = ReponseLog.query.count()
    correct_logs = ReponseLog.query.filter_by(bonne=True).count()
    pct_correct = int(correct_logs / total_logs * 100) if total_logs > 0 else 0
    avg_score = (
        round(sum(p.score for p in participants) / len(participants), 1)
        if participants
        else 0
    )
    termines = sum(1 for p in participants if p.termine)

    return render_template(
        "admin.html",
        participants=participants,
        total=total,
        total_logs=total_logs,
        pct_correct=pct_correct,
        avg_score=avg_score,
        termines=termines,
    )


@bp.route("/admin/logout")
def admin_logout():
    session.pop("admin_ok", None)
    return redirect(url_for("admin.admin"))


@bp.route("/admin/questions")
def admin_questions():
    if not admin_required():
        return redirect(url_for("admin.admin"))
    questions = Question.query.order_by(Question.ordre, Question.id).all()
    return render_template("admin_questions.html", questions=questions)


def _parse_question_form(form):
    """Parse and validate multilingual question form fields into a relational structure."""
    code = form.get("code", "").strip()
    rue = form.get("rue", "").strip()

    # Extract coordinates
    lat_str = form.get("lat", "").strip()
    lng_str = form.get("lng", "").strip()
    lat = float(lat_str) if lat_str else None
    lng = float(lng_str) if lng_str else None

    erreurs = []
    if not code:
        erreurs.append("Le code est obligatoire.")
    elif not re.fullmatch(r"\d{1,10}", code):
        erreurs.append("Le code doit être numérique.")
    if not rue:
        erreurs.append("Le nom de rue est obligatoire.")

    translations_data = {}

    # Helper function to extract and validate a specific language
    def extract_lang(lang_code, suffix=""):
        q_text = form.get(f"question{suffix}", "").strip()
        c1 = form.get(f"choix1{suffix}", "").strip()
        c2 = form.get(f"choix2{suffix}", "").strip()
        c3 = form.get(f"choix3{suffix}", "").strip()
        rep = form.get(f"reponse{suffix}", "").strip()
        cb = form.get(f"commentaire_bon{suffix}", "").strip()
        cm = form.get(f"commentaire_mauvais{suffix}", "").strip()

        has_data = any([q_text, c1, c2, c3, rep])
        is_required = lang_code == "fr"

        if has_data or is_required:
            if not q_text:
                erreurs.append(f"La question ({lang_code.upper()}) est obligatoire.")
            if not (c1 and c2 and c3):
                erreurs.append(f"Les 3 choix ({lang_code.upper()}) sont obligatoires.")
            if not rep:
                erreurs.append(
                    f"La bonne réponse ({lang_code.upper()}) est obligatoire."
                )
            elif rep not in [c1, c2, c3]:
                erreurs.append(
                    f"La bonne réponse ({lang_code.upper()}) doit être un des 3 choix."
                )

            # If valid, package the translation
            if not erreurs or has_data:
                translations_data[lang_code] = {
                    "question_text": q_text,
                    "choix": json.dumps([c1, c2, c3], ensure_ascii=False)
                    if (c1 and c2 and c3)
                    else "[]",
                    "reponse": rep,
                    "commentaire_bon": cb or None,
                    "commentaire_mauvais": cm or None,
                }

    # Extract all three languages
    extract_lang("fr", "")
    extract_lang("en", "_en")
    extract_lang("ko", "_ko")

    core_data = {"code": code, "rue": rue, "lat": lat, "lng": lng}
    return erreurs, core_data, translations_data


@bp.route("/admin/questions/nouvelle", methods=["GET", "POST"])
def admin_question_nouvelle():
    if not admin_required():
        return redirect(url_for("admin.admin"))
    if request.method == "POST":
        erreurs, core_data, translations_data = _parse_question_form(request.form)

        if not erreurs and Question.query.filter_by(code=core_data["code"]).first():
            erreurs.append(f"Le code {core_data['code']} est déjà utilisé.")

        if erreurs:
            return render_template(
                "admin_question_form.html",
                mode="nouvelle",
                erreurs=erreurs,
                form=request.form,
                q=None,
            )

        max_ordre = db.session.query(db.func.max(Question.ordre)).scalar() or 0
        q = Question(ordre=max_ordre + 1, active=True, **core_data)

        # Attach the relational translations
        for lang_code, t_data in translations_data.items():
            t = QuestionTranslation(language_code=lang_code, **t_data)
            q.translations.append(t)

        db.session.add(q)
        db.session.commit()
        flash(f'Question "{core_data["rue"]}" ajoutée avec succès !', "succes")
        return redirect(url_for("admin.admin_questions"))

    return render_template(
        "admin_question_form.html", mode="nouvelle", erreurs=[], form={}, q=None
    )


@bp.route("/admin/questions/<int:qid>/modifier", methods=["GET", "POST"])
def admin_question_modifier(qid):
    if not admin_required():
        return redirect(url_for("admin.admin"))
    q = db.session.get(Question, qid)
    if not q:
        abort(404)

    if request.method == "POST":
        erreurs, core_data, translations_data = _parse_question_form(request.form)
        existing = Question.query.filter_by(code=core_data["code"]).first()
        if existing and existing.id != qid:
            erreurs.append("Ce code est déjà utilisé par une autre question.")

        if erreurs:
            return render_template(
                "admin_question_form.html",
                mode="modifier",
                erreurs=erreurs,
                form=request.form,
                q=q,
            )

        # Update core
        q.code = core_data["code"]
        q.rue = core_data["rue"]

        # Update or Add translations
        for lang_code, t_data in translations_data.items():
            existing_t = q.get_translation(lang_code)
            if existing_t and existing_t.language_code == lang_code:
                for key, val in t_data.items():
                    setattr(existing_t, key, val)
            else:
                new_t = QuestionTranslation(language_code=lang_code, **t_data)
                q.translations.append(new_t)

        db.session.commit()
        flash(f'Question "{q.rue}" modifiée avec succès !', "succes")
        return redirect(url_for("admin.admin_questions"))

    # Helper to extract JSON arrays for the form
    def get_choix_safe(trans, index):
        if trans and trans.choix:
            try:
                arr = json.loads(trans.choix)
                return arr[index] if len(arr) > index else ""
            except:
                pass
        return ""

    t_fr = q.get_translation("fr")
    t_en = (
        q.get_translation("en")
        if any(t.language_code == "en" for t in q.translations)
        else None
    )
    t_ko = (
        q.get_translation("ko")
        if any(t.language_code == "ko" for t in q.translations)
        else None
    )

    form = {
        "code": q.code,
        "rue": q.rue,
        "lat": q.lat if q.lat is not None else "",
        "lng": q.lng if q.lng is not None else "",
        "question": t_fr.question_text if t_fr else "",
        "choix1": get_choix_safe(t_fr, 0),
        "choix2": get_choix_safe(t_fr, 1),
        "choix3": get_choix_safe(t_fr, 2),
        "reponse": t_fr.reponse if t_fr else "",
        "commentaire_bon": t_fr.commentaire_bon if t_fr else "",
        "commentaire_mauvais": t_fr.commentaire_mauvais if t_fr else "",
        "question_en": t_en.question_text if t_en else "",
        "choix1_en": get_choix_safe(t_en, 0),
        "choix2_en": get_choix_safe(t_en, 1),
        "choix3_en": get_choix_safe(t_en, 2),
        "reponse_en": t_en.reponse if t_en else "",
        "commentaire_bon_en": t_en.commentaire_bon if t_en else "",
        "commentaire_mauvais_en": t_en.commentaire_mauvais if t_en else "",
        "question_ko": t_ko.question_text if t_ko else "",
        "choix1_ko": get_choix_safe(t_ko, 0),
        "choix2_ko": get_choix_safe(t_ko, 1),
        "choix3_ko": get_choix_safe(t_ko, 2),
        "reponse_ko": t_ko.reponse if t_ko else "",
        "commentaire_bon_ko": t_ko.commentaire_bon if t_ko else "",
        "commentaire_mauvais_ko": t_ko.commentaire_mauvais if t_ko else "",
    }

    return render_template(
        "admin_question_form.html", mode="modifier", erreurs=[], form=form, q=q
    )


@bp.route("/admin/questions/<int:qid>/pause", methods=["POST"])
def admin_question_pause(qid):
    if not admin_required():
        return redirect(url_for("admin.admin"))
    q = db.session.get(Question, qid)
    if not q:
        abort(404)
    q.active = not q.active
    db.session.commit()
    etat = "activée" if q.active else "mise en pause"
    flash(f'Question "{q.rue}" {etat}.', "succes")
    return redirect(url_for("admin.admin_questions"))


@bp.route("/admin/questions/<int:qid>/supprimer", methods=["POST"])
def admin_question_supprimer(qid):
    if not admin_required():
        return redirect(url_for("admin.admin"))
    q = db.session.get(Question, qid)
    if not q:
        abort(404)
    nom = q.rue
    ReponseLog.query.filter_by(question_id=qid).delete()
    db.session.delete(q)
    db.session.commit()
    flash(f'Question "{nom}" supprimée définitivement.', "succes")
    return redirect(url_for("admin.admin_questions"))


@bp.route("/admin/logs")
def admin_logs():
    if not admin_required():
        return redirect(url_for("admin.admin"))
    questions = Question.query.order_by(Question.ordre, Question.id).all()
    q_stats = []
    for q in questions:
        logs = ReponseLog.query.filter_by(question_id=q.id).all()
        total_attempts = len(logs)
        correct = sum(1 for l in logs if l.bonne)
        pct = int(correct / total_attempts * 100) if total_attempts > 0 else None
        q_stats.append(
            {
                "id": q.id,
                "rue": q.rue,
                "code": q.code,
                "active": q.active,
                "attempts": total_attempts,
                "correct": correct,
                "pct": pct,
            }
        )

    q_stats_hardest = sorted(
        [s for s in q_stats if s["pct"] is not None], key=lambda x: x["pct"]
    )[:10]
    q_stats_popular = sorted(q_stats, key=lambda x: x["attempts"], reverse=True)[:10]

    participants = Participant.query.all()
    total_logs = ReponseLog.query.count()
    correct_logs = ReponseLog.query.filter_by(bonne=True).count()
    pct_global = int(correct_logs / total_logs * 100) if total_logs > 0 else 0
    avg_score = (
        round(sum(p.score for p in participants) / len(participants), 1)
        if participants
        else 0
    )
    termines = sum(1 for p in participants if p.termine)
    recent = ReponseLog.query.order_by(ReponseLog.date.desc()).limit(30).all()

    daily = defaultdict(int)
    for p in participants:
        daily[p.date_debut.strftime("%d/%m")] += 1
    daily_sorted = list(daily.items())[-14:]
    max_daily = max((v for _, v in daily_sorted), default=1)

    score_dist = defaultdict(int)
    for p in participants:
        score_dist[(p.score // 5) * 5] += 1

    return render_template(
        "admin_logs.html",
        q_stats=q_stats,
        q_stats_hardest=q_stats_hardest,
        q_stats_popular=q_stats_popular,
        total_logs=total_logs,
        correct_logs=correct_logs,
        pct_global=pct_global,
        avg_score=avg_score,
        termines=termines,
        total_participants=len(participants),
        recent=recent,
        daily_sorted=daily_sorted,
        max_daily=max_daily,
        score_dist=dict(score_dist),
    )
