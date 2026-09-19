"""
My Applications: tracks each job the user has saved or applied to, with
a status (saved / applied / interview / under_review / rejected).
Save/Apply buttons on the Opportunities page POST here via fetch().
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify

from database.db import get_db

applications_bp = Blueprint("applications", __name__, url_prefix="/applications")

VALID_STATUSES = {"saved", "applied", "interview", "under_review", "rejected"}


def _require_login():
    return "user_id" in session


@applications_bp.route("/", methods=["GET"])
def list_view():
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    user_id = session["user_id"]
    status_filter = request.args.get("status", "all")

    query = """
        SELECT a.job_id, a.status, a.applied_on, j.title, j.company, j.location, j.job_type
        FROM applications a
        JOIN jobs j ON j.job_id = a.job_id
        WHERE a.user_id = %s
    """
    params = [user_id]
    if status_filter != "all" and status_filter in VALID_STATUSES:
        query += " AND a.status = %s"
        params.append(status_filter)
    query += " ORDER BY a.updated_at DESC"

    with db.cursor() as cursor:
        cursor.execute(query, params)
        applications = cursor.fetchall()

    return render_template(
        "applications.html",
        active_page="applications",
        applications=applications,
        status_filter=status_filter,
    )


@applications_bp.route("/<int:job_id>/save", methods=["POST"])
def save(job_id):
    if not _require_login():
        return jsonify({"error": "Not logged in."}), 401

    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO applications (user_id, job_id, status)
            VALUES (%s, %s, 'saved')
            ON DUPLICATE KEY UPDATE status = status
            """,
            (session["user_id"], job_id),
        )
        db.commit()
    return jsonify({"status": "saved"})


@applications_bp.route("/<int:job_id>/apply", methods=["POST"])
def apply(job_id):
    if not _require_login():
        return jsonify({"error": "Not logged in."}), 401

    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO applications (user_id, job_id, status)
            VALUES (%s, %s, 'applied')
            ON DUPLICATE KEY UPDATE status = 'applied', applied_on = CURRENT_TIMESTAMP
            """,
            (session["user_id"], job_id),
        )
        db.commit()
    return jsonify({"status": "applied"})