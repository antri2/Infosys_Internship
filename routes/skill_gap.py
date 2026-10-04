"""Separate Skill Gap page and JSON analysis endpoint with role-level selection."""
import logging

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from database.db import get_db
from services import skill_gap_service
from services.agent_orchestrator import AgentOrchestrator
from services.context_builder import get_candidate_context, get_job_context
from services.role_catalog import canonical_role, job_role, role_options


skill_gap_bp = Blueprint("skill_gap", __name__, url_prefix="/skill-gap")
logger = logging.getLogger(__name__)


def _require_login():
    return "user_id" in session


def _optional_job_id(payload: dict):
    value = payload.get("job_id", payload.get("explicit_job_id"))
    if value in (None, ""):
        return None
    if isinstance(value, bool) or (
        isinstance(value, float) and not value.is_integer()
    ):
        raise ValueError("A valid job_id is required.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("A valid job_id is required.") from exc
    if parsed <= 0:
        raise ValueError("A valid job_id is required.")
    return parsed


def _optional_text(payload: dict, key: str, limit: int, label: str) -> str:
    value = payload.get(key, "")
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{label} must be {limit} characters or fewer.")
    return value


@skill_gap_bp.route("/", methods=["GET"])
def view():
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    selected_role = canonical_role(request.args.get("target_role", "AI Engineer")) or "AI Engineer"
    specific_job_id = request.args.get("job_id", type=int)
    company = request.args.get("company", "").strip()
    pasted_jd = request.args.get("job_description", request.args.get("jd", "")).strip()
    selected_job = None
    error = None

    # A database job is used only when the user explicitly arrived from an
    # Opportunity/deep link. A role selection alone never resolves a job.
    if specific_job_id:
        selected_job = get_job_context(db, specific_job_id)
        if selected_job is None:
            error = f"Job {specific_job_id} was not found."
        else:
            selected_role = job_role(selected_job) or selected_role

    return render_template(
        "skill_gap.html",
        active_page="skill_gap",
        role_options=role_options(),
        selected_role=selected_role,
        specific_job_id=specific_job_id,
        selected_job=selected_job,
        company=company,
        pasted_jd=pasted_jd,
        error=error,
    )


@skill_gap_bp.route("/analyze", methods=["POST"])
def analyze():
    if not _require_login():
        return jsonify({"success": False, "error": "Not logged in."}), 401

    payload = request.get_json(silent=True) or request.form
    try:
        job_id = _optional_job_id(payload)
        target_role = canonical_role(payload.get("target_role", ""))
        company = _optional_text(payload, "company", 200, "Company name")
        if not company:
            company = _optional_text(payload, "company_name", 200, "Company name")
        pasted_jd = _optional_text(payload, "job_description", 12000, "Job description")
        if not pasted_jd:
            pasted_jd = _optional_text(payload, "jd", 12000, "Job description")
        if not pasted_jd:
            pasted_jd = _optional_text(payload, "pasted_jd", 12000, "Job description")
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    if not target_role and job_id is None:
        return jsonify({"success": False, "error": "Select a target role first."}), 400

    db = get_db()
    explicit_job = None
    if job_id is not None:
        explicit_job = get_job_context(db, job_id)
        if explicit_job is None:
            return jsonify({"success": False, "error": f"Job {job_id} was not found."}), 404
        if not target_role:
            target_role = job_role(explicit_job) or target_role

    try:
        if pasted_jd:
            # A pasted JD always wins over a role or an Opportunity's stored
            # posting. No database job is created or selected for this mode.
            analysis_job = skill_gap_service.build_jd_context(
                target_role, company, pasted_jd
            )
            candidate = get_candidate_context(db, session["user_id"])
            report = skill_gap_service.generate_skill_gap_report(candidate, analysis_job)
            analysis_mode = "jd"
        elif explicit_job is not None:
            report = AgentOrchestrator(db, session["user_id"]).run_skill_gap(job_id)
            analysis_mode = "job"
        else:
            # Role-only mode deliberately uses a synthetic advisory context;
            # it never calls find_role_job or chooses a random posting.
            analysis_job = skill_gap_service.build_role_context(target_role, company)
            candidate = get_candidate_context(db, session["user_id"])
            report = skill_gap_service.generate_skill_gap_report(candidate, analysis_job)
            analysis_mode = "role"
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        logger.exception("Skill Gap analysis failed for role %s", target_role)
        return jsonify({
            "success": False,
            "error": "Skill Gap analysis could not be completed right now.",
        }), 503

    job_payload = None
    if analysis_mode == "job" and explicit_job is not None:
        job_payload = {
            "job_id": int(explicit_job["job_id"]),
            "title": explicit_job["title"],
            "company": explicit_job["company"],
            "location": explicit_job.get("location"),
        }
    return jsonify({
        "success": True,
        "target_role": target_role,
        "analysis": {
            "mode": analysis_mode,
            "company": company,
            "source": (
                "provided_job_description" if analysis_mode == "jd"
                else "explicit_opportunity_job" if analysis_mode == "job"
                else "role_level_guidance"
            ),
        },
        "job": job_payload,
        "report": report,
    })
