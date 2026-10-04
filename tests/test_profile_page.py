"""Profile page: it must surface and edit exactly what the Resume Parser stored.

The assertions here deliberately read back through services/context_builder.py
wherever possible, so a profile edit is proven to reach the same data every other
feature already reads.
"""

import pytest

from database.db import get_db
from services.context_builder import get_candidate_context


def _seed_parsed_profile(app, user_id, resume_id):
    """Mirror exactly what routes/resume.py::_save_extracted_profile writes."""
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO profiles (user_id, resume_id, summary, cgpa)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE summary = VALUES(summary), cgpa = VALUES(cgpa)
                """,
                (
                    user_id,
                    resume_id,
                    "Final-year B.Tech student focused on machine learning systems.",
                    "8.66",
                ),
            )
            cursor.execute("DELETE FROM skills WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM education WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM experience WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM projects WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM certifications WHERE user_id = %s", (user_id,))

            for name, category in (
                ("Python", "programming_language"),
                ("SQL", "programming_language"),
                ("MySQL", "tool"),
                ("PyTorch", "framework"),
                ("TensorFlow", "framework"),
                ("Scikit-learn", "framework"),
            ):
                cursor.execute(
                    "INSERT INTO skills (user_id, name, category) VALUES (%s, %s, %s)",
                    (user_id, name, category),
                )

            for e in (
                ("AKS University", "B.Tech", "Computer Science", "2023", "2026"),
                ("AKS University", "Diploma", "Computer Science", "2020", "2023"),
            ):
                cursor.execute(
                    "INSERT INTO education (user_id, institution, degree, field, start_date, end_date) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (user_id, *e),
                )

            for x in (
                ("Artificial Intelligence Intern", "Infosys Springboard", "Aug 2026", "Present", "Built a retrieval pipeline."),
                ("Research Intern", "IISER", "May 2026", "Jul 2026", "Benchmarked transformer baselines."),
            ):
                cursor.execute(
                    "INSERT INTO experience (user_id, title, organization, start_date, end_date, description) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (user_id, *x),
                )

            for p in (
                ("Resume Ranker", "Ranked resumes against job descriptions.", "Python, FAISS, scikit-learn"),
                ("Traffic Predictor", "Predicted congestion on city roads.", "TensorFlow, Pandas"),
            ):
                cursor.execute(
                    "INSERT INTO projects (user_id, title, description, tech_stack) VALUES (%s, %s, %s, %s)",
                    (user_id, *p),
                )

            cursor.execute(
                "INSERT INTO certifications (user_id, name, issuer, issue_date, credential_url) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user_id, "AWS Certified Developer", "Amazon Web Services", "2025", "https://example.test/aws"),
            )
        db.commit()


@pytest.fixture
def parsed(app, candidate):
    """A candidate whose rows are exactly what the Resume Parser would write."""
    _seed_parsed_profile(app, candidate["user_id"], candidate["resume_id"])
    return candidate


# ---------------------------------------------------------------- display ---


def test_profile_page_renders_every_parsed_section(client, parsed):
    html = client.get("/profile/").get_data(as_text=True)

    # Personal
    assert "Final-year B.Tech student focused on machine learning systems." in html
    assert "8.66" in html

    # Skills
    for skill in ("Python", "SQL", "MySQL", "PyTorch", "TensorFlow", "Scikit-learn"):
        assert skill in html

    # Education: BOTH records, never just the first
    assert html.count("AKS University") >= 2
    assert "B.Tech" in html and "Diploma" in html
    assert "Computer Science" in html

    # Experience: BOTH positions, with their descriptions
    assert "Artificial Intelligence Intern" in html
    assert "Infosys Springboard" in html
    assert "Research Intern" in html and "IISER" in html
    assert "Built a retrieval pipeline." in html

    # Projects: previously loaded but never rendered
    assert "Resume Ranker" in html
    assert "Traffic Predictor" in html
    assert "FAISS" in html

    # Certifications: previously never even queried
    assert "AWS Certified Developer" in html
    assert "https://example.test/aws" in html


def test_profile_page_offers_add_edit_and_delete(client, parsed):
    html = client.get("/profile/").get_data(as_text=True)

    assert "+ Add Education" in html
    assert "+ Add Experience" in html
    assert "+ Add Project" in html
    assert "+ Add Certification" in html
    assert "+ Add Skills" in html
    # 2 education + 2 experience + 2 projects + 1 certification = 7 records,
    # each with exactly one Edit and one Delete form.
    assert html.count("/profile/record/delete") == 7
    assert html.count("/profile/record/update") == 7
    assert html.count("/profile/record/add") == 4


def test_profile_page_requires_login(app):
    client = app.test_client()
    response = client.get("/profile/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# ------------------------------------------------------------------ skills ---


def test_saving_details_no_longer_wipes_skill_categories(app, client, parsed):
    user_id = parsed["user_id"]

    client.post(
        "/profile/edit",
        data={"name": "Renamed Candidate", "phone": "9998887776", "college": "Test University"},
    )

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT name, category FROM skills WHERE user_id = %s", (user_id,))
            skills = {row["name"]: row["category"] for row in cursor.fetchall()}

    # The old implementation deleted every skill and re-inserted it without a
    # category, destroying the parser's grouping.
    assert skills["Python"] == "programming_language"
    assert skills["PyTorch"] == "framework"
    assert skills["MySQL"] == "tool"
    assert len(skills) == 6


def test_edit_persists_personal_and_academic_fields(app, client, candidate):
    user_id = candidate["user_id"]
    client.post(
        "/profile/edit",
        data={
            "name": "Ada Lovelace",
            "phone": "+91 90000 00000",
            "career_status": "Experienced",
            "college": "New College",
            "degree": "M.Tech",
            "passing_year": "2027",
            "cgpa": "9.1",
            "summary": "ML engineer.",
            "experience": "Anything else worth noting.",
        },
    )

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT name, phone, career_status FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            cursor.execute(
                "SELECT college, degree, passing_year, cgpa, summary, experience FROM profiles WHERE user_id = %s",
                (user_id,),
            )
            profile = cursor.fetchone()

    assert (user["name"], user["phone"], user["career_status"]) == (
        "Ada Lovelace",
        "+91 90000 00000",
        "Experienced",
    )
    assert profile["college"] == "New College"
    assert profile["degree"] == "M.Tech"
    assert profile["passing_year"] == 2027
    assert float(profile["cgpa"]) == 9.1
    assert profile["summary"] == "ML engineer."
    assert profile["experience"] == "Anything else worth noting."


def test_edit_ignores_non_numeric_cgpa_and_passing_year(app, client, parsed):
    user_id = parsed["user_id"]

    client.post("/profile/edit", data={"cgpa": "not-a-number", "passing_year": "soon"})

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT cgpa, passing_year FROM profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()

    # Invalid input is discarded, the previously stored value survives.
    assert float(row["cgpa"]) == 8.66
    assert row["passing_year"] is None


def test_edit_ignores_unknown_career_status(app, client, candidate):
    user_id = candidate["user_id"]
    client.post("/profile/edit", data={"career_status": "Intergalactic"})
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT career_status FROM users WHERE id = %s", (user_id,))
            assert cursor.fetchone()["career_status"] == "Fresher"


def test_add_skills_normalizes_and_skips_duplicates(app, client, parsed):
    user_id = parsed["user_id"]

    client.post(
        "/profile/skill/add",
        data={"skills": "js, React.js,  postgresql , Python,", "category": "framework"},
    )

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT name, category FROM skills WHERE user_id = %s", (user_id,))
            skills = {row["name"]: row["category"] for row in cursor.fetchall()}

    assert skills["JavaScript"] == "framework"
    assert skills["React"] == "framework"
    assert skills["Postgres"] == "framework"
    # "Python" already existed, so it must not be duplicated or recategorized.
    assert skills["Python"] == "programming_language"
    assert len(skills) == 9


def test_skill_update_renames_and_preserves_category_when_untouched(app, client, parsed):
    user_id = parsed["user_id"]

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT id FROM skills WHERE user_id = %s AND name = 'PyTorch'", (user_id,))
            skill_id = cursor.fetchone()["id"]

    client.post("/profile/skill/update", data={"skill_id": str(skill_id), "name": "Torch", "category": ""})

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT name, category FROM skills WHERE id = %s AND user_id = %s", (skill_id, user_id))
            row = cursor.fetchone()

    assert row["name"] == "Torch"
    assert row["category"] == "framework"


def test_skill_delete_removes_only_that_row(app, client, parsed):
    user_id = parsed["user_id"]

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT id FROM skills WHERE user_id = %s AND name = 'SQL'", (user_id,))
            skill_id = cursor.fetchone()["id"]

    client.post("/profile/skill/delete", data={"skill_id": str(skill_id)})

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT name FROM skills WHERE user_id = %s", (user_id,))
            names = [row["name"] for row in cursor.fetchall()]

    assert "SQL" not in names
    assert "Python" in names


# ----------------------------------------------------------------- records ---


@pytest.mark.parametrize(
    "record_type,payload,table,expected_column",
    [
        (
            "education",
            {"institution": "New University", "degree": "B.Sc", "field": "Maths", "start_date": "2024", "end_date": "2027"},
            "education",
            "institution",
        ),
        (
            "experience",
            {"title": "Data Analyst", "organization": "Acme", "start_date": "Jun 2025", "end_date": "Dec 2025", "description": "Dashboards."},
            "experience",
            "title",
        ),
        (
            "projects",
            {"title": "Chatbot", "description": "A bot.", "tech_stack": "Python, Flask"},
            "projects",
            "title",
        ),
        (
            "certifications",
            {"name": "TensorFlow Developer", "issuer": "Google", "issue_date": "2025", "expiry_date": "", "credential_url": "https://example.test/tf"},
            "certifications",
            "name",
        ),
    ],
)
def test_add_record_persists_to_the_parser_table(app, client, candidate, record_type, payload, table, expected_column):
    user_id = candidate["user_id"]
    client.post("/profile/record/add", data={"record_type": record_type, **payload})

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {table} WHERE user_id = %s", (user_id,))
            rows = cursor.fetchall()

    assert any(row[expected_column] == payload[expected_column] for row in rows)

    html = client.get("/profile/").get_data(as_text=True)
    assert payload[expected_column] in html


def test_add_record_without_required_field_is_rejected(app, client, candidate):
    user_id = candidate["user_id"]
    before = _count(app, "projects", user_id)

    response = client.post("/profile/record/add", data={"record_type": "projects", "title": "  "})

    assert response.status_code == 302
    assert _count(app, "projects", user_id) == before


def test_added_records_reach_the_candidate_context(app, client, parsed):
    user_id = parsed["user_id"]
    client.post(
        "/profile/record/add",
        data={"record_type": "projects", "title": "Fraud Detector", "description": "XGBoost model.", "tech_stack": "Python"},
    )
    client.post(
        "/profile/record/add",
        data={"record_type": "certifications", "name": "Azure AI Engineer", "issuer": "Microsoft"},
    )

    with app.app_context():
        context = get_candidate_context(get_db(), user_id)

    assert any(p["title"] == "Fraud Detector" for p in context["projects"])
    assert any(c["name"] == "Azure AI Engineer" for c in context["certifications"])


def test_update_record_changes_the_stored_row(app, client, parsed):
    user_id = parsed["user_id"]
    record_id = _one_id(app, "projects", user_id, "title", "Resume Ranker")

    client.post(
        "/profile/record/update",
        data={
            "record_type": "projects",
            "record_id": str(record_id),
            "title": "Resume Ranker v2",
            "description": "Now with re-ranking.",
            "tech_stack": "Python, FAISS",
        },
    )

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT title, description FROM projects WHERE id = %s AND user_id = %s", (record_id, user_id))
            row = cursor.fetchone()

    assert row["title"] == "Resume Ranker v2"
    assert row["description"] == "Now with re-ranking."


def test_delete_record_removes_only_that_row(app, client, parsed):
    user_id = parsed["user_id"]
    record_id = _one_id(app, "education", user_id, "degree", "Diploma")

    client.post("/profile/record/delete", data={"record_type": "education", "record_id": str(record_id)})

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT degree FROM education WHERE user_id = %s", (user_id,))
            degrees = [row["degree"] for row in cursor.fetchall()]

    # B.Tech must survive; only the targeted row is removed.
    assert degrees == ["B.Tech"]


def test_cannot_edit_or_delete_another_users_record(app, client, candidate):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, career_status) VALUES ('Other', 'other@example.test', 'x', 'Fresher')"
            )
            other_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO projects (user_id, title) VALUES (%s, 'Secret Project')", (other_id,)
            )
            other_project = cursor.lastrowid
        db.commit()

    try:
        client.post(
            "/profile/record/update",
            data={"record_type": "projects", "record_id": str(other_project), "title": "Hijacked"},
        )
        client.post("/profile/record/delete", data={"record_type": "projects", "record_id": str(other_project)})

        with app.app_context():
            db = get_db()
            with db.cursor() as cursor:
                cursor.execute("SELECT title FROM projects WHERE id = %s", (other_project,))
                assert cursor.fetchone()["title"] == "Secret Project"
    finally:
        with app.app_context():
            db = get_db()
            with db.cursor() as cursor:
                cursor.execute("DELETE FROM users WHERE id = %s", (other_id,))
            db.commit()


@pytest.mark.parametrize(
    "hostile",
    [
        "users; DROP TABLE users; --",
        "education WHERE 1=1",
        "__nonexistent__",
    ],
)
def test_hostile_record_type_cannot_reach_the_sql_layer(client, hostile):
    response = client.post("/profile/record/delete", data={"record_type": hostile, "record_id": "1"})
    assert response.status_code == 302
    # The candidates table is still there.
    assert client.get("/profile/").status_code == 200


def test_non_numeric_record_id_is_rejected(client):
    response = client.post("/profile/record/delete", data={"record_type": "projects", "record_id": "abc"})
    assert response.status_code == 302
    assert client.get("/profile/").status_code == 200


def test_every_mutation_requires_login(app):
    client = app.test_client()
    for path, data in (
        ("/profile/edit", {"name": "X"}),
        ("/profile/record/add", {"record_type": "projects", "title": "X"}),
        ("/profile/record/update", {"record_type": "projects", "record_id": "1", "title": "X"}),
        ("/profile/record/delete", {"record_type": "projects", "record_id": "1"}),
        ("/profile/skill/add", {"skills": "Rust"}),
        ("/profile/skill/update", {"skill_id": "1", "name": "Rust"}),
        ("/profile/skill/delete", {"skill_id": "1"}),
    ):
        response = client.post(path, data=data)
        assert response.status_code == 302, path
        assert "/login" in response.headers["Location"], path


# ----------------------------------------------------------------- helpers ---


def _count(app, table, user_id):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = %s", (user_id,))
            return cursor.fetchone()["n"]


def _one_id(app, table, user_id, column, value):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                f"SELECT id FROM {table} WHERE user_id = %s AND {column} = %s", (user_id, value)
            )
            return cursor.fetchone()["id"]
