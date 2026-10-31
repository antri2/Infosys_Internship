"""Authenticated Career Assistant page and conversation endpoints."""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from database.db import get_db
from services.agent_orchestrator import AgentOrchestrator
from services.career_assistant_agent import ChatSessionNotFound


assistant_bp = Blueprint("assistant", __name__, url_prefix="/assistant")
logger = logging.getLogger(__name__)


def _require_login() -> bool:
    return "user_id" in session


def _payload() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else request.form


def _optional_id(payload: dict, key: str):
    value = payload.get(key)
    if value in (None, ""):
        return None
    if isinstance(value, bool) or (
        isinstance(value, float) and not value.is_integer()
    ):
        raise ValueError(f"A valid {key} is required.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"A valid {key} is required.") from exc
    if parsed <= 0:
        raise ValueError(f"A valid {key} is required.")
    return parsed


def _text(payload: dict, key: str, limit: int) -> str:
    value = payload.get(key, "")
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text.")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{key} is too long.")
    return value


def _error(message: str, status: int):
    return jsonify({"success": False, "error": message}), status


@assistant_bp.route("/", methods=["GET"])
def view():
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    error = None
    session_id = request.args.get("session_id", type=int)
    try:
        session_data = AgentOrchestrator(db, session["user_id"]).get_assistant_session(
            session_id
        )
    except (ValueError, ChatSessionNotFound):
        error = "The selected conversation could not be loaded."
        session_data = {"session_id": None, "context": {}, "messages": []}
    except Exception:
        logger.exception("Could not load Career Assistant conversation")
        session_data = {"session_id": None, "context": {}, "messages": []}
        error = "Your conversation could not be loaded right now."

    context = session_data.get("context") or {}
    try:
        conversations = AgentOrchestrator(
            db, session["user_id"]
        ).list_career_conversations()
    except Exception:
        logger.exception("Could not list Career Assistant conversations")
        conversations = []
    return render_template(
        "assistant.html",
        active_page="assistant",
        messages=session_data.get("messages", []),
        session_id=session_data.get("session_id"),
        conversations=conversations,
        selected_job_id=context.get("job_id") or request.args.get("job_id", type=int),
        target_role=context.get("target_role", "") or request.args.get("target_role", ""),
        pasted_jd=context.get("pasted_jd", "") or request.args.get("pasted_jd", ""),
        error=error,
    )


@assistant_bp.route("/message", methods=["POST"])
@assistant_bp.route("/chat", methods=["POST"])
@assistant_bp.route("/ask", methods=["POST"])
def message():
    if not _require_login():
        return _error("Not logged in.", 401)

    payload = _payload()
    payload = dict(payload)
    if "message" not in payload and "question" in payload:
        payload["message"] = payload["question"]
    if "session_id" not in payload and "conversation_id" in payload:
        payload["session_id"] = payload["conversation_id"]
    if "pasted_jd" not in payload:
        payload["pasted_jd"] = payload.get("job_description", payload.get("jd", ""))
    try:
        question = _text(payload, "message", 4000)
        if not question:
            raise ValueError("A question is required.")
        job_id = _optional_id(payload, "job_id")
        session_id = _optional_id(payload, "session_id")
        target_role = _text(payload, "target_role", 120)
        pasted_jd = _text(payload, "pasted_jd", 12000)
    except ValueError as exc:
        return _error(str(exc), 400)

    try:
        result = AgentOrchestrator(get_db(), session["user_id"]).run_career_assistant(
            question,
            job_id=job_id,
            target_role=target_role,
            pasted_jd=pasted_jd,
            session_id=session_id,
        )
    except ChatSessionNotFound:
        return _error("The conversation was not found.", 404)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        logger.exception("Career Assistant turn failed")
        return _error("The Career Assistant could not complete that question.", 503)

    return jsonify({"success": True, "response": result.get("answer", ""), **result})


@assistant_bp.route("/history", methods=["GET"])
@assistant_bp.route("/history/<int:session_id>", methods=["GET"])
def history(session_id: int | None = None):
    if not _require_login():
        return _error("Not logged in.", 401)
    try:
        result = AgentOrchestrator(
            get_db(), session["user_id"]
        ).get_assistant_session(session_id)
    except ChatSessionNotFound:
        return _error("The conversation was not found.", 404)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        logger.exception("Career Assistant history failed")
        return _error("Conversation history could not be loaded.", 503)
    return jsonify({"success": True, **result})


@assistant_bp.route("/reset", methods=["POST"])
def reset():
    if not _require_login():
        return _error("Not logged in.", 401)
    try:
        result = AgentOrchestrator(get_db(), session["user_id"]).reset_career_assistant()
    except Exception:
        logger.exception("Could not reset Career Assistant conversation")
        return _error("A new conversation could not be started.", 503)
    return jsonify({"success": True, **result})


@assistant_bp.route("/conversations", methods=["GET"])
def conversations():
    """Every stored conversation for this user, for the sidebar list."""
    if not _require_login():
        return _error("Not logged in.", 401)
    try:
        items = AgentOrchestrator(
            get_db(), session["user_id"]
        ).list_career_conversations()
    except Exception:
        logger.exception("Could not list Career Assistant conversations")
        return _error("Conversations could not be loaded.", 503)
    return jsonify({"success": True, "conversations": items})


@assistant_bp.route("/conversations/<int:session_id>/title", methods=["POST"])
def rename_conversation(session_id: int):
    if not _require_login():
        return _error("Not logged in.", 401)
    payload = _payload()
    title = " ".join(str(payload.get("title", "")).split())[:80]
    if not title:
        return _error("A conversation title is required.", 400)
    try:
        changed = AgentOrchestrator(
            get_db(), session["user_id"]
        ).rename_career_conversation(session_id, title)
    except Exception:
        logger.exception("Could not rename Career Assistant conversation")
        return _error("The conversation could not be renamed.", 503)
    if not changed:
        # Ownership is enforced in SQL, so this is also what a conversation
        # belonging to another user returns.
        return _error("The conversation was not found.", 404)
    return jsonify({"success": True, "title": title})


@assistant_bp.route("/conversations/<int:session_id>", methods=["DELETE", "POST"])
def delete_conversation(session_id: int):
    if not _require_login():
        return _error("Not logged in.", 401)
    try:
        deleted = AgentOrchestrator(
            get_db(), session["user_id"]
        ).delete_career_conversation(session_id)
    except Exception:
        logger.exception("Could not delete Career Assistant conversation")
        return _error("The conversation could not be deleted.", 503)
    if not deleted:
        return _error("The conversation was not found.", 404)
    return jsonify({"success": True})
