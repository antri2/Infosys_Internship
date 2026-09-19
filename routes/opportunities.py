"""
Opportunities page: one unified list (no separate "recommendations" vs
"internships" split, per product decision). Ranks jobs against the
logged-in user's profile using the RAG semantic search when available,
computes a match percentage + missing skills per job via
services.job_matcher, and shows which jobs the user has already
saved/applied to.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session

from database.db import get_db
from services.job_matcher import compute_match
from services.opportunity_service import search_jobs

opportunities_bp = Blueprint("opportunities", __name__, url_prefix="/opportunities")


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

    jobs = search_jobs(search_query, top_k=20)

    enriched = []
    for job in jobs:
        match_info = compute_match(user_skills, job)
        job_id = int(job["job_id"])
        enriched.append({
            **job,
            "job_id": job_id,
            **match_info,
            "application_status": applied_status.get(job_id),
        })

    enriched.sort(key=lambda j: j["match_percent"], reverse=True)

    return render_template(
        "opportunities.html",
        active_page="opportunities",
        jobs=enriched,
        search_query=request.args.get("q", ""),
        has_skills=bool(user_skills),
    )