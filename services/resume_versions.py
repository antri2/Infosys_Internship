"""Saved resume versions: several independent resumes per candidate.

`tailored_resumes` holds the *generated* draft for a job and is unique on
(user_id, job_id). This module manages a different entity: the finished,
user-edited resumes a person keeps for different roles and different
applications. They need to be independent of one another, renameable, and
safe to delete individually.

Ownership rule
--------------
Every read and write is filtered by `user_id`, including the lookups by id.
A version belonging to someone else is therefore indistinguishable from one
that does not exist, so there is no path by which one user can open, overwrite
or delete another's saved resume. That is enforced here rather than in the
route so it cannot be forgotten by a new caller.
"""

from __future__ import annotations

import json
from datetime import datetime

from services import resume_document

MAX_TITLE = 200
MAX_COMPANY = 255
MAX_JOB_DESCRIPTION = 8000
MAX_INSTRUCTIONS = 5000


class VersionError(ValueError):
    """A problem the user can act on (bad title, unknown id, missing content)."""


def _clean(value, limit: int) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()[:limit]


def default_title(target_role: str, company: str = "") -> str:
    """A sensible starting name; the user can rename it afterwards."""
    role = _clean(target_role, 120) or "Resume"
    company = _clean(company, MAX_COMPANY)
    return f"{role} - {company}" if company else role


def _decode(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        decoded = json.loads(value)
    except (ValueError, TypeError):
        return fallback
    return decoded if isinstance(decoded, type(fallback)) else fallback


def _row_to_version(row: dict | None) -> dict | None:
    if not row:
        return None
    sections = _decode(row.get("sections"), [])
    return {
        "id": row["id"],
        "title": row["title"],
        "target_role": row.get("target_role") or "",
        "job_id": row.get("job_id"),
        "company": row.get("company") or "",
        "job_description": row.get("job_description") or "",
        "template_key": row.get("template_key") or "chronological",
        "custom_instructions": row.get("custom_instructions") or "",
        "sections": sections if isinstance(sections, list) else [],
        "content_text": row.get("content_text") or "",
        "source_fact_check": row.get("source_fact_check") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def list_versions(db, user_id: int, target_role: str | None = None) -> list[dict]:
    """The user's saved resumes, newest edit first."""
    query = (
        "SELECT * FROM resume_versions WHERE user_id = %s"
        + (" AND target_role = %s" if target_role else "")
        + " ORDER BY updated_at DESC, id DESC"
    )
    params = [user_id, target_role] if target_role else [user_id]
    with db.cursor() as cursor:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
    return [_row_to_version(row) for row in rows]


def get_version(db, user_id: int, version_id: int) -> dict | None:
    """One saved resume, or None. Never returns another user's version."""
    try:
        version_id = int(version_id)
    except (TypeError, ValueError):
        return None
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM resume_versions WHERE id = %s AND user_id = %s",
            (version_id, user_id),
        )
        row = cursor.fetchone()
    return _row_to_version(row)


def document_for(version: dict, candidate: dict | None = None) -> dict:
    """The canonical document for a saved version.

    A version always stores its own name and contact line, so it still renders
    correctly if the profile is edited later. Candidate data is used only for
    the headline fallback.
    """
    return resume_document.validate_sections(
        version.get("sections") or [],
        name=resume_document.name_of(version, candidate),
        contact=resume_document.contact_for(version),
        headline=version.get("target_role") or "",
    )


def _normalise_document(
    sections,
    candidate: dict | None,
    target_role: str,
) -> dict:
    """Validate submitted sections into the canonical document.

    The contact line is rebuilt from the profile rather than trusted from the
    form, so a submitted field cannot inject a different phone number or email
    into the rendered document.
    """
    contact = resume_document.contact_for(candidate)
    return resume_document.validate_sections(
        sections,
        name=resume_document.name_of({}, candidate),
        contact=contact,
        headline=target_role,
    )


def save_version(
    db,
    user_id: int,
    candidate: dict,
    *,
    sections,
    target_role: str = "",
    template_key: str = "chronological",
    custom_instructions: str = "",
    job_id: int | None = None,
    company: str = "",
    job_description: str = "",
    title: str = "",
    version_id: int | None = None,
    source_fact_check: str = "",
) -> dict:
    """Create a new saved resume, or update an existing one the user owns."""
    target_role = _clean(target_role, 120)
    template_key = _clean(template_key, 40) or "chronological"
    company = _clean(company, MAX_COMPANY)
    job_description = str(job_description or "").strip()[:MAX_JOB_DESCRIPTION]
    custom_instructions = str(custom_instructions or "").strip()[:MAX_INSTRUCTIONS]

    if job_id in ("", None):
        job_id = None
    else:
        try:
            job_id = int(job_id)
        except (TypeError, ValueError):
            raise VersionError("A valid job reference is required.")
        if job_id <= 0:
            job_id = None

    if company and job_id:
        # Only trust a company name the database already holds. Otherwise the
        # name is whatever the user typed, which is fine, but a mismatched
        # pair is not silently accepted as fact.
        with db.cursor() as cursor:
            cursor.execute("SELECT company FROM jobs WHERE job_id = %s", (job_id,))
            row = cursor.fetchone()
        if not row or not row.get("company"):
            raise VersionError("That job reference could not be found.")
        company = _clean(row["company"], MAX_COMPANY)

    document = _normalise_document(sections, candidate, target_role)
    if resume_document.is_empty(document):
        raise VersionError("There is nothing to save yet. Generate or write a resume first.")

    content_text = resume_document.render_text(document)

    with db.cursor() as cursor:
        if version_id:
            # An update must not silently rename the resume. When no title is
            # supplied the existing one is kept, rather than being regenerated
            # from the role and wiping a name the user chose.
            existing_title = None
            cursor.execute(
                "SELECT title FROM resume_versions WHERE id = %s AND user_id = %s",
                (int(version_id), user_id),
            )
            row = cursor.fetchone()
            if row:
                existing_title = row.get("title")

            title = _clean(title, MAX_TITLE) or existing_title \
                or default_title(target_role, company)

            # Scoped update: a version id that is not the user's own matches no
            # row, so it can never overwrite someone else's resume.
            cursor.execute(
                """
                UPDATE resume_versions
                SET title = %s, target_role = %s, job_id = %s, company = %s,
                    job_description = %s, template_key = %s,
                    custom_instructions = %s, sections = %s, content_text = %s
                WHERE id = %s AND user_id = %s
                """,
                (
                    title, target_role, job_id, company, job_description,
                    template_key, custom_instructions,
                    json.dumps(document["sections"]),
                    content_text, int(version_id), user_id,
                ),
            )
            if cursor.rowcount == 0:
                raise VersionError("That saved resume could not be found.")
            saved_id = int(version_id)
        else:
            cursor.execute(
                """
            INSERT INTO resume_versions
                (user_id, title, target_role, job_id, company,
                 job_description, template_key, custom_instructions,
                 sections, content_text, source_fact_check)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                _clean(title, MAX_TITLE) or default_title(target_role, company),
                target_role, job_id, company, job_description,
                template_key, custom_instructions,
                json.dumps(document["sections"]), content_text,
                _clean(source_fact_check, 30) or None,
            ),
        )
            saved_id = cursor.lastrowid
    db.commit()

    return get_version(db, user_id, saved_id)


def rename_version(db, user_id: int, version_id: int, title: str) -> dict:
    title = _clean(title, MAX_TITLE)
    if not title:
        raise VersionError("A saved resume needs a name.")
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE resume_versions SET title = %s WHERE id = %s AND user_id = %s",
            (title, int(version_id), user_id),
        )
        if cursor.rowcount == 0:
            raise VersionError("That saved resume could not be found.")
    db.commit()
    return get_version(db, user_id, int(version_id))


def delete_version(db, user_id: int, version_id: int) -> bool:
    """Delete one saved resume. Other versions and the profile are untouched."""
    with db.cursor() as cursor:
        cursor.execute(
            "DELETE FROM resume_versions WHERE id = %s AND user_id = %s",
            (int(version_id), user_id),
        )
        deleted = cursor.rowcount > 0
    db.commit()
    return deleted


def count_versions(db, user_id: int) -> int:
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS n FROM resume_versions WHERE user_id = %s", (user_id,)
        )
        return cursor.fetchone()["n"]


def format_timestamp(value) -> str:
    """A readable edit date, or an empty string when there isn't one."""
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %H:%M")
    return _clean(value, 40)