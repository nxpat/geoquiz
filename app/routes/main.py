"""Player-facing routes: accueil, carte, question, enregistrer, résultats."""

import re

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..extensions import db
from ..helpers import email_valid, init_session
from ..models import Participant, Question
from ..translations import SUPPORTED_LANGS, get_lang, t

bp = Blueprint("main", __name__)


# ── Language switch ───────────────────────────────────────────


@bp.route("/set_lang/<lang>")
def set_lang(lang):
    if lang in SUPPORTED_LANGS:
        session["lang"] = lang
    next_url = request.args.get("next") or request.referrer or url_for("main.carte")
    return redirect(next_url)


# ── Public pages ──────────────────────────────────────────────


@bp.route("/")
def index():
    admin_ok = session.get("admin_ok", False)

    # Use get_lang() to trigger the auto-detect logic instead of hardcoding "fr"
    lang = get_lang()

    session.clear()
    if admin_ok:
        session["admin_ok"] = True

    session["lang"] = lang
    session["reponses_ids"] = []
    session["score"] = 0
    return render_template("accueil.html")


@bp.route("/carte")
def carte():
    init_session()
    total = Question.query.filter_by(active=True).count()

    # Build map data using database coordinates directly
    questions_map_data = []
    for q in (
        Question.query.filter_by(active=True)
        .order_by(Question.ordre, Question.id)
        .all()
    ):
        # Only add to map if coordinates exist in the database
        if q.lat is not None and q.lng is not None:
            questions_map_data.append(
                {
                    "rue": q.rue,
                    "lat": q.lat,
                    "lng": q.lng,
                }
            )

    return render_template(
        "carte.html",
        score=session["score"],
        nb_repondu=len(session["reponses_ids"]),
        total=total,
        questions_map_data=questions_map_data,
        google_maps_key=current_app.config["GOOGLE_MAPS_KEY"],
    )


@bp.route("/question", methods=["GET", "POST"])
def question():
    init_session()
    lang = get_lang()

    if request.method == "POST":
        raw = request.form.get("code", "").strip()
        raw = re.sub(r"\D", "", raw)
        try:
            code = str(int(raw)) if raw else ""
        except ValueError:
            code = ""
        q = Question.query.filter_by(code=code, active=True).first()
        if not q:
            return render_template(
                "saisie_code.html",
                erreur=t("code_not_found"),
                score=session["score"],
                code_prefill="",
            )
        deja_repondu = q.id in session["reponses_ids"]
        q_dict = q.to_dict(lang)
        return render_template(
            "question.html",
            q=q_dict,
            deja_repondu=deja_repondu,
            score=session["score"],
            media_images=q_dict.get("media_images", []),
            media_videos=q_dict.get("media_videos", []),
        )

    code_prefill = request.args.get("code", "")
    if code_prefill:
        raw = re.sub(r"\D", "", code_prefill)
        try:
            code = str(int(raw)) if raw else ""
        except ValueError:
            code = ""
        q = Question.query.filter_by(code=code, active=True).first()
        q_dict = q.to_dict(lang)
        if q:
            deja_repondu = q.id in session["reponses_ids"]
            return render_template(
                "question.html",
                q=q_dict,
                deja_repondu=deja_repondu,
                score=session["score"],
                media_images=q_dict.get("media_images", []),
                media_videos=q_dict.get("media_videos", []),
            )

    return render_template(
        "saisie_code.html", score=session["score"], code_prefill=code_prefill
    )


@bp.route("/repondre", methods=["POST"])
def repondre():
    from ..models import ReponseLog

    init_session()
    lang = get_lang()
    total = Question.query.filter_by(active=True).count()

    try:
        question_id = int(request.form.get("question_id", ""))
    except (ValueError, TypeError):
        return redirect(url_for("main.carte"))

    reponse_donnee = request.form.get("reponse", "").strip()
    q_obj = db.session.get(Question, question_id)
    if not q_obj or not q_obj.active:
        return redirect(url_for("main.carte"))

    q = q_obj.to_dict(lang)

    if not reponse_donnee:
        return render_template(
            "question.html",
            q=q,
            deja_repondu=False,
            score=session["score"],
            erreur=t("question_no_answer"),
            media_images=q.get("media_images", []),
            media_videos=q.get("media_videos", []),
        )

    if reponse_donnee not in q["choix"]:
        return render_template(
            "question.html",
            q=q,
            deja_repondu=False,
            score=session["score"],
            erreur=t("question_invalid"),
            media_images=q.get("media_images", []),
            media_videos=q.get("media_videos", []),
        )

    bonne = reponse_donnee == q["reponse"]
    reponses_ids = list(session["reponses_ids"])

    log = ReponseLog(question_id=question_id, reponse=reponse_donnee, bonne=bonne)
    db.session.add(log)
    db.session.commit()

    if question_id not in reponses_ids:
        reponses_ids.append(question_id)
        session["reponses_ids"] = reponses_ids
        session.modified = True
        if bonne:
            session["score"] += 1

    commentaire = q["commentaire_bon"] if bonne else q["commentaire_mauvais"]
    return render_template(
        "resultat_question.html",
        bonne=bonne,
        commentaire=commentaire,
        q=q,
        score=session["score"],
        nb_repondu=len(session["reponses_ids"]),
        total=total,
    )


@bp.route("/enregistrer", methods=["GET", "POST"])
def enregistrer():
    init_session()
    total = Question.query.filter_by(active=True).count()

    if "participant_id" in session:
        return redirect(url_for("main.resultats_finaux"))

    if request.method == "POST":
        prenom = request.form.get("prenom", "").strip()[:100]
        nom = request.form.get("nom", "").strip()[:100]
        email = request.form.get("email", "").strip()[:200].lower()

        erreurs = []
        if not prenom:
            erreurs.append(t("register_err_firstname"))
        if not nom:
            erreurs.append(t("register_err_lastname"))
        if not email:
            erreurs.append(t("register_err_email"))
        elif not email_valid(email):
            erreurs.append(t("register_err_email_invalid"))

        if erreurs:
            return render_template(
                "enregistrer.html",
                erreur=" ".join(erreurs),
                score=session["score"],
                nb_repondu=len(session["reponses_ids"]),
                total=total,
            )

        p = Participant(
            prenom=prenom,
            nom=nom,
            email=email,
            score=session["score"],
            nb_reponses=len(session["reponses_ids"]),
            termine=True,
        )
        db.session.add(p)
        db.session.commit()
        session["participant_id"] = p.id
        return redirect(url_for("main.resultats_finaux"))

    return render_template(
        "enregistrer.html",
        score=session["score"],
        nb_repondu=len(session["reponses_ids"]),
        total=total,
    )


@bp.route("/resultats_finaux")
def resultats_finaux():
    init_session()
    total = Question.query.filter_by(active=True).count()
    p = None
    if "participant_id" in session:
        p = db.session.get(Participant, session["participant_id"])
    return render_template(
        "resultats_finaux.html",
        participant=p,
        score=session["score"],
        nb_repondu=len(session["reponses_ids"]),
        total=total,
    )
