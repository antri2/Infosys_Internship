"""
My Applications: tracks each job the user has saved or applied to, with
a status (saved / applied / interview / under_review / rejected).
Save/Apply buttons on the Opportunities page POST here via fetch().
"""
import pymysql
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from database.db import get_db


applications_bp = Blueprint("applications", __name__, url_prefix="/applications")

VALID_STATUSES = {"saved", "applied", "interview", "under_review", "rejected"}


def _require_login():
    return "user_id" in session


def _get_current_resume_id(cursor, user_id: int) -> int | None:
    """Return a parsed resume owned by this user, preferring profiles.resume_id."""
    cursor.execute(
        """
        SELECT p.resume_id, r.id AS owned_resume_id
        FROM profiles p
        LEFT JOIN resumes r
          ON r.id = p.resume_id AND r.user_id = p.user_id
        WHERE p.user_id = %s
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    if row and row.get("resume_id") and row.get("owned_resume_id"):
        return row["resume_id"]

    cursor.execute(
        """
        SELECT id
        FROM resumes
        WHERE user_id = %s AND parse_status = 'parsed'
        ORDER BY uploaded_at DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    latest = cursor.fetchone()
    return latest["id"] if latest else None


def _job_exists(cursor, job_id: int) -> bool:
    cursor.execute("SELECT 1 FROM jobs WHERE job_id = %s", (job_id,))
    return cursor.fetchone() is not None


def _preservation_message(action: str, actual_status: str) -> str | None:
    expected = "saved" if action == "save" else "applied"
    if actual_status == expected:
        return None
    label = actual_status.replace("_", " ")
    return f"Existing application status '{label}' was preserved."


def _track_application(job_id: int, action: str):
    if not _require_login():
        return jsonify({"error": "Not logged in."}), 401
    if action not in {"save", "apply"}:
        return jsonify({"error": "Invalid application action."}), 400

    user_id = session["user_id"]
    db = get_db()

    try:
        with db.cursor() as cursor:
            if not _job_exists(cursor, job_id):
                return jsonify({
                    "error": f"Job {job_id} does not exist in MySQL. Run the canonical job synchronization step."
                }), 404

            resume_id = _get_current_resume_id(cursor, user_id)

            if action == "save":
                cursor.execute(
                    """
                    INSERT INTO applications (user_id, job_id, resume_id, status, applied_on)
                    VALUES (%s, %s, %s, 'saved', NULL)
                    ON DUPLICATE KEY UPDATE
                        resume_id = COALESCE(VALUES(resume_id), resume_id)
                    """,
                    (user_id, job_id, resume_id),
                )
            else:
                # applied_on is assigned first so CASE sees the pre-update status.
                # A repeated Apply must not downgrade interview/under_review/rejected.
                cursor.execute(
                    """
                    INSERT INTO applications (user_id, job_id, resume_id, status, applied_on)
                    VALUES (%s, %s, %s, 'applied', CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                        applied_on = IF(status = 'saved', CURRENT_TIMESTAMP, applied_on),
                        status = IF(status = 'saved', 'applied', status),
                        resume_id = COALESCE(VALUES(resume_id), resume_id)
                    """,
                    (user_id, job_id, resume_id),
                )

            created = cursor.rowcount == 1
            cursor.execute(
                """
                SELECT status, applied_on, resume_id
                FROM applications
                WHERE user_id = %s AND job_id = %s
                """,
                (user_id, job_id),
            )
            application = cursor.fetchone()

        db.commit()
    except pymysql.err.IntegrityError:
        db.rollback()
        return jsonify({
            "error": "The application could not be saved because its job or resume is no longer valid."
        }), 409

    actual_status = application["status"]
    payload = {
        "job_id": job_id,
        "status": actual_status,
        "resume_id": application["resume_id"],
        "applied_on": application["applied_on"].isoformat() if application["applied_on"] else None,
        "created": created,
    }
    message = _preservation_message(action, actual_status)
    if message:
        payload["message"] = message

    return jsonify(payload), 201 if created else 200


@applications_bp.route("/", methods=["GET"])
def list_view():
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    user_id = session["user_id"]
    status_filter = request.args.get("status", "all")

    query = """
        SELECT a.job_id, a.status, a.applied_on, a.updated_at, a.resume_id,
               j.title, j.company, j.location, j.job_type
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
    return _track_application(job_id, "save")


@applications_bp.route("/<int:job_id>/apply", methods=["POST"])
def apply(job_id):
    return _track_application(job_id, "apply")
