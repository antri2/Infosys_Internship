"""Authenticated Cover Letter page and JSON workflow endpoints.

Cover letters are generic by default.  A role-level target resolves a
representative synchronized job internally, while exact job IDs remain an
optional, backward-compatible API context and are never exposed in the form.
"""
from __future__ import annotations

import logging
import re

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from database.db import get_db
from services.agent_orchestrator import AgentOrchestrator
from services.context_builder import get_job_context
from services.cover_letter_agent import MAX_CONTEXT_LENGTH, CoverLetterNotFound
from services.role_catalog import canonical_role, job_role, role_options


cover_letter_bp = Blueprint("cover_letter", __name__, url_prefix="/cover-letter")
logger = logging.getLogger(__name__)


class JobNotFound(ValueError):
    """A requested synchronized job does not exist."""


def _require_login() -> bool:
    return "user_id" in session


def _payload() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else request.form


def _parse_id(value, label: str) -> int:
    if isinstance(value, bool) or (
        isinstance(value, float) and not value.is_integer()
    ):
        raise ValueError(f"A valid {label} is required.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"A valid {label} is required.") from exc
    if parsed <= 0:
        raise ValueError(f"A valid {label} is required.")
    return parsed


def _job_id(payload: dict, required: bool = False):
    value = payload.get("job_id")
    if value in (None, ""):
        if required:
            raise ValueError("A valid job_id is required.")
        return None
    return _parse_id(value, "job_id")


def _custom_details(payload: dict) -> str:
    value = payload.get(
        "extra_context",
        payload.get("custom_details", payload.get("custom_context", "")),
    )
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError("Custom details must be text.")
    value = value.strip()
    if len(value) > MAX_CONTEXT_LENGTH:
        raise ValueError(f"Custom details must be {MAX_CONTEXT_LENGTH} characters or fewer.")
    return value


def _target_role(payload: dict) -> str:
    """Return a role-level target without exposing a job ID in the UI."""
    value = payload.get("target_role", payload.get("role", ""))
    if value == "custom":
        value = payload.get("custom_role", "")
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError("Target role must be text.")
    value = value.strip()
    if len(value) > 120:
        raise ValueError("Target role must be 120 characters or fewer.")
    return canonical_role(value) or value


def _append_role_context(extra_context: str, role: str) -> str:
    """Add an off-catalog role to generic custom context when needed."""
    if not role:
        return extra_context
    if re.search(r"(?im)^\s*(?:role|specific role|target role|position|job title)\s*:", extra_context):
        return extra_context
    return f"{extra_context}\nRole: {role}".strip() if extra_context else f"Role: {role}"


def _is_generic_request(payload: dict, extra_context: str = "") -> bool:
    """Accept an explicit generic marker, role target, or custom context."""
    if extra_context or _target_role(payload):
        return True
    marker = payload.get("generic", payload.get("is_generic", False))
    if isinstance(marker, str):
        return marker.strip().casefold() in {"1", "true", "yes", "on"}
    return marker is True or marker == 1


def _resolve_optional_job(db, payload: dict):
    """Resolve ONLY a job the user explicitly selected for this letter.

    A role on its own is not a job. Resolving a "representative" posting from
    the dataset for a bare role used to hand the agent a real employer name and
    job description that the user never supplied, which made the letter claim
    to be addressed to that company. Role-only requests now resolve to no job
    at all and fall through to the general role mode.
    """
    job_id = _job_id(payload)
    if job_id is None:
        return None, None

    job = get_job_context(db, job_id)
    if job is None:
        raise JobNotFound(f"Job {job_id} was not found.")
    return job_id, job


def _letter_id(payload: dict, required: bool = False):
    value = payload.get("letter_id", payload.get("id"))
    if value in (None, ""):
        if required:
            raise ValueError("A valid letter_id is required.")
        return None
    return _parse_id(value, "letter_id")


def _edited_content(payload: dict) -> str:
    value = payload.get(
        "content",
        payload.get(
            "cover_letter",
            payload.get("edited_content", payload.get("cover_letter_content", payload.get("letter"))),
        ),
    )
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Cover letter content is required.")
    if len(value) > 20000:
        raise ValueError("Cover letter content is too long.")
    # Do not strip or normalize: Save must persist exactly what the user edited.
    return value


def _job_json(job: dict | None) -> dict | None:
    if not job:
        return None
    return {
        "job_id": int(job["job_id"]),
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
        "job_type": job.get("job_type"),
    }


def _letter_json(row: dict) -> dict:
    return {
        "id": int(row["id"]),
        "letter_id": int(row["id"]),
        "job_id": row.get("job_id"),
        "content": row.get("content") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        # The role this letter was written for, and the heading that identifies
        # it. Both come from the same helper the saved list uses, so the list
        # and the reading view never disagree about what a letter is.
        "target_role": row.get("target_role") or "",
        "heading": letter_heading(row),
        "job": {
            "job_id": row.get("job_id"),
            "title": row.get("job_title"),
            "company": row.get("job_company"),
            "location": row.get("job_location"),
        } if row.get("job_id") is not None else None,
    }


def _error(message: str, status: int):
    return jsonify({"success": False, "error": message}), status



def letter_heading(letter: dict | None) -> str:
    """The heading for a saved letter, which must name the target role.

    The brief asks for the ambiguous "Generic Cover Letter" to go. A letter
    attached to a job is named by that job. A role-specific generic letter is
    named by its stored role. Only a letter with neither -- an older row saved
    before the role was recorded -- falls back to the old wording, and it says
    so explicitly rather than pretending to know.
    """
    letter = letter if isinstance(letter, dict) else {}
    job_title = str(letter.get("job_title") or "").strip()
    if job_title:
        company = str(letter.get("job_company") or "").strip()
        return f"Cover Letter / {job_title}" + (f" at {company}" if company else "")

    role = str(letter.get("target_role") or "").strip()
    if role:
        return f"Generic Cover Letter / {role}"

    return "Generic Cover Letter (no role recorded)"


@cover_letter_bp.route("/", methods=["GET"])
def view():
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    orchestrator = AgentOrchestrator(db, session["user_id"])
    error = None
    selected_job = None
    selected_job_id = None
    selected_letter = None
    selected_role = ""

    raw_letter_id = request.args.get("letter_id")
    if raw_letter_id:
        try:
            selected_letter = orchestrator.load_cover_letter(
                _parse_id(raw_letter_id, "letter_id")
            )
        except (ValueError, CoverLetterNotFound):
            error = "The selected saved letter could not be loaded."
        if selected_letter:
            selected_job_id = selected_letter.get("job_id")

    raw_job_id = request.args.get("job_id")
    if raw_job_id and selected_letter is None:
        try:
            selected_job_id = _parse_id(raw_job_id, "job_id")
        except ValueError:
            error = "A valid target job is required."

    # A normal page load stays generic. A role query only sets the role; it
    # never attaches a job, because that would silently supply the employer and
    # job description to the letter the user is about to generate.
    if selected_job_id:
        try:
            selected_job = get_job_context(db, int(selected_job_id))
            if selected_job is None:
                error = f"Job {selected_job_id} was not found."
            else:
                selected_role = job_role(selected_job) or selected_role
        except Exception:
            logger.exception("Could not load selected Cover Letter job")
            error = "The selected job could not be loaded right now."
    else:
        raw_role = request.args.get("target_role", "")
        if raw_role:
            try:
                selected_role = _target_role({"target_role": raw_role})
            except ValueError:
                error = "A valid target role is required."

    try:
        letters = orchestrator.list_cover_letters()
    except Exception:
        logger.exception("Could not load saved Cover Letters")
        letters = []

    return render_template(
        "cover_letter.html",
        active_page="cover_letter",
        role_options=role_options(),
        selected_role=selected_role,
        selected_job_id=selected_job_id,
        selected_job=selected_job,
        selected_letter=selected_letter,
        selected_letter_heading=letter_heading(selected_letter),
        letters=letters,
        letter_headings={row["id"]: letter_heading(row) for row in letters},
        error=error,
    )


@cover_letter_bp.route("/generate", methods=["POST"])
@cover_letter_bp.route("/generate-cover-letter", methods=["POST"])
def generate():
    if not _require_login():
        return _error("Not logged in.", 401)

    payload = _payload()
    try:
        extra_context = _custom_details(payload)
        target_role = _target_role(payload)
        job_id, job = _resolve_optional_job(get_db(), payload)
        if target_role and job_id is None:
            extra_context = _append_role_context(extra_context, target_role)
        if job_id is None and not _is_generic_request(payload, extra_context):
            # Keep the legacy bare API request invalid; the page explicitly
            # sends ``generic`` so an empty form is still generic by default.
            raise ValueError("Select a target or provide custom details.")
    except JobNotFound as exc:
        return _error(str(exc), 404)
    except ValueError as exc:
        return _error(str(exc), 400)

    try:
        result = AgentOrchestrator(get_db(), session["user_id"]).generate_cover_letter(
            job_id, extra_context
        )
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        logger.exception("Cover Letter generation failed for job %s", job_id)
        return _error("The cover letter could not be generated right now.", 503)

    return jsonify({
        "success": True,
        "id": None,
        "letter_id": None,
        "job_id": job_id,
        "job": _job_json(job),
        "cover_letter": result["cover_letter"],
        "content": result["cover_letter"],
        "highlighted_verified_facts": result.get("highlighted_verified_facts", []),
        "flagged_claims": result.get("flagged_claims", []),
        "used_fallback": result.get("used_fallback", False),
        "validation_status": result.get("validation_status", "validated"),
    })


@cover_letter_bp.route("/save", methods=["POST"])
@cover_letter_bp.route("/save-letter", methods=["POST"])
@cover_letter_bp.route("/update", methods=["POST"])
def save():
    if not _require_login():
        return _error("Not logged in.", 401)

    payload = _payload()
    try:
        content = _edited_content(payload)
        letter_id = _letter_id(payload)
        job_id = _job_id(payload)
        # The role the user selected, stored so the saved list can identify a
        # generic letter by role instead of an ambiguous "Generic Cover Letter".
        target_role = _target_role(payload)
    except ValueError as exc:
        return _error(str(exc), 400)

    try:
        result = AgentOrchestrator(get_db(), session["user_id"]).save_cover_letter(
            content, job_id, letter_id, target_role=target_role
        )
    except CoverLetterNotFound:
        return _error("The saved cover letter was not found.", 404)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        logger.exception("Cover Letter save failed")
        return _error("The cover letter could not be saved right now.", 503)

    return jsonify({
        "success": True,
        "id": result["id"],
        "letter_id": result["letter_id"],
        "job_id": result["job_id"],
        "job": result["job"],
        "target_role": result.get("target_role", ""),
        "content": result["content"],
        "saved": True,
    })


@cover_letter_bp.route("/load/<int:letter_id>", methods=["GET"])
@cover_letter_bp.route("/load", methods=["GET", "POST"])
@cover_letter_bp.route("/load-letter", methods=["GET", "POST"])
def load(letter_id: int | None = None):
    if not _require_login():
        return _error("Not logged in.", 401)

    payload = _payload() if request.method == "POST" else {
        "letter_id": request.args.get("letter_id")
    }
    try:
        normalized_id = letter_id if letter_id is not None else _letter_id(payload, required=True)
        row = AgentOrchestrator(get_db(), session["user_id"]).load_cover_letter(
            normalized_id
        )
    except CoverLetterNotFound:
        return _error("The saved cover letter was not found.", 404)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        logger.exception("Cover Letter load failed")
        return _error("The saved cover letter could not be loaded right now.", 503)

    return jsonify({"success": True, "letter": _letter_json(row), **_letter_json(row)})


@cover_letter_bp.route("/regenerate", methods=["POST"])
@cover_letter_bp.route("/regenerate-letter", methods=["POST"])
def regenerate():
    if not _require_login():
        return _error("Not logged in.", 401)

    payload = _payload()
    try:
        letter_id = _letter_id(payload)
        extra_context = _custom_details(payload)
        target_role = _target_role(payload)
        explicit_job_id = _job_id(payload)
        resolved_job_id, _ = _resolve_optional_job(get_db(), payload)
        job_id = resolved_job_id
        if target_role and (
            job_id is None or (letter_id is not None and explicit_job_id is None)
        ):
            extra_context = _append_role_context(extra_context, target_role)
        if letter_id is not None and explicit_job_id is None:
            # A saved letter supplies its own job context.  A newly selected
            # role should not be forced through the saved-row ownership check.
            job_id = None
        if letter_id is None and job_id is None and not _is_generic_request(
            payload, extra_context
        ):
            raise ValueError("Select a target or provide custom details.")
    except JobNotFound as exc:
        return _error(str(exc), 404)
    except ValueError as exc:
        return _error(str(exc), 400)

    db = get_db()
    try:
        orchestrator = AgentOrchestrator(db, session["user_id"])
        if letter_id is None:
            result = orchestrator.generate_cover_letter(job_id, extra_context)
        else:
            # Only reuse the saved letter's job when the user has not asked for
            # a role-only/general letter; otherwise the previous company and job
            # description would leak into the new draft.
            inherit_saved_job = explicit_job_id is None and not target_role and not _is_generic_request(
                payload, extra_context
            )
            result = orchestrator.regenerate_cover_letter(
                letter_id, job_id, extra_context, inherit_saved_job=inherit_saved_job
            )
    except CoverLetterNotFound:
        return _error("The saved cover letter was not found.", 404)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        logger.exception("Cover Letter regeneration failed")
        return _error("The cover letter could not be regenerated right now.", 503)

    return jsonify({
        "success": True,
        "id": result.get("id"),
        "letter_id": result.get("letter_id"),
        "regenerated_from_letter_id": result.get("regenerated_from_letter_id"),
        "job_id": result["job_id"],
        "job": result.get("job"),
        "cover_letter": result["cover_letter"],
        "content": result["cover_letter"],
        "highlighted_verified_facts": result.get("highlighted_verified_facts", []),
        "flagged_claims": result.get("flagged_claims", []),
        "used_fallback": result.get("used_fallback", False),
        "validation_status": result.get("validation_status", "validated"),
    })
