"""
Opportunities page: one unified list (no separate "recommendations" vs
"internships" split, per product decision). Ranks jobs against the
logged-in user's profile using the RAG semantic search when available,
computes a match percentage + missing skills per job via
services.job_matcher, and shows which jobs the user has already
saved/applied to.
"""
import logging

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from database.db import get_db
from services.adzuna_service import (
    _ADZUNA_JOB_ID_OFFSET as ADZUNA_JOB_ID_OFFSET,
    _ADZUNA_JOB_ID_SPAN as ADZUNA_JOB_ID_SPAN,
)
from services.context_builder import get_candidate_context, get_job_context
from services.job_dates import (
    format_date,
    is_demo_listing,
    validated_publication_date,
)
from services.job_matcher import compute_match
from services.job_summary_agent import generate_job_summary
from services.notification_service import notify_new_opportunities
from services.opportunity_service import build_default_query, recommend_jobs

opportunities_bp = Blueprint("opportunities", __name__, url_prefix="/opportunities")
logger = logging.getLogger(__name__)


def _require_login():
    return "user_id" in session


def _get_user_skills(db, user_id: int) -> list[str]:
    with db.cursor() as cursor:
        cursor.execute("SELECT name FROM skills WHERE user_id = %s", (user_id,))
        return [row["name"] for row in cursor.fetchall()]


def _get_application_status_map(db, user_id: int) -> dict:
    with db.cursor() as cursor:
        cursor.execute("SELECT job_id, status FROM applications WHERE user_id = %s", (user_id,))
        return {row["job_id"]: row["status"] for row in cursor.fetchall()}


def _attach_local_dates(db, jobs: list[dict]) -> None:
    """Fill published_date for local jobs from the existing jobs.created_at.

    The canonical CSV has no posting-date column, so `created_at` (the row
    import timestamp) is the only existing field there is. Live Adzuna rows
    already carry their own real published_date and are left untouched. No
    deadline is produced here: the local dataset has no such field, so the card
    renders "Not specified".
    """
    local_ids: list[int] = []
    for job in jobs:
        if job.get("source") == "adzuna":
            job.setdefault("application_deadline", "")
            continue
        raw = str(job.get("job_id", ""))
        if not raw.isdigit():
            job["published_date"] = ""
            job.setdefault("application_deadline", "")
            continue
        value = int(raw)
        # Skip anything in the reserved live range; those are Adzuna ids.
        if ADZUNA_JOB_ID_OFFSET <= value < ADZUNA_JOB_ID_OFFSET + ADZUNA_JOB_ID_SPAN:
            job["published_date"] = ""
            job.setdefault("application_deadline", "")
            continue
        local_ids.append(value)

    created_map: dict[int, object] = {}
    if local_ids:
        placeholders = ", ".join(["%s"] * len(local_ids))
        with db.cursor() as cursor:
            cursor.execute(
                f"SELECT job_id, created_at FROM jobs WHERE job_id IN ({placeholders})",
                local_ids,
            )
            created_map = {row["job_id"]: row["created_at"] for row in cursor.fetchall()}

    for job in jobs:
        if "published_date" in job:
            continue  # already decided above (live, unparseable, or reserved)
        raw = str(job.get("job_id", ""))
        job["published_date"] = format_date(created_map.get(int(raw))) if raw.isdigit() else ""
        job.setdefault("application_deadline", "")


@opportunities_bp.route("/", methods=["GET"])
def list_view():
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    user_id = session["user_id"]
    user_skills = _get_user_skills(db, user_id)
    applied_status = _get_application_status_map(db, user_id)

    search_query = request.args.get("q", "").strip()
    if not search_query:
        # No search typed: personalize from the profile so a signed-in user
        # sees relevant live opportunities immediately. This is the same
        # default the shared helper uses, so the page and the service agree.
        search_query = build_default_query(user_skills)

    ranked_jobs = recommend_jobs(search_query, user_skills, top_k=20)

    enriched = []
    for job in ranked_jobs:
        job_id = int(job["job_id"])
        enriched.append({
            **job,
            "application_status": applied_status.get(job_id),
        })

    _attach_local_dates(db, enriched)

    # A publication date is shown only when it is real.
    #
    # `_attach_local_dates` fills `published_date` from jobs.created_at for the
    # seeded rows, because that is the only timestamp they carry -- but
    # created_at is when the row was imported, not when the role was posted, so
    # rendering it as a publication date would be false. Generated listings
    # therefore get an empty display date; live Adzuna listings keep the real
    # one the source published.
    for job in enriched:
        job["display_published_date"] = (
            "" if is_demo_listing(job) else validated_publication_date(job.get("published_date"))
        )

    # Announce well-matched jobs the user has not tracked yet. This only reads
    # the jobs the recommendation flow just returned, and the unique dedupe key
    # means the same job is never announced twice.
    notify_new_opportunities(db, user_id, enriched)

    return render_template(
        "opportunities.html",
        active_page="opportunities",
        jobs=enriched,
        search_query=request.args.get("q", ""),
        has_skills=bool(user_skills),
    )


@opportunities_bp.route("/<int:job_id>/ai-summary", methods=["POST"])
def ai_summary(job_id):
    """Return a short, fact-grounded summary for one selected MySQL job."""
    if not _require_login():
        return jsonify({"success": False, "error": "Not logged in."}), 401

    db = get_db()
    job = get_job_context(db, job_id)
    if not job:
        return jsonify({
            "success": False,
            "error": f"Job {job_id} was not found.",
        }), 404

    try:
        candidate = get_candidate_context(db, session["user_id"])
        match_info = compute_match(candidate.get("skills", []), job)
        result = generate_job_summary(candidate, job, match_info)
    except Exception:
        logger.exception("AI job summary generation failed for job %s", job_id)
        return jsonify({
            "success": False,
            "error": "The job summary could not be generated right now.",
        }), 503

    return jsonify({
        "success": True,
        "job_id": job_id,
        "summary": result["summary"],
        "used_fallback": result["used_fallback"],
    })