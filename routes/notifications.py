"""Notification panel endpoints for the header bell.

Read-only with respect to application tracking: these routes list and mark
notifications as read, and never insert business data. Generation happens in
the routes that own the underlying event (Opportunities, Skill Gap,
Applications) so a notification can only ever describe something that really
happened.
"""
from flask import Blueprint, jsonify, redirect, request, session, url_for

from database.db import get_db
from services.notification_service import (
    MAX_NOTIFICATIONS,
    list_notifications,
    mark_all_read,
    mark_read,
    unread_count,
)


notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")

# The bell reads its state on every page, so the payload stays small.
LIST_LIMIT = 10


def _escape(value) -> str:
    """Escape text before it is embedded in the server-rendered fragment."""
    text = str(value if value is not None else "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _require_login():
    return "user_id" in session


def _serialise(row: dict) -> dict:
    created = row.get("created_at")
    return {
        "id": row.get("id"),
        "category": row.get("category"),
        "title": row.get("title"),
        "body": row.get("body"),
        "link": row.get("link"),
        "is_read": bool(row.get("is_read")),
        "created_at": created.isoformat() if created else None,
    }


def _valid_limit() -> int:
    raw = request.args.get("limit", LIST_LIMIT)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return LIST_LIMIT
    return max(1, min(value, MAX_NOTIFICATIONS))


@notifications_bp.route("/", methods=["GET"])
def list_notifications_view():
    """Return the user's notifications plus the unread count.

    A ``mark_read=1`` query marks everything read first, which is what the
    panel does when the user opens it.
    """
    if not _require_login():
        return jsonify({"error": "Not logged in."}), 401

    db = get_db()
    user_id = session["user_id"]

    if request.args.get("mark_read") == "1":
        mark_all_read(db, user_id)

    rows = list_notifications(db, user_id, limit=_valid_limit())
    return jsonify({
        "notifications": [_serialise(row) for row in rows],
        "unread": unread_count(db, user_id),
    })


@notifications_bp.route("/read-all", methods=["POST"])
def read_all():
    if not _require_login():
        return jsonify({"error": "Not logged in."}), 401

    db = get_db()
    user_id = session["user_id"]
    mark_all_read(db, user_id)
    return jsonify({"success": True, "unread": 0})


@notifications_bp.route("/<int:notification_id>/read", methods=["POST"])
def read_one(notification_id: int):
    """Mark one notification as read.

    A row that belongs to another user is reported as not found rather than
    silently succeeding, so this cannot be used to probe for other users'
    notifications.
    """
    if not _require_login():
        return jsonify({"error": "Not logged in."}), 401

    db = get_db()
    user_id = session["user_id"]
    changed = mark_read(db, user_id, notification_id)

    if not changed:
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM notifications WHERE id = %s AND user_id = %s",
                (notification_id, user_id),
            )
            if cursor.fetchone() is None:
                return jsonify({"error": "Notification was not found."}), 404

    return jsonify({"success": True, "unread": unread_count(db, user_id)})


@notifications_bp.route("/bell", methods=["GET"])
def bell():
    """Server-rendered drawer body, used when JS is unavailable.

    Renders the same drawer markup the client-side script fills, so a user
    without JavaScript still sees real notifications instead of a blank panel.
    """
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    user_id = session["user_id"]
    rows = list_notifications(db, user_id, limit=LIST_LIMIT)
    unread = unread_count(db, user_id)

    if not rows:
        body = (
            '<div class="notification-empty-state">'
            '<span class="notification-empty-icon" aria-hidden="true">&#128276;</span>'
            '<p class="notification-empty"><strong>You are all caught up.</strong></p>'
            '<p class="notification-empty">New opportunities, skill gap updates, and '
            "application status changes will appear here.</p></div>"
        )
    else:
        parts = []
        for row in rows:
            item = _serialise(row)
            created = item.get("created_at") or ""
            parts.append(
                '<article class="notification-item{unread}">'
                '<div class="notification-item-top">'
                '<span class="notification-category">{category}</span>{dot}</div>'
                '<p class="notification-title">{title}</p>{body}'
                '<div class="notification-item-foot">{time}{link}</div></article>'.format(
                    unread="" if item["is_read"] else " is-unread",
                    category=_escape(item["category"].replace("_", " ").title()),
                    dot="" if item["is_read"]
                    else '<span class="notification-unread-dot" aria-label="Unread"></span>',
                    title=_escape(item["title"]),
                    body=f'<p class="notification-body">{_escape(item["body"])}</p>'
                    if item["body"] else "",
                    time=f'<span class="notification-time">{_escape(created[:16].replace("T", " "))}</span>'
                    if created else "",
                    link=f'<a class="notification-link" href="{_escape(item["link"])}">View</a>'
                    if item["link"] else "",
                )
            )
        body = "".join(parts)

    return jsonify({
        "success": True,
        "notifications": [_serialise(row) for row in rows],
        "unread": unread,
        "html": body,
    })
