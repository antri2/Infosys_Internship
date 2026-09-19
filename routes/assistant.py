"""
Career Assistant: UI shell for now. Per product decision, the actual
chatbot logic is a later milestone -- this route just renders a
"coming soon" chat interface so the page exists and looks finished.
"""
from flask import Blueprint, render_template, redirect, url_for, session

assistant_bp = Blueprint("assistant", __name__, url_prefix="/assistant")


def _require_login():
    return "user_id" in session


@assistant_bp.route("/", methods=["GET"])
def view():
    if not _require_login():
        return redirect(url_for("auth.login"))
    return render_template("assistant.html", active_page="assistant")