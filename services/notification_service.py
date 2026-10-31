"""Notification storage and generation for the header bell.

Every notification is derived from data CareerAI already has. Nothing here
invents a job, a deadline, or a date:

* **opportunity** -- a job the user can see right now on the Opportunities
  page. Emitted from the jobs the recommendation flow already returned.
* **skill_gap** -- the critical gaps of a stored Skill Gap report for a role
  the user actually ran against.
* **application** -- the existing ``applications`` row status. This only
  restates what is stored; it does not schedule or predict anything.

Duplicate suppression is structural rather than best-effort: every row carries
a ``dedupe_key`` and the table has ``UNIQUE KEY (user_id, dedupe_key)``.
Inserting the same event twice is therefore impossible at the database level,
not merely unlikely.
"""
from __future__ import annotations

import json
import logging


logger = logging.getLogger(__name__)

# Plain relative paths rather than url_for(). The service is called from routes,
# tests, and background-style helpers, and a notification link must never be the
# reason a request fails. These are the app's real routes.
OPPORTUNITIES_URL = "/opportunities/"
APPLICATIONS_URL = "/applications/"

CATEGORY_OPPORTUNITY = "opportunity"
CATEGORY_SKILL_GAP = "skill_gap"
CATEGORY_APPLICATION = "application"

# Only real values from the applications ENUM are described as notifications.
_APPLICATION_MESSAGES = {
    "saved": "You saved this job to your applications. Review it and apply when you are ready.",
    "applied": "You applied to this job.",
    "interview": "This application moved to interview stage.",
    "under_review": "This application is under review.",
    "rejected": "This application was marked rejected.",
}

# An opportunity is only "new" if it is well matched to the profile, so the
# bell does not fill up with listings the user never wanted.
NEW_OPPORTUNITY_MIN_FIT = 70
MAX_NOTIFICATIONS = 30


def _clean(value, limit: int = 255) -> str:
    return " ".join(str(value or "").split())[:limit]


# -------------------------------------------------------------------------- #
# Storage
# -------------------------------------------------------------------------- #


def add_notification(
    db,
    user_id: int,
    category: str,
    title: str,
    body: str = "",
    link: str = "",
    dedupe_key: str = "",
) -> bool:
    """Insert one notification. Returns False when it already existed.

    A duplicate is a normal outcome, not an error, so the unique-key collision
    is handled quietly and never surfaced to the user.
    """
    title = _clean(title)
    dedupe_key = _clean(dedupe_key, 255)
    if not title or not dedupe_key:
        return False

    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO notifications
                    (user_id, category, title, body, link, dedupe_key)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE id = id
                """,
                (
                    user_id,
                    category,
                    title,
                    _clean(body, 1000),
                    _clean(link, 500),
                    dedupe_key,
                ),
            )
        db.commit()
        return cursor.rowcount == 1
    except Exception:
        # A notification is never important enough to break the page that
        # produced it, so the failure is logged and swallowed.
        db.rollback()
        logger.exception("Could not store a %s notification", category)
        return False


def list_notifications(db, user_id: int, limit: int = MAX_NOTIFICATIONS) -> list[dict]:
    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, category, title, body, link, is_read, created_at
            FROM notifications
            WHERE user_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (user_id, int(limit)),
        )
        return list(cursor.fetchall())


def unread_count(db, user_id: int) -> int:
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS total FROM notifications "
            "WHERE user_id = %s AND is_read = 0",
            (user_id,),
        )
        row = cursor.fetchone()
    return int((row or {}).get("total") or 0)


def mark_all_read(db, user_id: int) -> int:
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE notifications SET is_read = 1, read_at = CURRENT_TIMESTAMP "
            "WHERE user_id = %s AND is_read = 0",
            (user_id,),
        )
        changed = cursor.rowcount
    db.commit()
    return changed


def mark_read(db, user_id: int, notification_id: int) -> bool:
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE notifications SET is_read = 1, read_at = CURRENT_TIMESTAMP "
            "WHERE id = %s AND user_id = %s AND is_read = 0",
            (notification_id, user_id),
        )
        changed = cursor.rowcount
    db.commit()
    return changed > 0


# -------------------------------------------------------------------------- #
# Generation from existing data
# -------------------------------------------------------------------------- #


def notify_new_opportunities(db, user_id: int, jobs: list[dict]) -> int:
    """Notify about well-matched jobs the recommendation flow just returned.

    Dedupe is per job id, so a job is announced once no matter how often the
    user searches or reopens the page.
    """
    created = 0
    for job in jobs or []:
        if job.get("application_status"):
            continue  # already tracked; the application notice covers it
        if not job.get("match_available") or int(job.get("match_percent") or 0) < NEW_OPPORTUNITY_MIN_FIT:
            continue
        job_id = str(job.get("job_id") or "").strip()
        title = _clean(job.get("title"))
        if not job_id or not title:
            continue
        company = _clean(job.get("company")) or "an employer"
        if add_notification(
            db,
            user_id,
            CATEGORY_OPPORTUNITY,
            f"New opportunity: {title}",
            body=(
                f"{company} - {job.get('match_percent')}% Profile Skill Fit"
                f" based on your profile skills."
            ),
            link=OPPORTUNITIES_URL,
            dedupe_key=f"opportunity:{job_id}",
        ):
            created += 1
    return created


def notify_skill_gap(db, user_id: int, job_id: int, report: dict, role: str = "") -> int:
    """Notify about the critical gaps of a stored Skill Gap report.

    The body is built only from skills the report itself recorded as missing,
    so nothing about the role or the gaps is invented here.
    """
    if not isinstance(report, dict):
        return 0

    gaps = report.get("critical_gaps") or []
    names: list[str] = []
    for entry in gaps:
        if isinstance(entry, dict):
            skill = _clean(entry.get("skill"), 80)
        else:
            skill = _clean(entry, 80)
        if skill and skill not in names:
            names.append(skill)
    if not names:
        return 0

    role_label = _clean(role) or "this role"
    shown = ", ".join(names[:5])
    extra = f" and {len(names) - 5} more" if len(names) > 5 else ""
    return 1 if add_notification(
        db,
        user_id,
        CATEGORY_SKILL_GAP,
        f"Skill gap for {role_label}",
        body=f"Your stored Skill Gap report lists these as missing: {shown}{extra}.",
        link=(
            f"/skill-gap/?job_id={job_id}" if job_id else "/skill-gap/"
        ),
        dedupe_key=f"skill_gap:{job_id}",
    ) else 0


def _job_label(db, job_id: int) -> str:
    """Read the stored job title so the notification names a real job."""
    try:
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT title, company FROM jobs WHERE job_id = %s", (job_id,)
            )
            row = cursor.fetchone()
    except Exception:
        logger.exception("Could not read job %s for a notification", job_id)
        return ""
    if not row:
        return ""
    title = _clean(row.get("title"))
    company = _clean(row.get("company"))
    return f"{title} at {company}" if company else title


def notify_application(db, user_id: int, job_id: int, status: str) -> int:
    """Notify about an application the user actually saved or applied to.

    This only restates the stored ``applications`` row. It creates no
    reminder schedule and no deadline, because the schema has no such field.
    """
    message = _APPLICATION_MESSAGES.get(str(status or ""))
    if not message:
        return 0

    label = _job_label(db, job_id)
    if not label:
        return 0
    return 1 if add_notification(
        db,
        user_id,
        CATEGORY_APPLICATION,
        f"Application updated: {label}",
        body=message,
        link=APPLICATIONS_URL,
        dedupe_key=f"application:{job_id}:{status}",
    ) else 0


def notify_existing_skill_gaps(db, user_id: int) -> int:
    """Build skill-gap notices from reports the user has already generated."""
    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT job_id, critical_gaps
                FROM skill_gap_reports
                WHERE user_id = %s
                ORDER BY updated_at DESC, id DESC
                LIMIT 10
                """,
                (user_id,),
            )
            reports = list(cursor.fetchall())
    except Exception:
        logger.exception("Could not read stored Skill Gap reports")
        return 0

    created = 0
    for row in reports:
        raw = row.get("critical_gaps")
        if not raw:
            continue
        try:
            critical = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except (TypeError, ValueError):
            continue
        job_id = row.get("job_id")
        report = {"critical_gaps": critical or []}
        label = _job_label(db, job_id)
        # The stored report is keyed by job, so the job's own title is the role
        # the user actually analysed.
        role = label.split(" at ")[0] if label else ""
        if notify_skill_gap(db, user_id, job_id, report, role=role):
            created += 1
    return created
