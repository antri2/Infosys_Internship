"""Profile page rendering: dates must never surface as placeholders.

A profile record can legitimately have only one of start_date / end_date (a
resume parser often extracts a graduation year with no start year). The page
used to render the missing side as a literal "?", which put a stray question
mark in front of the user.
"""
import pytest

from database.db import get_db


@pytest.fixture
def dated_user(app, candidate):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO education (user_id, institution, degree, field, "
                "start_date, end_date) VALUES (%s,'AKS University','B.Tech',"
                "'Computer Science',NULL,'2026')",
                (candidate["user_id"],),
            )
            cursor.execute(
                "INSERT INTO education (user_id, institution, degree, field, "
                "start_date, end_date) VALUES (%s,'Both Dates Uni','B.Tech',"
                "'CSE','2022','2026')",
                (candidate["user_id"],),
            )
            cursor.execute(
                "INSERT INTO education (user_id, institution, degree, field) "
                "VALUES (%s,'No Dates Uni','B.Tech','CSE')",
                (candidate["user_id"],),
            )
            cursor.execute(
                "INSERT INTO experience (user_id, title, organization, start_date, "
                "end_date) VALUES (%s,'Analyst','Acme','2025',NULL)",
                (candidate["user_id"],),
            )
        db.commit()
    return candidate


def test_profile_never_renders_a_question_mark_placeholder(client, dated_user):
    html = client.get("/profile/").get_data(as_text=True)

    assert "? &ndash;" not in html
    assert "? –" not in html
    # A single unknown side must not produce a bare "?" anywhere in the
    # education/experience blocks.
    assert "<div class=\"muted\" style=\"margin-top:2px\">?</div>" not in html


def test_single_date_is_rendered_as_a_labelled_range(client, dated_user):
    body = client.get("/profile/").get_data(as_text=True)

    assert "Until 2026" in body          # end_date only
    assert "From 2025" in body           # start_date only
    assert "2022 &ndash; 2026" in body   # both dates


def test_record_with_no_dates_renders_no_date_line(client, dated_user):
    body = client.get("/profile/").get_data(as_text=True)

    assert "No Dates Uni" in body
    # The institution is present but no From/Until/date line was invented for it.
    idx = body.index("No Dates Uni")
    window = body[idx: idx + 900]
    assert "Until" not in window.split("</div>")[0]