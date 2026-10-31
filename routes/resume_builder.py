"""Resume Builder routes: generation, section editing, saved versions, downloads.

The flow this module supports, end to end:

  generate  -> a tailored draft (unchanged AgentOrchestrator path)
  edit      -> per-section changes held in a hidden JSON field
  save      -> an independent saved version in resume_versions
  download  -> PDF/TXT rendered from that same structured value

The important invariant is that the preview, the TXT file and the PDF are all
rendered from one document dict, so a user can never download something
different from what they approved.

Ownership: every version read/write is scoped by the session's user_id, and the
scoping lives in services.resume_versions rather than here so a future caller
cannot forget it.
"""

import json
import logging

from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from database.db import get_db
from services import resume_document, resume_versions
from services.agent_orchestrator import AgentOrchestrator
from services.context_builder import get_candidate_context, get_job_context
from services.resume_agent import TEMPLATE_ORDER, TEMPLATES, normalize_custom_instructions
from services.role_catalog import find_role_job, job_role


resume_builder_bp = Blueprint(
    "resume_builder", __name__, url_prefix="/resume-builder"
)
logger = logging.getLogger(__name__)


# Resume Builder uses its own display labels so the page can show the familiar
# "ML Engineer" wording without changing the role catalogs used elsewhere.
RESUME_ROLE_OPTIONS = [
    "AI Engineer",
    "ML Engineer",
    "Data Scientist",
    "Software Engineer",
    "Data Analyst",
    "GenAI Engineer",
    "Full Stack Developer",
    "Frontend Developer",
    "Backend Developer",
    "DevOps Engineer",
    "Product Analyst",
    "Business Analyst",
]


def _require_login():
    return "user_id" in session


def _wants_json() -> bool:
    """Whether this caller wants a JSON body rather than a re-rendered page.

    `request.is_json` is the wrong test here: it describes the *request* body,
    and the browser sends form-encoded data while asking for JSON back via
    Accept / X-Requested-With. Checking only is_json made the editor's save and
    download calls silently receive an HTML page instead of the JSON they parse.
    """
    if request.is_json:
        return True
    if request.headers.get("X-Requested-With") == "fetch":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept


def _payload():
    """Request values as one mapping, whichever way they arrived.

    A GET carries its parameters in the query string, not in request.form, so
    the download links on the saved-resume list (?version_id=...) would resolve
    to nothing without this. Form values win over query values on the rare
    request that has both, because the body is the more specific intent.
    """
    json_payload = request.get_json(silent=True)
    if isinstance(json_payload, dict):
        return json_payload
    merged = dict(request.args)
    merged.update(request.form.to_dict(flat=True))
    return merged


def _display_role(value: str | None) -> str:
    value = str(value or "").strip()
    return "ML Engineer" if value == "Machine Learning Engineer" else value


def _normalise_role(value: str | None) -> str:
    value = str(value or "").strip()
    folded = value.casefold()
    for option in RESUME_ROLE_OPTIONS:
        if option.casefold() == folded:
            return option
    return ""


def _lookup_role(value: str) -> str:
    return "Machine Learning Engineer" if value == "ML Engineer" else value


def _resolve_target(db, payload):
    """Resolve a role internally without exposing a job id to the page."""
    raw_job_id = payload.get("job_id")
    if raw_job_id not in (None, ""):
        try:
            job_id = int(raw_job_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("A valid target job is required.") from exc
        if job_id <= 0:
            raise ValueError("A valid target job is required.")
        job = get_job_context(db, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} was not found.")
        role = _normalise_role(payload.get("target_role")) or _display_role(job_role(job))
        return role, job

    role = _normalise_role(payload.get("target_role"))
    if not role:
        return "", None
    job = find_role_job(db, _lookup_role(role))
    if job is None:
        raise ValueError(f"No synchronized role context was found for {role}.")
    return role, job


def _role_requirements(job):
    if not job:
        return {"required": "", "preferred": ""}
    return {
        "required": job.get("required_skills") or "",
        "preferred": job.get("preferred_skills") or "",
    }


def _ordered_templates() -> dict:
    """Templates in their curated display order."""
    ordered = {key: TEMPLATES[key] for key in TEMPLATE_ORDER if key in TEMPLATES}
    for key, value in TEMPLATES.items():
        ordered.setdefault(key, value)
    return ordered


def _section_order(template_key: str) -> list[str] | None:
    """The selected template's section order, for the document builder.

    Passed in rather than imported inside the service so resume_document stays
    independent of the agent, and so the preview, TXT and PDF all follow the
    template the user actually chose.
    """
    template = TEMPLATES.get(template_key or "")
    return list(template["section_order"]) if template else None


def _build_document(db, user_id, *, result=None, version=None, role="", sections=None,
                    template_key=""):
    """Resolve the document the page should show, whichever source it came from.

    Precedence: an explicitly opened saved version, then the current draft in
    session storage, then a freshly generated result. A version wins so that
    opening a saved resume does not silently show the last generated draft.
    """
    candidate = get_candidate_context(db, user_id)

    if version is not None:
        return resume_versions.document_for(version, candidate), candidate

    if sections is not None:
        document = resume_document.validate_sections(
            sections,
            name=resume_document.name_of({}, candidate),
            contact=resume_document.contact_for(candidate),
            headline=role or "",
        )
        if not resume_document.is_empty(document):
            return document, candidate

    if result:
        return resume_document.sections_from_tailored(
            result, candidate, _section_order(template_key)
        ), candidate

    return {
        "name": resume_document.name_of({}, candidate),
        "contact": resume_document.contact_for(candidate),
        "headline": "",
        "sections": [],
    }, candidate


def _render_builder(
    db,
    user_id,
    role="",
    template_key="chronological",
    result=None,
    error=None,
    custom_instructions="",
    saved=False,
    profile_updates=None,
    version=None,
    notice=None,
    document=None,
    draft_sections=None,
):
    role_job = None
    skill_gap = None

    # Role context for the header strip.
    if role and not result:
        try:
            role, role_job = _resolve_target(db, {"target_role": role})
        except ValueError as exc:
            error = error or str(exc)
            role_job = None

    if role_job and not result:
        try:
            skill_gap = AgentOrchestrator(db, user_id).get_cached_skill_gap(
                int(role_job["job_id"])
            )
        except Exception:
            logger.exception("Could not load Resume Builder Skill Gap context")
    if result is not None:
        skill_gap = result.get("skill_gap", skill_gap)

    if document is None:
        document, candidate = _build_document(
            db, user_id, result=result, version=version, role=role,
            sections=draft_sections, template_key=template_key,
        )
    else:
        candidate = get_candidate_context(db, user_id)

    ordered_templates = _ordered_templates()
    resolved_template = template_key if template_key in ordered_templates else "chronological"
    if version and version.get("template_key") in ordered_templates:
        resolved_template = version["template_key"]
        template_key = resolved_template

    # A saved version keeps the section order the user left it in, because
    # document_for() returns its stored sections verbatim rather than
    # re-deriving them from the template.

    return render_template(
        "resume_builder.html",
        active_page="resume_builder",
        role_options=RESUME_ROLE_OPTIONS,
        selected_role=role or (version or {}).get("target_role", ""),
        selected_template=resolved_template,
        templates=ordered_templates,
        selected_template_description=ordered_templates[resolved_template]["description"],
        custom_instructions=custom_instructions or (version or {}).get("custom_instructions", ""),
        candidate=candidate,
        result=result,
        role_requirements=_role_requirements(role_job),
        skill_gap=skill_gap,
        error=error,
        notice=notice,
        saved=saved,
        profile_updates=profile_updates or {},
        versions=resume_versions.list_versions(db, user_id),
        open_version=version,
        document=document,
        document_json=json.dumps(document, ensure_ascii=False),
        document_html=resume_document.render_html(document),
        document_text=resume_document.render_text(document),
        section_kinds=resume_document.DEFAULT_SECTION_TITLES,
    )


def _requested_version(db, user_id):
    """The saved resume the user asked to open, if any."""
    raw = request.args.get("version") or request.form.get("version_id")
    if raw in (None, ""):
        return None
    try:
        version_id = int(raw)
    except (TypeError, ValueError):
        return None
    version = resume_versions.get_version(db, user_id, version_id)
    if version is None:
        flash("That saved resume could not be found.")
    return version


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

@resume_builder_bp.route("/", methods=["GET"])
def view():
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    user_id = session["user_id"]
    role = _normalise_role(request.args.get("target_role"))
    template_key = request.args.get("template", "chronological")
    if template_key not in TEMPLATES:
        template_key = "chronological"
    result = None
    error = None
    role_job = None
    custom_instructions = ""

    version = _requested_version(db, user_id)

    try:
        # ``job_id`` remains accepted only as a backwards-compatible API/query
        # path. It is never rendered in the normal Resume Builder UI.
        role, role_job = _resolve_target(
            db,
            {
                "target_role": request.args.get("target_role", ""),
                "job_id": request.args.get("job_id"),
            },
        )
    except ValueError as exc:
        error = str(exc)

    # A saved version is shown instead of the generated draft when one is open.
    if role_job and version is None:
        try:
            result = AgentOrchestrator(db, user_id).get_cached_resume_builder(
                int(role_job["job_id"]),
                template_key,
                require_matching_instructions=False,
            )
            if result:
                custom_instructions = result.get("custom_instructions", "")
        except Exception:
            logger.exception("Could not load Resume Builder data")
            error = error or "Resume Builder data could not be loaded right now."

    return _render_builder(
        db,
        user_id,
        role=role,
        template_key=template_key,
        result=result,
        error=error,
        custom_instructions=custom_instructions,
        version=version,
    )


# --------------------------------------------------------------------------
# Generation (unchanged behaviour, existing endpoints preserved)
# --------------------------------------------------------------------------

@resume_builder_bp.route("/generate", methods=["POST"])
def generate():
    """Generate a role-level resume through AgentOrchestrator."""
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    payload = _payload()
    template_key = payload.get("template", "chronological")
    if template_key not in TEMPLATES:
        template_key = "chronological"
    try:
        custom_instructions = normalize_custom_instructions(
            payload.get("custom_instructions", payload.get("instructions", ""))
        )
        role, job = _resolve_target(db, payload)
        if not role or job is None:
            raise ValueError("Select a target role first.")
        legacy_request = payload.get("job_id") not in (None, "")
        result = AgentOrchestrator(db, session["user_id"]).run_resume_builder(
            int(job["job_id"]),
            template=template_key,
            force_refresh=bool(custom_instructions),
            custom_instructions=custom_instructions,
            target_role=role,
        )
        if legacy_request:
            # Preserve the established legacy page wording for old API callers;
            # the normal role-based flow still reports a fresh generation.
            result["from_cache"] = True
    except ValueError as exc:
        return _render_builder(
            db,
            session["user_id"],
            role=_normalise_role(payload.get("target_role")),
            template_key=template_key,
            custom_instructions=payload.get("custom_instructions", ""),
            error=str(exc),
        )
    except Exception:
        logger.exception("Resume generation failed")
        return _render_builder(
            db,
            session["user_id"],
            role=_normalise_role(payload.get("target_role")),
            template_key=template_key,
            custom_instructions=payload.get("custom_instructions", ""),
            error="The tailored resume could not be generated right now.",
        )

    return _render_builder(
        db,
        session["user_id"],
        role=role,
        template_key=template_key,
        result=result,
        custom_instructions=custom_instructions,
        notice="Resume generated. Review each section, then save it.",
    )


@resume_builder_bp.route("/regenerate", methods=["POST"])
def regenerate():
    """Explicitly create a fresh draft; this is never automatic after an edit."""
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    payload = _payload()
    template_key = payload.get("template", "chronological")
    if template_key not in TEMPLATES:
        template_key = "chronological"
    try:
        custom_instructions = normalize_custom_instructions(
            payload.get("custom_instructions", payload.get("instructions", ""))
        )
        role, job = _resolve_target(db, payload)
        if not role or job is None:
            raise ValueError("Select a target role first.")
        result = AgentOrchestrator(db, session["user_id"]).run_resume_builder(
            int(job["job_id"]),
            template=template_key,
            force_refresh=True,
            custom_instructions=custom_instructions,
            target_role=role,
        )
    except ValueError as exc:
        return _render_builder(
            db,
            session["user_id"],
            role=_normalise_role(payload.get("target_role")),
            template_key=template_key,
            custom_instructions=payload.get("custom_instructions", ""),
            error=str(exc),
        )
    except Exception:
        logger.exception("Resume regeneration failed")
        return _render_builder(
            db,
            session["user_id"],
            role=_normalise_role(payload.get("target_role")),
            template_key=template_key,
            custom_instructions=payload.get("custom_instructions", ""),
            error="The tailored resume could not be regenerated right now.",
        )

    return _render_builder(
        db,
        session["user_id"],
        role=role,
        template_key=template_key,
        result=result,
        custom_instructions=custom_instructions,
        notice="A fresh draft was generated. Your saved resumes were not changed.",
    )


@resume_builder_bp.route("/save", methods=["POST"])
@resume_builder_bp.route("/update", methods=["POST"])
def save():
    """Save the exact user-approved text without invoking the LLM.

    Preserved endpoint and behaviour: this records the draft in
    tailored_resumes and applies only explicitly requested profile additions.
    Saving an independent version is the separate /versions/save route.
    """
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    payload = _payload()
    template_key = payload.get("template", "chronological")
    if template_key not in TEMPLATES:
        template_key = "chronological"
    try:
        role, job = _resolve_target(db, payload)
        if not role or job is None:
            raise ValueError("Select a target role first.")
        custom_instructions = normalize_custom_instructions(
            payload.get("custom_instructions", payload.get("instructions", ""))
        )
        resume_text = payload.get("resume_text", payload.get("content", ""))
        if not isinstance(resume_text, str) or not resume_text.strip():
            raise ValueError("Generate or enter a resume before saving.")
        result = AgentOrchestrator(db, session["user_id"]).save_resume_builder(
            int(job["job_id"]),
            resume_text,
            template=template_key,
            custom_instructions=custom_instructions,
            target_role=role,
        )
    except ValueError as exc:
        if _wants_json():
            return jsonify({"success": False, "error": str(exc)}), 400
        return _render_builder(
            db,
            session["user_id"],
            role=_normalise_role(payload.get("target_role")),
            template_key=template_key,
            custom_instructions=payload.get("custom_instructions", ""),
            error=str(exc),
        )
    except Exception:
        logger.exception("Resume save failed")
        if _wants_json():
            return jsonify({"success": False, "error": "The resume could not be saved right now."}), 503
        return _render_builder(
            db,
            session["user_id"],
            role=_normalise_role(payload.get("target_role")),
            template_key=template_key,
            custom_instructions=payload.get("custom_instructions", ""),
            error="The resume could not be saved right now.",
        )

    result["saved"] = True
    if _wants_json():
        return jsonify({
            "success": True,
            "resume_text": result["resume_text"],
            "template": result.get("template", template_key),
            "profile_updates": result.get("profile_updates", {}),
        })
    return _render_builder(
        db,
        session["user_id"],
        role=role,
        template_key=template_key,
        result=result,
        custom_instructions=custom_instructions,
        saved=True,
        profile_updates=result.get("profile_updates", {}),
    )


# --------------------------------------------------------------------------
# Saved versions
# --------------------------------------------------------------------------

def _submitted_sections(payload):
    """Pull the edited document out of a request.

    Accepts the JSON string the editor submits, and falls back to the stored
    version's sections when the request only names a version. Returns None when
    neither is usable, so the caller can decide what to do.
    """
    raw = payload.get("sections")
    if isinstance(raw, (list, tuple)):
        return list(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            decoded = json.loads(raw)
        except (ValueError, TypeError):
            raise resume_versions.VersionError(
                "The resume content could not be read. Please try again."
            )
        if isinstance(decoded, dict):
            # The editor posts the whole document; keep only its sections.
            return decoded.get("sections") or []
        if isinstance(decoded, list):
            return decoded
    return None


def _version_target(payload):
    """Optional job association supplied with the version form."""
    raw = payload.get("job_id")
    if raw in (None, ""):
        return None, ""
    try:
        job_id = int(raw)
    except (TypeError, ValueError):
        raise resume_versions.VersionError("A valid job reference is required.")
    if job_id <= 0:
        return None, ""
    db = get_db()
    job = get_job_context(db, job_id)
    if job is None:
        raise resume_versions.VersionError(
            "That job could not be found, so it was not attached to this resume."
        )
    return job_id, str(job.get("company") or "")


@resume_builder_bp.route("/versions/save", methods=["POST"])
def save_version():
    """Create or update an independent saved resume.

    Editing a version never touches the candidate profile, the generated
    draft, or any other version: only the addressed row is written.
    """
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    user_id = session["user_id"]
    payload = _payload()
    candidate = get_candidate_context(db, user_id)

    version_id = payload.get("version_id")
    if version_id in (None, ""):
        version_id = None

    # Bound before the try so the error path can still show what the user had.
    sections = None

    try:
        sections = _submitted_sections(payload)
        if sections is None:
            raise resume_versions.VersionError(
                "There is nothing to save yet. Generate or write a resume first."
            )
        job_id, job_company = _version_target(payload)
        company = str(payload.get("company") or "").strip() or job_company

        version = resume_versions.save_version(
            db,
            user_id,
            candidate,
            sections=sections,
            target_role=str(payload.get("target_role") or "").strip(),
            template_key=str(payload.get("template") or "chronological"),
            custom_instructions=payload.get("custom_instructions", ""),
            job_id=job_id,
            company=company,
            job_description=payload.get("job_description", ""),
            title=str(payload.get("version_title") or payload.get("title") or "").strip(),
            version_id=version_id,
            source_fact_check=str(payload.get("fact_check_status") or "").strip(),
        )
    except resume_versions.VersionError as exc:
        message = str(exc)
        if _wants_json():
            return jsonify({"success": False, "error": message}), 400
        return _render_builder(
            db, user_id,
            role=_normalise_role(payload.get("target_role")),
            template_key=payload.get("template", "chronological"),
            error=message,
            draft_sections=sections,
        )

    if _wants_json():
        return jsonify({
            "success": True,
            "version_id": version["id"],
            "title": version["title"],
            "target_role": version["target_role"],
        })

    return _render_builder(
        db, user_id,
        role=version["target_role"],
        template_key=version["template_key"],
        version=version,
        notice=f'Saved as "{version["title"]}". Your profile and other resumes were not changed.',
    )


@resume_builder_bp.route("/versions/<int:version_id>/rename", methods=["POST"])
def rename_version(version_id):
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    user_id = session["user_id"]
    payload = _payload()
    try:
        version = resume_versions.rename_version(
            db, user_id, version_id, str(payload.get("title") or "")
        )
    except resume_versions.VersionError as exc:
        if _wants_json():
            return jsonify({"success": False, "error": str(exc)}), 400
        return _render_builder(db, user_id, error=str(exc))

    if _wants_json():
        return jsonify({"success": True, "title": version["title"]})
    return _render_builder(
        db, user_id,
        role=version["target_role"],
        template_key=version["template_key"],
        version=version,
        notice=f'Renamed to "{version["title"]}".',
    )


@resume_builder_bp.route("/versions/<int:version_id>/delete", methods=["POST"])
def delete_version(version_id):
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    user_id = session["user_id"]
    deleted = resume_versions.delete_version(db, user_id, version_id)

    if not deleted:
        message = "That saved resume could not be found."
        if _wants_json():
            return jsonify({"success": False, "error": message}), 404
        return _render_builder(db, user_id, error=message)

    if _wants_json():
        return jsonify({"success": True})
    return _render_builder(
        db, user_id, notice="That saved resume was deleted. Nothing else was changed."
    )


# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------

def _download_source(db, user_id, payload):
    """Which document a download should contain.

    A named version is loaded from the database -- the submitted content is
    ignored in that case, so a stale form cannot change what a saved resume
    produces. Otherwise the submitted (possibly edited) sections are used, so
    the download always reflects the latest edit even before saving.
    """
    version_id = payload.get("version_id")
    if version_id not in (None, ""):
        try:
            version = resume_versions.get_version(db, user_id, int(version_id))
        except (TypeError, ValueError):
            version = None
        if version is None:
            raise resume_versions.VersionError("That saved resume could not be found.")
        candidate = get_candidate_context(db, user_id)
        document = resume_versions.document_for(version, candidate)
        label = version["title"] or version["target_role"] or "resume"
        return document, label

    sections = _submitted_sections(payload)
    if sections is None:
        raise resume_versions.VersionError(
            "Generate a resume before downloading it."
        )
    candidate = get_candidate_context(db, user_id)
    document = resume_document.validate_sections(
        sections,
        name=resume_document.name_of({}, candidate),
        contact=resume_document.contact_for(candidate),
        headline=str(payload.get("target_role") or "").strip(),
    )
    return document, str(payload.get("target_role") or "") or "resume"


@resume_builder_bp.route("/download/txt", methods=["POST", "GET"])
def download_txt():
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    payload = _payload()
    try:
        document, label = _download_source(db, session["user_id"], payload)
    except resume_versions.VersionError as exc:
        return _download_failure(payload, str(exc))

    text = resume_document.render_text(document)
    if not text.strip():
        return _download_failure(payload, "There is no resume content to download yet.")

    filename = f"{resume_document.safe_filename(label)}-resume.txt"
    return Response(
        text,
        # mimetype (not content_type) so Flask adds the charset exactly once;
        # passing "text/plain; charset=utf-8" produced "...;charset=utf-8; charset=utf-8".
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@resume_builder_bp.route("/download/pdf", methods=["POST", "GET"])
def download_pdf():
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    payload = _payload()
    try:
        document, label = _download_source(db, session["user_id"], payload)
    except resume_versions.VersionError as exc:
        return _download_failure(payload, str(exc))

    try:
        pdf = resume_document.render_pdf(document)
    except Exception:
        # A PDF failure must not silently produce a download.
        logger.exception("Resume PDF generation failed")
        return _download_failure(
            payload, "The PDF could not be generated. Your resume is unchanged."
        )

    filename = f"{resume_document.safe_filename(label)}-resume.pdf"
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _download_failure(payload, message):
    """Report a failed download without ever returning a 200.

    This matters more than it looks: these routes are reached by a plain link or
    a form submit, so returning the rendered page with status 200 would let a
    browser save an HTML error page to disk as "resume.pdf". A failed download
    therefore either redirects back to the builder with the reason on it, or
    returns JSON to a fetch() caller -- never a successful-looking response.
    """
    if _wants_json():
        return jsonify({"success": False, "error": message}), 400

    flash(message, "error")
    return redirect(url_for(
        "resume_builder.view",
        target_role=_normalise_role(payload.get("target_role")) or None,
    ))


# --------------------------------------------------------------------------
# Existing profile-update endpoints (unchanged behaviour)
# --------------------------------------------------------------------------

@resume_builder_bp.route("/add-skill", methods=["POST"])
def add_skill():
    """Explicit legacy profile update endpoint; AI generation never calls it."""
    if not _require_login():
        return redirect(url_for("auth.login"))
    name = str(request.form.get("name", "")).strip()
    if name:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO skills (user_id, name, category) VALUES (%s, %s, %s)",
                (session["user_id"], name, "other"),
            )
        db.commit()
        flash(f'Added "{name}" to your skills.')
    return redirect(url_for("resume_builder.view", **_carry_forward_args()))


@resume_builder_bp.route("/add-project", methods=["POST"])
def add_project():
    """Explicit legacy project update endpoint; AI generation never calls it."""
    if not _require_login():
        return redirect(url_for("auth.login"))
    title = str(request.form.get("title", "")).strip()
    if not title:
        flash("Project title is required.")
        return redirect(url_for("resume_builder.view", **_carry_forward_args()))

    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO projects (user_id, title, description, tech_stack)
            VALUES (%s, %s, %s, %s)
            """,
            (
                session["user_id"],
                title,
                str(request.form.get("description", "")).strip() or None,
                str(request.form.get("tech_stack", "")).strip() or None,
            ),
        )
    db.commit()
    flash(f'Added "{title}" to your projects.')
    return redirect(url_for("resume_builder.view", **_carry_forward_args()))


def _carry_forward_args() -> dict:
    args = {}
    if request.form.get("target_role"):
        args["target_role"] = request.form["target_role"]
    if request.form.get("template"):
        args["template"] = request.form["template"]
    return args