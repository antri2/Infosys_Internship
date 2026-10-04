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
from services.context_builder import get_candidate_context, get_job_context
from services.job_matcher import compute_match
from services.job_summary_agent import generate_job_summary
from services.opportunity_service import recommend_jobs

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
        # Build a query from the user's profile so results are personalized
        # even when they haven't typed a search.
        search_query = ", ".join(user_skills) if user_skills else "internship entry level"

    ranked_jobs = recommend_jobs(search_query, user_skills, top_k=20)

    enriched = []
    for job in ranked_jobs:
        job_id = int(job["job_id"])
        enriched.append({
            **job,
            "application_status": applied_status.get(job_id),
        })

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