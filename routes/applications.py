"""
My Applications: tracks each job the user has saved or applied to, with
a status (saved / applied / interview / under_review / rejected).
Save/Apply buttons on the Opportunities page POST here via fetch().
"""
import pymysql
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

import logging

from database.db import get_db
from services.notification_service import notify_application


applications_bp = Blueprint("applications", __name__, url_prefix="/applications")
logger = logging.getLogger(__name__)

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


def _ensure_job_row(cursor, job_id: int) -> bool:
    """Make sure a job this user is tracking has a `jobs` row to reference.

    The local dataset stays exactly as it is. A live Adzuna job is only written
    here when the user explicitly saves or applies to it -- never in bulk, and
    never to make browsing work. The id lives in the reserved Adzuna range, so
    it can never collide with the 185 canonical rows, and the loader's
    verification only inspects CSV ids, so the dataset check is unaffected.
    """
    if _job_exists(cursor, job_id):
        return True

    try:
        from services import adzuna_service, live_job_store
    except Exception:
        return False

    if not adzuna_service.is_adzuna_job_id(job_id):
        return False

    job = live_job_store.get(job_id)
    if not job:
        return False

    cursor.execute(
        """
        INSERT INTO jobs
            (job_id, title, company, location, job_type, domain, description,
             responsibilities, required_skills, preferred_skills, qualifications,
             experience_required, education_required, stipend_or_salary, apply_link)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            title=VALUES(title), company=VALUES(company), location=VALUES(location),
            description=VALUES(description), apply_link=VALUES(apply_link)
        """,
        (
            int(job_id),
            job.get("title") or "",
            job.get("company") or "",
            job.get("location") or "",
            job.get("job_type") or "",
            job.get("domain") or "",
            job.get("description") or "",
            job.get("responsibilities") or "",
            job.get("required_skills") or "",
            job.get("preferred_skills") or "",
            job.get("qualifications") or "",
            job.get("experience_required") or "",
            job.get("education_required") or "",
            job.get("stipend_or_salary") or "",
            job.get("apply_link") or "",
        ),
    )
    return True


def _preservation_message(action: str, actual_status: str) -> str | None:
    expected = "saved" if action == "save" else "applied"
    if actual_status == expected:
        return None
    label = actual_status.replace("_", " ")
    return f"Existing application status '{label}' was preserved."


# MySQL error codes seen when a tracking row cannot be written. Mapped to the
# cause that actually applies, so the message describes the user's problem
# instead of a generic one. 1452 is a foreign-key violation, 1062 a duplicate.
_FK_ERROR = 1452
_DUPLICATE_ERROR = 1062

_FK_COLUMN_HINTS = (
    ("applications_ibfk_1", "your sign-in session refers to an account that no longer exists"),
    ("applications_ibfk_2", "this job listing is no longer available, so it can no longer be tracked"),
    ("fk_applications_resume_id", "the resume linked to this application is no longer available"),
)

_ERROR_STATUS = {
    _FK_ERROR: 409,
    _DUPLICATE_ERROR: 409,
}


def _tracking_error_detail(exc) -> str:
    """Explain an IntegrityError using the constraint it actually came from."""
    code = exc.args[0] if exc.args else None
    text = str(exc.args[1]) if len(exc.args) > 1 else str(exc)

    for constraint, reason in _FK_COLUMN_HINTS:
        if constraint in text:
            return f"This application could not be saved because {reason}."

    if code == _FK_ERROR:
        return "This application could not be saved because a linked record is no longer valid."
    if code == _DUPLICATE_ERROR:
        return "This application is already recorded for this job."

    # Unknown code: say what happened without inventing a cause.
    return "This application could not be saved due to a database constraint."


def _track_application(job_id: int, action: str):
    if not _require_login():
        return jsonify({"error": "Not logged in."}), 401
    if action not in {"save", "apply"}:
        return jsonify({"error": "Invalid application action."}), 400

    user_id = session["user_id"]
    db = get_db()

    try:
        with db.cursor() as cursor:
            if not _ensure_job_row(cursor, job_id):
                return jsonify({
                    "error": f"Job {job_id} could not be found. Live listings can only be tracked while they are still open on the job board."
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
    except pymysql.err.IntegrityError as exc:
        db.rollback()
        code = exc.args[0] if exc.args else None
        logger.warning(
            "Application %s for job %s refused: %s", action, job_id, exc
        )
        return jsonify({
            "error": _tracking_error_detail(exc),
            "code": "tracking_failed",
        }), _ERROR_STATUS.get(code, 409)

    actual_status = application["status"]

    # Restate the status the user just produced. Dedupe is per (job, status),
    # so a repeated Apply on an already-applied job adds nothing new.
    if created:
        notify_application(db, user_id, job_id, actual_status)

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
