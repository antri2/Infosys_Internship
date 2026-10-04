"""Authenticated Interview Preparation page and JSON generation endpoint."""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from database.db import get_db
from services.agent_orchestrator import AgentOrchestrator
from services.context_builder import get_job_context
from services.interview_agent import (
    DIFFICULTIES,
    MAX_QUESTIONS,
    QUESTION_CATEGORIES,
    canonical_category,
    canonical_difficulty,
)
from services.role_catalog import canonical_role, job_role, role_options


interview_bp = Blueprint("interview", __name__, url_prefix="/interview")
logger = logging.getLogger(__name__)

# Icon + one-line description for each preparation category card.  Icons are
# inline SVG paths rather than emoji so the UI stays consistent across
# platforms.
CATEGORY_CARDS = [
    {"code": "technical", "icon": "chip", "title": "Technical",
     "description": "Test technical concepts and fundamentals."},
    {"code": "hr", "icon": "people", "title": "HR / Behavioral",
     "description": "Practice common HR and behavioral questions."},
    {"code": "coding", "icon": "code", "title": "Coding",
     "description": "Practice programming and problem-solving questions."},
    {"code": "project", "icon": "folder", "title": "Project-Based",
     "description": "Questions based on projects from your profile."},
    {"code": "role_specific", "icon": "target", "title": "Role-Specific",
     "description": "Questions focused on your target role or JD."},
    {"code": "mixed", "icon": "grid", "title": "Mixed Interview",
     "description": "Combination of technical, HR, coding and project questions."},
]

CATEGORY_ICONS = {
    "chip": '<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>',
    "people": '<circle cx="9" cy="8" r="3"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M16 5.5a3 3 0 0 1 0 5.5M17 20a6 6 0 0 0-2-4.5"/>',
    "code": '<path d="M9 8l-5 4 5 4M15 8l5 4-5 4"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "target": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/>',
    "grid": '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
}

COUNT_OPTIONS = (5, 10, 15, 20)


def _require_login() -> bool:
    return "user_id" in session


def _payload() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else request.form


def _optional_job_id(payload: dict) -> int | None:
    value = payload.get("job_id")
    if value in (None, ""):
        return None
    if isinstance(value, bool) or (
        isinstance(value, float) and not value.is_integer()
    ):
        raise ValueError("A valid job_id is required.")
    try:
        job_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("A valid job_id is required.") from exc
    if job_id <= 0 or (
        str(job_id) != str(value).strip() and not isinstance(value, int)
    ):
        raise ValueError("A valid job_id is required.")
    return job_id


def _optional_text(payload: dict, keys: tuple[str, ...], limit: int, label: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise ValueError(f"{label} must be text.")
        text = value.strip()
        if len(text) > limit:
            raise ValueError(f"{label} must be {limit} characters or fewer.")
        return text
    return ""


def _question_count(payload: dict) -> int:
    value = payload.get(
        "count",
        payload.get("question_count", payload.get("number_of_questions", 5)),
    )
    if isinstance(value, bool) or (
        isinstance(value, float) and not value.is_integer()
    ):
        raise ValueError(f"Question count must be between 1 and {MAX_QUESTIONS}.")
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Question count must be between 1 and {MAX_QUESTIONS}.") from exc
    if not 1 <= count <= MAX_QUESTIONS:
        raise ValueError(f"Question count must be between 1 and {MAX_QUESTIONS}.")
    return count


def _json_error(message: str, status: int):
    return jsonify({"success": False, "error": message}), status


def _selected_job_json(job: dict | None) -> dict | None:
    if not job:
        return None
    return {
        "job_id": int(job["job_id"]),
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
    }


@interview_bp.route("/", methods=["GET"])
def view():
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    selected_role = canonical_role(request.args.get("target_role", "AI Engineer")) or "AI Engineer"
    specific_job_id = request.args.get("job_id", type=int)
    selected_job = None
    error = None
    # A stored job is only ever used when the user explicitly arrived from an
    # Opportunity or an Application. Selecting a role alone must not resolve a
    # random posting from the dataset.
    if specific_job_id:
        selected_job = get_job_context(db, specific_job_id)
        if selected_job is None:
            error = f"Job {specific_job_id} was not found."
        else:
            selected_role = job_role(selected_job) or selected_role

    target_source = request.args.get("target_source", "role")
    if target_source not in {"role", "custom"}:
        target_source = "custom" if selected_job is not None else "role"

    selected_category = canonical_category(request.args.get("category", "technical")) or "technical"
    selected_difficulty = canonical_difficulty(request.args.get("difficulty", "medium")) or "medium"
    try:
        selected_count = max(1, min(MAX_QUESTIONS, int(request.args.get("count", 5))))
    except (TypeError, ValueError):
        selected_count = 5
    company = (request.args.get("company", "") or "").strip()
    job_description = (
        request.args.get("job_description", request.args.get("jd", "")) or ""
    ).strip()
    focus_areas = (request.args.get("focus_areas", "") or "").strip()

    recent_questions = []
    recent_plans = []
    try:
        history = AgentOrchestrator(db, session["user_id"]).list_recent_interview_data()
        recent_questions = history["questions"]
        recent_plans = history["plans"]
    except Exception:
        logger.exception("Could not load saved Interview Preparation data")

    return render_template(
        "Interview.html",
        active_page="interview",
        role_options=role_options(),
        selected_role=selected_role,
        specific_job_id=specific_job_id,
        selected_job=selected_job,
        target_source=target_source,
        category_cards=CATEGORY_CARDS,
        category_icons=CATEGORY_ICONS,
        category_labels=QUESTION_CATEGORIES,
        difficulty_labels=DIFFICULTIES,
        count_options=COUNT_OPTIONS,
        company=company,
        job_description=job_description,
        focus_areas=focus_areas,
        question_categories=QUESTION_CATEGORIES,
        difficulties=DIFFICULTIES,
        selected_category=selected_category,
        selected_difficulty=selected_difficulty,
        selected_count=selected_count,
        recent_questions=recent_questions,
        recent_plans=recent_plans,
        error=error,
    )


@interview_bp.route("/generate", methods=["POST"])
@interview_bp.route("/generate-questions", methods=["POST"])
def generate():
    """Generate questions and a plan through AgentOrchestrator."""
    if not _require_login():
        return _json_error("Not logged in.", 401)

    payload = _payload()
    try:
        job_id = _optional_job_id(payload)
        count = _question_count(payload)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    raw_role = payload.get("target_role", payload.get("role", ""))
    if not isinstance(raw_role, str):
        return _json_error("Target role is required.", 400)
    target_role = canonical_role(raw_role)
    db = get_db()
    job = None
    if job_id is not None:
        try:
            job = get_job_context(db, job_id)
        except Exception:
            logger.exception("Could not load Interview Preparation job %s", job_id)
            return _json_error("The selected job could not be loaded right now.", 503)
        if job is None:
            return _json_error(f"Job {job_id} was not found.", 404)
        target_role = target_role or job_role(job)
    if not target_role:
        return _json_error("Target role is required.", 400)

    raw_category = payload.get("category", payload.get("question_type", ""))
    category = canonical_category(raw_category)
    if category is None:
        return _json_error("Invalid question category.", 400)
    raw_difficulty = payload.get("difficulty", "")
    difficulty = canonical_difficulty(raw_difficulty)
    if difficulty is None:
        return _json_error("Invalid difficulty.", 400)
    company = _optional_text(payload, ("company", "company_name"), 200, "Company name")
    job_description = _optional_text(
        payload, ("job_description", "jd", "pasted_jd"), 4000, "Job description"
    )
    focus_areas = _optional_text(payload, ("focus_areas", "focus"), 200, "Focus areas")

    try:
        result = AgentOrchestrator(db, session["user_id"]).run_interview_preparation(
            target_role=target_role,
            job_id=job_id,
            category=category,
            difficulty=difficulty,
            count=count,
            focus_areas=focus_areas,
            company=company,
            job_description=job_description,
        )
    except ValueError as exc:
        message = str(exc)
        if "was not found" in message:
            return _json_error(message, 404)
        return _json_error(message, 400)
    except Exception:
        logger.exception("Interview preparation failed")
        return _json_error("Interview preparation could not be completed right now.", 503)

    return jsonify({
        "success": True,
        "target_role": result["target_role"],
        "job": _selected_job_json(job),
        "category": result["category"],
        "category_label": result.get("category_label"),
        "difficulty": result["difficulty"],
        "difficulty_label": result.get("difficulty_label"),
        "context_mode": result.get("context_mode"),
        "company": result.get("company", ""),
        "focus_areas": result.get("focus_areas", ""),
        "question_ids": result.get("question_ids", []),
        "questions": result["questions"],
        "plan": result["plan"],
        "used_fallback": result.get("used_fallback", False),
        "validation_status": result.get("validation_status", "validated"),
        "skill_gap": result.get("skill_gap"),
    })


@interview_bp.route("/tip", methods=["POST"])
def tip():
    """Return a short hint for the current question, never the full answer."""
    if not _require_login():
        return _json_error("Not logged in.", 401)

    payload = _payload()
    question = _optional_text(payload, ("question",), 4000, "Question")
    if not question:
        return _json_error("Question is required.", 400)
    target_role = str(payload.get("target_role", "") or "").strip()
    if not target_role:
        return _json_error("Target role is required.", 400)
    company = _optional_text(payload, ("company",), 200, "Company name")
    job_description = _optional_text(
        payload, ("job_description", "jd"), 4000, "Job description"
    )

    try:
        result = AgentOrchestrator(get_db(), session["user_id"]).get_interview_tip(
            question,
            target_role,
            canonical_category(payload.get("category", "")) or "",
            canonical_difficulty(payload.get("difficulty", "")) or "",
            company=company,
            job_description=job_description,
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        logger.exception("Interview tip generation failed")
        return _json_error("A tip could not be generated right now.", 503)

    return jsonify({"success": True, "tip": result["tip"]})


@interview_bp.route("/evaluate", methods=["POST"])
def evaluate():
    """Evaluate a submitted mock-interview answer."""
    if not _require_login():
        return _json_error("Not logged in.", 401)

    payload = _payload()
    question = _optional_text(payload, ("question",), 4000, "Question")
    if not question:
        return _json_error("Question is required.", 400)
    user_answer = _optional_text(payload, ("answer", "user_answer"), 6000, "Answer")
    if not user_answer:
        return _json_error("An answer is required before submitting.", 400)
    target_role = str(payload.get("target_role", "") or "").strip()
    if not target_role:
        return _json_error("Target role is required.", 400)
    company = _optional_text(payload, ("company",), 200, "Company name")
    job_description = _optional_text(
        payload, ("job_description", "jd"), 4000, "Job description"
    )

    try:
        result = AgentOrchestrator(
            get_db(), session["user_id"]
        ).evaluate_interview_answer(
            question,
            user_answer,
            target_role,
            category=canonical_category(payload.get("category", "")) or "",
            difficulty=canonical_difficulty(payload.get("difficulty", "")) or "",
            company=company,
            job_description=job_description,
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        logger.exception("Interview answer evaluation failed")
        return _json_error("Your answer could not be evaluated right now.", 503)

    return jsonify({"success": True, **result})


@interview_bp.route("/mock/start", methods=["POST"])
def mock_start():
    """Open a mock-interview session for the interview history."""
    if not _require_login():
        return _json_error("Not logged in.", 401)

    payload = _payload()
    try:
        job_id = _optional_job_id(payload)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        result = AgentOrchestrator(get_db(), session["user_id"]).start_mock_interview(job_id)
    except ValueError as exc:
        message = str(exc)
        return _json_error(message, 404 if "was not found" in message else 400)
    except Exception:
        logger.exception("Could not start the mock interview session")
        return _json_error("The mock interview session could not be started.", 503)
    return jsonify({"success": True, **result})


@interview_bp.route("/mock/answer", methods=["POST"])
def mock_answer():
    """Record one mock answer, or a skip when no answer is supplied."""
    if not _require_login():
        return _json_error("Not logged in.", 401)

    payload = _payload()
    try:
        session_id = int(payload.get("session_id"))
        question_id = int(payload.get("question_id"))
    except (TypeError, ValueError):
        return _json_error("A valid session_id and question_id are required.", 400)

    answer = _optional_text(payload, ("answer", "user_answer"), 6000, "Answer")
    feedback = payload.get("feedback")
    if not isinstance(feedback, dict):
        feedback = None
    score = payload.get("score")

    try:
        AgentOrchestrator(
            get_db(), session["user_id"]
        ).record_mock_answer(session_id, question_id, answer, feedback, score)
    except ValueError as exc:
        return _json_error(str(exc), 404)
    except Exception:
        logger.exception("Could not record the mock interview answer")
        return _json_error("The answer could not be saved.", 503)
    return jsonify({"success": True, "skipped": not bool(answer)})


@interview_bp.route("/mock/finish", methods=["POST"])
def mock_finish():
    """Close a mock session so it appears in Interview History."""
    if not _require_login():
        return _json_error("Not logged in.", 401)

    payload = _payload()
    try:
        session_id = int(payload.get("session_id"))
    except (TypeError, ValueError):
        return _json_error("A valid session_id is required.", 400)

    try:
        AgentOrchestrator(get_db(), session["user_id"]).finish_mock_interview(session_id)
    except ValueError as exc:
        return _json_error(str(exc), 404)
    except Exception:
        logger.exception("Could not finish the mock interview session")
        return _json_error("The session could not be closed.", 503)
    return jsonify({"success": True})


@interview_bp.route("/mock/history", methods=["GET"])
def mock_history():
    """Compact list of completed mock interviews."""
    if not _require_login():
        return _json_error("Not logged in.", 401)
    try:
        sessions = AgentOrchestrator(
            get_db(), session["user_id"]
        ).list_mock_interview_history()
    except Exception:
        logger.exception("Could not load mock interview history")
        return _json_error("Interview history could not be loaded.", 503)
    return jsonify({"success": True, "sessions": sessions})


@interview_bp.route("/mock/history/<int:session_id>", methods=["GET"])
def mock_history_detail(session_id: int):
    """Full question-by-question review of one completed mock interview."""
    if not _require_login():
        return _json_error("Not logged in.", 401)
    try:
        result = AgentOrchestrator(
            get_db(), session["user_id"]
        ).load_mock_interview_history(session_id)
    except Exception:
        logger.exception("Could not load the mock interview review")
        return _json_error("The interview review could not be loaded.", 503)
    if result is None:
        return _json_error("Interview session was not found.", 404)
    return jsonify({"success": True, "session": result})


@interview_bp.route("/summary", methods=["POST"])
def summary():
    """Practice-only summary of a completed mock interview."""
    if not _require_login():
        return _json_error("Not logged in.", 401)

    payload = _payload()
    target_role = str(payload.get("target_role", "") or "").strip()
    if not target_role:
        return _json_error("Target role is required.", 400)
    results = payload.get("results")
    if not isinstance(results, list):
        results = []
    results = results[:50]

    try:
        result = AgentOrchestrator(
            get_db(), session["user_id"]
        ).summarize_interview_session(target_role, results)
    except Exception:
        logger.exception("Interview summary failed")
        return _json_error("The summary could not be created right now.", 503)

    return jsonify({"success": True, **result})


@interview_bp.route("/recent", methods=["GET"])
def recent():
    if not _require_login():
        return _json_error("Not logged in.", 401)
    try:
        history = AgentOrchestrator(
            get_db(), session["user_id"]
        ).list_recent_interview_data()
    except Exception:
        logger.exception("Could not load recent Interview Preparation data")
        return _json_error("Saved Interview Preparation data could not be loaded.", 503)
    return jsonify({"success": True, **history})
