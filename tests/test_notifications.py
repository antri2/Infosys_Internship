"""Notification bell: storage, read state, and duplicate suppression.

Everything here is asserted against real data already in the database. The
tests also verify that no notification invents a deadline or a date.
"""
import json
import re

import pytest

from services import notification_service as ns


def _make_job(db, title="Data Analyst", company="Vertex Digital Labs"):
    """Insert a real job row the notifications can legitimately point at."""
    with db.cursor() as cursor:
        cursor.execute("SELECT MAX(job_id) AS top FROM jobs")
        job_id = int((cursor.fetchone() or {}).get("top") or 0) + 1
        cursor.execute(
            "INSERT INTO jobs (job_id, title, company, location, description, "
            "required_skills, qualifications) "
            "VALUES (%s, %s, %s, 'Bangalore', 'Analysis work.', "
            "'Python, SQL', 'B.Tech')",
            (job_id, title, company),
        )
    db.commit()
    return job_id


def _delete_job(db, job_id):
    with db.cursor() as cursor:
        cursor.execute("DELETE FROM jobs WHERE job_id = %s", (job_id,))
    db.commit()


# ------------------------------------------------------------------ storage ---


def test_add_and_read_back(app, candidate):
    from database.db import get_db

    with app.app_context():
        db = get_db()
        ns.add_notification(
            db, candidate["user_id"], ns.CATEGORY_OPPORTUNITY,
            "New opportunity: Data Analyst",
            body="Vertex Digital Labs - 80% Profile Skill Fit",
            link="/opportunities/",
            dedupe_key="opportunity:999",
        )
        rows = ns.list_notifications(db, candidate["user_id"])
        titles = [row["title"] for row in rows]
        assert "New opportunity: Data Analyst" in titles
        assert ns.unread_count(db, candidate["user_id"]) == 1


def test_same_dedupe_key_is_never_inserted_twice(app, candidate):
    from database.db import get_db

    with app.app_context():
        db = get_db()
        first = ns.add_notification(
            db, candidate["user_id"], ns.CATEGORY_OPPORTUNITY,
            "New opportunity: Data Analyst", dedupe_key="opportunity:1001",
        )
        second = ns.add_notification(
            db, candidate["user_id"], ns.CATEGORY_OPPORTUNITY,
            "New opportunity: Data Analyst", dedupe_key="opportunity:1001",
        )
        assert first is True
        assert second is False
        assert len(ns.list_notifications(db, candidate["user_id"])) == 1


def test_dedupe_is_per_user(app, candidate):
    """One user's event must not suppress another user's."""
    from database.db import get_db

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, career_status) "
                "VALUES ('Other', 'other-notif@example.test', 'x', 'Fresher')"
            )
            other_id = cursor.lastrowid
        db.commit()

        assert ns.add_notification(
            db, candidate["user_id"], ns.CATEGORY_OPPORTUNITY,
            "Shared event", dedupe_key="opportunity:shared",
        )
        assert ns.add_notification(
            db, other_id, ns.CATEGORY_OPPORTUNITY,
            "Shared event", dedupe_key="opportunity:shared",
        )

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS c FROM notifications WHERE user_id = %s",
                           (other_id,))
            assert cursor.fetchone()["c"] == 1
            cursor.execute("DELETE FROM users WHERE id = %s", (other_id,))
        db.commit()


def test_blank_title_or_key_is_never_stored(app, candidate):
    from database.db import get_db

    with app.app_context():
        db = get_db()
        assert ns.add_notification(db, candidate["user_id"], "opportunity", "", dedupe_key="k") is False
        assert ns.add_notification(db, candidate["user_id"], "opportunity", "T", dedupe_key="") is False
        assert ns.list_notifications(db, candidate["user_id"]) == []


# -------------------------------------------------------------------- read ---


def test_mark_read_clears_unread_count(app, candidate):
    from database.db import get_db

    with app.app_context():
        db = get_db()
        ns.add_notification(db, candidate["user_id"], "opportunity", "A", dedupe_key="r:1")
        ns.add_notification(db, candidate["user_id"], "skill_gap", "B", dedupe_key="r:2")
        assert ns.unread_count(db, candidate["user_id"]) == 2

        rows = ns.list_notifications(db, candidate["user_id"])
        assert ns.mark_read(db, candidate["user_id"], rows[0]["id"]) is True
        assert ns.unread_count(db, candidate["user_id"]) == 1

        assert ns.mark_all_read(db, candidate["user_id"]) == 1
        assert ns.unread_count(db, candidate["user_id"]) == 0
        # A second mark-all is a no-op, not an error.
        assert ns.mark_all_read(db, candidate["user_id"]) == 0


def test_marking_read_twice_reports_no_change(app, candidate):
    from database.db import get_db

    with app.app_context():
        db = get_db()
        ns.add_notification(db, candidate["user_id"], "opportunity", "A", dedupe_key="r3:1")
        row = ns.list_notifications(db, candidate["user_id"])[0]
        assert ns.mark_read(db, candidate["user_id"], row["id"]) is True
        assert ns.mark_read(db, candidate["user_id"], row["id"]) is False


# --------------------------------------------------- generation from real data ---


def test_new_opportunity_notification_uses_only_real_job_fields(app, candidate):
    from database.db import get_db

    with app.app_context():
        db = get_db()
        job_id = _make_job(db)
        try:
            created = ns.notify_new_opportunities(db, candidate["user_id"], [{
                "job_id": job_id,
                "title": "Data Analyst",
                "company": "Vertex Digital Labs",
                "match_available": True,
                "match_percent": 82,
            }])
            assert created == 1
            row = ns.list_notifications(db, candidate["user_id"])[0]
            assert "Data Analyst" in row["title"]
            assert "82% Profile Skill Fit" in row["body"]
        finally:
            _delete_job(db, job_id)


def test_low_fit_and_tracked_jobs_are_not_announced(app, candidate):
    from database.db import get_db

    with app.app_context():
        db = get_db()
        job_id = _make_job(db)
        try:
            created = ns.notify_new_opportunities(db, candidate["user_id"], [
                {"job_id": job_id, "title": "Data Analyst", "company": "X",
                 "match_available": True, "match_percent": 30},
                {"job_id": job_id, "title": "Data Analyst", "company": "X",
                 "match_available": False, "match_percent": None},
                {"job_id": job_id, "title": "Data Analyst", "company": "X",
                 "match_available": True, "match_percent": 90,
                 "application_status": "applied"},
            ])
            assert created == 0
            assert ns.list_notifications(db, candidate["user_id"]) == []
        finally:
            _delete_job(db, job_id)


def test_repeated_opportunity_page_creates_no_duplicates(app, candidate):
    """Re-opening Opportunities must not re-announce the same jobs."""
    from database.db import get_db

    with app.app_context():
        db = get_db()
        job_id = _make_job(db)
        jobs = [{
            "job_id": job_id, "title": "Data Analyst", "company": "Vertex Digital Labs",
            "match_available": True, "match_percent": 88,
        }]
        try:
            assert ns.notify_new_opportunities(db, candidate["user_id"], jobs) == 1
            assert ns.notify_new_opportunities(db, candidate["user_id"], jobs) == 0
            assert ns.notify_new_opportunities(db, candidate["user_id"], jobs) == 0
            assert len(ns.list_notifications(db, candidate["user_id"])) == 1
        finally:
            _delete_job(db, job_id)


def test_skill_gap_notification_lists_only_recorded_gaps(app, candidate):
    from database.db import get_db

    with app.app_context():
        db = get_db()
        job_id = _make_job(db)
        try:
            created = ns.notify_skill_gap(db, candidate["user_id"], job_id, {
                "critical_gaps": [
                    {"skill": "Power BI", "why_it_matters": "dashboards"},
                    {"skill": "Tableau", "why_it_matters": "reporting"},
                ],
            }, role="Data Analyst")
            assert created == 1
            body = ns.list_notifications(db, candidate["user_id"])[0]["body"]
            assert "Power BI" in body and "Tableau" in body
        finally:
            _delete_job(db, job_id)


def test_skill_gap_with_no_critical_gaps_creates_nothing(app, candidate):
    from database.db import get_db

    with app.app_context():
        db = get_db()
        assert ns.notify_skill_gap(
            db, candidate["user_id"], 1, {"critical_gaps": []}, role="Data Analyst"
        ) == 0
        assert ns.notify_skill_gap(
            db, candidate["user_id"], 1, {}, role="Data Analyst"
        ) == 0
        assert ns.list_notifications(db, candidate["user_id"]) == []


def test_application_notification_restates_the_stored_status(app, candidate):
    from database.db import get_db

    with app.app_context():
        db = get_db()
        job_id = _make_job(db)
        try:
            assert ns.notify_application(db, candidate["user_id"], job_id, "applied") == 1
            row = ns.list_notifications(db, candidate["user_id"])[0]
            assert "Data Analyst" in row["title"]
            assert "Vertex Digital Labs" in row["title"]
            assert "applied" in row["body"].lower()
        finally:
            _delete_job(db, job_id)


def test_application_notification_ignores_an_unknown_status(app, candidate):
    from database.db import get_db

    with app.app_context():
        db = get_db()
        job_id = _make_job(db)
        try:
            assert ns.notify_application(db, candidate["user_id"], job_id, "ghosted") == 0
            assert ns.notify_application(db, candidate["user_id"], 99999999, "applied") == 0
            assert ns.list_notifications(db, candidate["user_id"]) == []
        finally:
            _delete_job(db, job_id)


def test_application_notification_has_no_invented_deadline(app, candidate):
    """The schema has no deadline field, so no notification may imply one."""
    from database.db import get_db

    with app.app_context():
        db = get_db()
        job_id = _make_job(db)
        try:
            ns.notify_application(db, candidate["user_id"], job_id, "saved")
            row = ns.list_notifications(db, candidate["user_id"])[0]
            flat = f"{row['title']} {row['body']}".lower()
            for forbidden in ("deadline", "due by", "apply by", "expires"):
                assert forbidden not in flat
            assert not re.search(r"\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}", flat)
        finally:
            _delete_job(db, job_id)


def test_repeated_apply_does_not_duplicate_the_notification(app, candidate):
    from database.db import get_db

    with app.app_context():
        db = get_db()
        job_id = _make_job(db)
        try:
            assert ns.notify_application(db, candidate["user_id"], job_id, "saved") == 1
            assert ns.notify_application(db, candidate["user_id"], job_id, "saved") == 0
            # A real status change is a genuinely different event.
            assert ns.notify_application(db, candidate["user_id"], job_id, "applied") == 1
            assert len(ns.list_notifications(db, candidate["user_id"])) == 2
        finally:
            _delete_job(db, job_id)


# ------------------------------------------------------------------- routes ---


def test_list_endpoint_requires_login(app):
    client = app.test_client()
    response = client.get("/notifications/")
    assert response.status_code == 401


def test_bell_renders_empty_state_for_a_fresh_user(client):
    response = client.get("/notifications/?mark_read=1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["notifications"] == []
    assert payload["unread"] == 0


def test_drawer_fragment_has_an_empty_state(app, candidate):
    client = app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = candidate["user_id"]
    payload = client.get("/notifications/bell").get_json()
    assert payload["notifications"] == []
    assert "caught up" in payload["html"]


def test_read_endpoints_require_login(app):
    client = app.test_client()
    assert client.post("/notifications/read-all").status_code == 401
    assert client.post("/notifications/1/read").status_code == 401


def test_mark_as_read_url_is_built_with_the_real_id(app, client, candidate):
    """The bell's read request must target the clicked row, not the sentinel.

    The URL template renders as "/notifications/0/read", so the id has to be
    substituted as a whole path segment. An earlier end-anchored replace never
    matched (the URL ends in "/read"), so every click posted to
    /notifications/0/read and 404'd without persisting anything.
    """
    from database.db import get_db

    with app.app_context():
        db = get_db()
        ns.add_notification(db, candidate["user_id"], "opportunity",
                            "Clickable row", dedupe_key="click:1")
        row_id = ns.list_notifications(db, candidate["user_id"])[0]["id"]

    html = client.get("/opportunities/").get_data(as_text=True)
    assert "function readUrlFor(id)" in html
    # The substitution must replace the whole "/0/" segment.
    assert "readUrlTemplate.replace('/0/', '/' + encodeURIComponent(id) + '/')" in html
    # And the end-anchored form that silently broke must not come back.
    assert "replace(/\\/0$/," not in html
    assert "fetch(readUrlFor(id)" in html

    # The route really resolves for a real id, and really marks it read.
    response = client.post(f"/notifications/{row_id}/read")
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["unread"] == 0


def test_cannot_mark_another_users_notification_read(app, candidate):
    """Ownership is enforced, so this cannot be used to probe other users."""
    from database.db import get_db

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, career_status) "
                "VALUES ('Other', 'other-read@example.test', 'x', 'Fresher')"
            )
            other_id = cursor.lastrowid
        db.commit()
        ns.add_notification(db, other_id, "opportunity", "Private", dedupe_key="p:1")
        row = ns.list_notifications(db, other_id)[0]

    client = app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = candidate["user_id"]
    assert client.post(f"/notifications/{row['id']}/read").status_code == 404

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM users WHERE id = %s", (other_id,))
        db.commit()


def test_header_bell_is_present_and_opens_the_drawer(client):
    html = client.get("/opportunities/").get_data(as_text=True)
    assert 'id="notificationBell"' in html
    assert "toggleNotifications(event)" in html
    # The bell opens a right-side drawer, not the old floating dropdown.
    assert 'id="notificationDrawer"' in html
    assert 'id="notificationDrawerBody"' in html
    assert 'id="notificationDrawerClose"' in html
    assert 'id="notificationBackdrop"' in html
    assert 'id="notificationDropdown"' not in html
    assert 'id="notificationBadge"' in html
    # The drawer must be dismissible by backdrop and by Escape.
    assert "backdrop.addEventListener('click', closeDrawer)" in html
    assert "event.key === 'Escape'" in html


def _badge_html(html: str) -> str:
    """The opening span tag of the bell badge."""
    match = re.search(r'<span class="notification-badge[^"]*"[^>]*id="notificationBadge"', html)
    assert match, "bell badge span not found"
    return match.group(0)


def test_bell_marks_unread_count_on_every_page(app, client, candidate):
    """The badge count reaches the template without the page doing it."""
    from database.db import get_db

    with app.app_context():
        db = get_db()
        ns.add_notification(db, candidate["user_id"], "opportunity",
                            "Badge check", dedupe_key="badge:1")

    html = client.get("/applications/").get_data(as_text=True)
    badge = _badge_html(html)
    assert "is-hidden" not in badge
    assert ">1</span>" in html


def test_bell_badge_is_hidden_with_no_unread(client):
    html = client.get("/opportunities/").get_data(as_text=True)
    assert "is-hidden" in _badge_html(html)
