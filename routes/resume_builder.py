"""Role-based Resume Builder page and generation/save endpoints."""
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from database.db import get_db
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


def _payload():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else request.form


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
):
    candidate = get_candidate_context(db, user_id)
    role_job = None
    skill_gap = None
    if role:
        try:
            role, role_job = _resolve_target(db, {"target_role": role})
        except ValueError as exc:
            error = error or str(exc)
            role_job = None
    if role_job:
        try:
            skill_gap = AgentOrchestrator(db, user_id).get_cached_skill_gap(
                int(role_job["job_id"])
            )
        except Exception:
            logger.exception("Could not load Resume Builder Skill Gap context")
    if result is not None:
        skill_gap = result.get("skill_gap", skill_gap)
    ordered_templates = _ordered_templates()
    resolved_template = template_key if template_key in ordered_templates else "chronological"
    return render_template(
        "resume_builder.html",
        active_page="resume_builder",
        role_options=RESUME_ROLE_OPTIONS,
        selected_role=role,
        selected_template=resolved_template,
        templates=ordered_templates,
        selected_template_description=ordered_templates[resolved_template]["description"],
        custom_instructions=custom_instructions,
        candidate=candidate,
        result=result,
        role_requirements=_role_requirements(role_job),
        skill_gap=skill_gap,
        error=error,
        saved=saved,
        profile_updates=profile_updates or {},
    )


@resume_builder_bp.route("/", methods=["GET"])
def view():
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    role = _normalise_role(request.args.get("target_role"))
    template_key = request.args.get("template", "chronological")
    if template_key not in TEMPLATES:
        template_key = "chronological"
    result = None
    error = None
    role_job = None
    custom_instructions = ""

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

    if role_job:
        try:
            orchestrator = AgentOrchestrator(db, session["user_id"])
            result = orchestrator.get_cached_resume_builder(
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
        session["user_id"],
        role=role,
        template_key=template_key,
        result=result,
        error=error,
        custom_instructions=custom_instructions,
    )


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
    )


@resume_builder_bp.route("/save", methods=["POST"])
@resume_builder_bp.route("/update", methods=["POST"])
def save():
    """Save the exact user-approved text without invoking the LLM."""
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
        if request.is_json:
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
        if request.is_json:
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
    if request.is_json:
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
        args["target_role"] = request.form.get("target_role")
    if request.form.get("template"):
        args["template"] = request.form.get("template")
    return args
