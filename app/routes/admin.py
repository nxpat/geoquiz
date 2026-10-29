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
from ..kml import sync_plaque_coords
from ..models import Participant, Question, ReponseLog

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


@bp.route("/admin/sync-map")
def admin_sync_map():
    """Synchronise les coordonnées des plaques depuis Google My Maps."""
    if not admin_required():
        return redirect(url_for("admin.admin"))
    _nb, msg = sync_plaque_coords()
    flash(f"🗺️ {msg}", "succes")
    return redirect(url_for("admin.admin"))


@bp.route("/admin/questions")
def admin_questions():
    if not admin_required():
        return redirect(url_for("admin.admin"))
    questions = Question.query.order_by(Question.ordre, Question.id).all()
    return render_template("admin_questions.html", questions=questions)


def _parse_question_form(form):
    """Parse and validate multilingual question form fields."""
    code = form.get("code", "").strip()
    rue = form.get("rue", "").strip()
    # FR
    q_fr = form.get("question", "").strip()
    c1, c2, c3 = (
        form.get("choix1", "").strip(),
        form.get("choix2", "").strip(),
        form.get("choix3", "").strip(),
    )
    rep_fr = form.get("reponse", "").strip()
    cb_fr = form.get("commentaire_bon", "").strip()
    cm_fr = form.get("commentaire_mauvais", "").strip()
    # EN
    q_en = form.get("question_en", "").strip()
    c1e, c2e, c3e = (
        form.get("choix1_en", "").strip(),
        form.get("choix2_en", "").strip(),
        form.get("choix3_en", "").strip(),
    )
    rep_en = form.get("reponse_en", "").strip()
    cb_en = form.get("commentaire_bon_en", "").strip()
    cm_en = form.get("commentaire_mauvais_en", "").strip()
    # KO
    q_ko = form.get("question_ko", "").strip()
    c1k, c2k, c3k = (
        form.get("choix1_ko", "").strip(),
        form.get("choix2_ko", "").strip(),
        form.get("choix3_ko", "").strip(),
    )
    rep_ko = form.get("reponse_ko", "").strip()
    cb_ko = form.get("commentaire_bon_ko", "").strip()
    cm_ko = form.get("commentaire_mauvais_ko", "").strip()

    erreurs = []
    if not code:
        erreurs.append("Le code est obligatoire.")
    elif not re.fullmatch(r"\d{1,10}", code):
        erreurs.append("Le code doit être numérique.")
    if not rue:
        erreurs.append("Le nom de rue est obligatoire.")
    if not q_fr:
        erreurs.append("La question (FR) est obligatoire.")
    if not (c1 and c2 and c3):
        erreurs.append("Les 3 choix (FR) sont obligatoires.")
    if not rep_fr:
        erreurs.append("La bonne réponse (FR) est obligatoire.")
    elif rep_fr not in [c1, c2, c3]:
        erreurs.append("La bonne réponse (FR) doit être un des 3 choix.")
    if any([q_en, c1e, c2e, c3e, rep_en]):
        if not (c1e and c2e and c3e):
            erreurs.append(
                "Les 3 choix (EN) sont obligatoires si la version anglaise est renseignée."
            )
        elif rep_en and rep_en not in [c1e, c2e, c3e]:
            erreurs.append("La bonne réponse (EN) doit être un des 3 choix anglais.")
    if any([q_ko, c1k, c2k, c3k, rep_ko]):
        if not (c1k and c2k and c3k):
            erreurs.append(
                "Les 3 choix (KO) sont obligatoires si la version coréenne est renseignée."
            )
        elif rep_ko and rep_ko not in [c1k, c2k, c3k]:
            erreurs.append("La bonne réponse (KO) doit être un des 3 choix coréens.")

    data = {
        "code": code,
        "rue": rue,
        "question": q_fr,
        "choix": json.dumps([c1, c2, c3], ensure_ascii=False),
        "reponse": rep_fr,
        "commentaire_bon": cb_fr,
        "commentaire_mauvais": cm_fr,
        "question_en": q_en or None,
        "choix_en": json.dumps([c1e, c2e, c3e], ensure_ascii=False)
        if (c1e and c2e and c3e)
        else None,
        "reponse_en": rep_en or None,
        "commentaire_bon_en": cb_en or None,
        "commentaire_mauvais_en": cm_en or None,
        "question_ko": q_ko or None,
        "choix_ko": json.dumps([c1k, c2k, c3k], ensure_ascii=False)
        if (c1k and c2k and c3k)
        else None,
        "reponse_ko": rep_ko or None,
        "commentaire_bon_ko": cb_ko or None,
        "commentaire_mauvais_ko": cm_ko or None,
    }
    return erreurs, data


@bp.route("/admin/questions/nouvelle", methods=["GET", "POST"])
def admin_question_nouvelle():
    if not admin_required():
        return redirect(url_for("admin.admin"))
    if request.method == "POST":
        erreurs, data = _parse_question_form(request.form)
        if not erreurs and Question.query.filter_by(code=data["code"]).first():
            erreurs.append(f"Le code {data['code']} est déjà utilisé.")
        if erreurs:
            return render_template(
                "admin_question_form.html",
                mode="nouvelle",
                erreurs=erreurs,
                form=request.form,
                q=None,
            )
        max_ordre = db.session.query(db.func.max(Question.ordre)).scalar() or 0
        q = Question(ordre=max_ordre + 1, active=True, **data)
        db.session.add(q)
        db.session.commit()
        flash(f'Question "{data["rue"]}" ajoutée avec succès !', "succes")
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
        erreurs, data = _parse_question_form(request.form)
        existing = Question.query.filter_by(code=data["code"]).first()
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
        for key, val in data.items():
            setattr(q, key, val)
        db.session.commit()
        flash(f'Question "{q.rue}" modifiée avec succès !', "succes")
        return redirect(url_for("admin.admin_questions"))

    cl_fr = q.choix_list("fr")
    cl_en = q.choix_list("en") if q.choix_en else ["", "", ""]
    cl_ko = q.choix_list("ko") if q.choix_ko else ["", "", ""]

    def safe(lst, i):
        return lst[i] if len(lst) > i else ""

    form = {
        "code": q.code,
        "rue": q.rue,
        "question": q.question,
        "choix1": safe(cl_fr, 0),
        "choix2": safe(cl_fr, 1),
        "choix3": safe(cl_fr, 2),
        "reponse": q.reponse,
        "commentaire_bon": q.commentaire_bon,
        "commentaire_mauvais": q.commentaire_mauvais,
        "question_en": q.question_en or "",
        "choix1_en": safe(cl_en, 0),
        "choix2_en": safe(cl_en, 1),
        "choix3_en": safe(cl_en, 2),
        "reponse_en": q.reponse_en or "",
        "commentaire_bon_en": q.commentaire_bon_en or "",
        "commentaire_mauvais_en": q.commentaire_mauvais_en or "",
        "question_ko": q.question_ko or "",
        "choix1_ko": safe(cl_ko, 0),
        "choix2_ko": safe(cl_ko, 1),
        "choix3_ko": safe(cl_ko, 2),
        "reponse_ko": q.reponse_ko or "",
        "commentaire_bon_ko": q.commentaire_bon_ko or "",
        "commentaire_mauvais_ko": q.commentaire_mauvais_ko or "",
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
