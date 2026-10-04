"""Profile-completeness logic behind the Dashboard's Profile Completeness card.

These assertions call _build_checklist() directly on real database rows instead
of scraping the rendered Dashboard. The Dashboard redesign removed the large
profile-completion widget and the Profile & Resume Status checklist, so the
markup is no longer a stable place to assert the logic -- and asserting the
logic itself is stronger anyway.
"""

import uuid

import pytest

from database.db import get_db
from routes.profile import _build_checklist, _load_profile


def _checklist_for(app, user_id):
    with app.app_context():
        db = get_db()
        profile = _load_profile(db, user_id)
        checklist = _build_checklist(db, user_id, profile)
        completeness = round(sum(1 for c in checklist if c["done"]) / len(checklist) * 100)
        return {c["name"]: c["done"] for c in checklist}, completeness


def _make(app, *, education=(), cgpa=None, college=None, degree=None, skills=True):
    """Create one user with an exactly-specified profile state."""
    marker = uuid.uuid4().hex[:10]
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (name, email, phone, password_hash, career_status) "
                "VALUES (%s, %s, %s, 'x', 'Fresher')",
                (f"Edu {marker}", f"edu-{marker}@example.test", "+91 90000 00000"),
            )
            user_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO resumes (user_id, file_path, file_type, parse_status) "
                "VALUES (%s, %s, 'pdf', 'parsed')",
                (user_id, f"test/{marker}.pdf"),
            )
            resume_id = cursor.lastrowid
            for institution, edu_degree in education:
                cursor.execute(
                    "INSERT INTO education (user_id, institution, degree, start_date, end_date) "
                    "VALUES (%s, %s, %s, '2023', '2026')",
                    (user_id, institution, edu_degree),
                )
            cursor.execute(
                "INSERT INTO profiles (user_id, resume_id, college, degree, cgpa) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user_id, resume_id, college, degree, cgpa),
            )
            if skills:
                cursor.execute(
                    "INSERT INTO skills (user_id, name, category) VALUES (%s, 'Python', 'tool')",
                    (user_id,),
                )
        db.commit()
    return user_id


@pytest.fixture
def state(app, candidate):
    def _render(**kwargs):
        user_id = _make(app, **kwargs)
        try:
            return _checklist_for(app, user_id)
        finally:
            with app.app_context():
                db = get_db()
                with db.cursor() as cursor:
                    cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
                db.commit()

    return _render


# ------------------------------------------------------- the reported bug ---


def test_single_btech_record_with_no_cgpa_is_complete(state):
    """The exact reported case: one B.Tech, no CGPA anywhere."""
    items, _ = state(education=[("AKS University", "B.Tech")], college="AKS University", degree="B.Tech")
    assert items["Education Details"] is True


def test_single_btech_with_cgpa_still_complete(state):
    items, _ = state(
        education=[("AKS University", "B.Tech")], cgpa="8.66", college="AKS University", degree="B.Tech"
    )
    assert items["Education Details"] is True


def test_cgpa_is_not_required(state):
    """With and without CGPA the verdict must be identical."""
    with_cgpa, _ = state(
        education=[("AKS University", "B.Tech")], cgpa="8.66", college="AKS University", degree="B.Tech"
    )
    without_cgpa, _ = state(education=[("AKS University", "B.Tech")], college="AKS University", degree="B.Tech")
    assert with_cgpa["Education Details"] == without_cgpa["Education Details"] is True


def test_two_records_are_not_required(state):
    """Diploma + B.Tech is not the bar; one record is enough."""
    one, pct_one = state(education=[("AKS University", "B.Tech")], college="AKS University", degree="B.Tech")
    two, pct_two = state(
        education=[("AKS University", "Diploma"), ("AKS University", "B.Tech")],
        college="AKS University",
        degree="Diploma",
    )
    assert one["Education Details"] is True
    assert two["Education Details"] is True
    # Adding a second degree must not move the percentage.
    assert pct_one == pct_two


def test_degree_only_record_counts_when_institution_missing(state):
    items, _ = state(education=[("", "B.Tech")])
    assert items["Education Details"] is True


# ------------------------------------------------------------ still honest ---


def test_no_education_at_all_stays_pending(state):
    items, _ = state()
    assert items["Education Details"] is False


def test_blank_education_row_is_not_a_valid_record(state):
    items, _ = state(education=[("", "")])
    assert items["Education Details"] is False


def test_manually_entered_college_and_degree_still_count(state):
    """The Profile page lets a user type college/degree with no education row."""
    items, _ = state(college="AKS University", degree="B.Tech")
    assert items["Education Details"] is True


# ------------------------------------------------------------- percentage ---


def test_overall_percentage_updates_with_education(state):
    without_edu, pct_without = state()
    with_edu, pct_with = state(education=[("AKS University", "B.Tech")])
    assert without_edu["Education Details"] is False
    assert with_edu["Education Details"] is True
    assert int(pct_with) > int(pct_without)


def test_percentage_matches_the_ratio_of_completed_items(state):
    items, pct = state(education=[("AKS University", "B.Tech")], college="AKS University", degree="B.Tech")
    assert len(items) == 6
    assert int(pct) == round(sum(items.values()) / len(items) * 100)


def test_checklist_shape_is_unchanged(state):
    """The redesign must not alter which sections the logic tracks."""
    items, _ = state()
    assert set(items) == {
        "Personal Information",
        "Education Details",
        "Skills",
        "Experience",
        "Projects",
        "Resume Uploaded",
    }