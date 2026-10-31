import os
import re
import uuid
from pathlib import Path

import pymysql
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE = os.getenv("CAREERAI_TEST_DATABASE", "career_ai_step1_test")

if not re.fullmatch(r"career_ai_[A-Za-z0-9_]+", TEST_DATABASE):
    raise RuntimeError("CAREERAI_TEST_DATABASE must be an isolated career_ai_* test database")

# This must happen before config is imported. Environment variables take
# precedence over values from .env when python-dotenv is called.
os.environ["MYSQL_DATABASE"] = TEST_DATABASE

# Keep the suite hermetic and offline. A developer machine usually has real
# Adzuna credentials in .env, and without this the tests would silently make
# live network calls and assert against whatever Adzuna happened to return.
# Tests that exercise the live path stub the transport and credentials
# themselves (see tests/test_adzuna_service.py), so they still run in full.
os.environ["ADZUNA_ENABLED"] = "false"

from Data.Loads_jobs_to_dataset import read_clean_jobs, sync_jobs, verify_jobs  # noqa: E402
from app import create_app  # noqa: E402
from database import db  # noqa: E402
from database.db import get_db  # noqa: E402
from services.rag_service import validate_store_against_csv  # noqa: E402


def _admin_connection(database=None):
    import config

    return pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=database,
        charset="utf8mb4",
        autocommit=True,
    )


@pytest.fixture(scope="session", autouse=True)
def step1_database():
    connection = _admin_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{TEST_DATABASE}`")
    finally:
        connection.close()

    db.init_db()

    connection = _admin_connection(TEST_DATABASE)
    try:
        jobs = read_clean_jobs()
        assert sync_jobs(connection, jobs) == 185
        # A second explicit synchronization must be safe.
        assert sync_jobs(connection, jobs) == 185
        assert verify_jobs(connection, jobs)["canonical_count"] == 185
    finally:
        connection.close()

    vector_result = validate_store_against_csv()
    assert vector_result["job_count"] == 185
    assert vector_result["vector_count"] == 370
    assert vector_result["dimension"] == 384

    yield

    connection = _admin_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{TEST_DATABASE}`")
    finally:
        connection.close()


@pytest.fixture(scope="session")
def app(step1_database):
    application = create_app()
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def candidate(app):
    marker = uuid.uuid4().hex[:12]
    user_id = None
    resume_id = None

    with app.app_context():
        connection = get_db()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, career_status) VALUES (%s, %s, %s, 'Fresher')",
                (f"Step1 {marker}", f"step1-{marker}@example.test", "not-used-in-tests"),
            )
            user_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO resumes (user_id, file_path, file_type, parse_status)
                VALUES (%s, %s, 'pdf', 'parsed')
                """,
                (user_id, f"test/{marker}.pdf"),
            )
            resume_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO profiles (user_id, resume_id, college, degree, cgpa)
                VALUES (%s, %s, 'Test University', 'B.Tech', 8.5)
                """,
                (user_id, resume_id),
            )
            cursor.execute(
                """
                INSERT INTO certifications (user_id, name, issuer)
                VALUES (%s, 'AWS Certified Developer', 'Test Issuer')
                """,
                (user_id,),
            )
        connection.commit()

    yield {
        "user_id": user_id,
        "resume_id": resume_id,
        "email": f"step1-{marker}@example.test",
    }

    with app.app_context():
        connection = get_db()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        connection.commit()


@pytest.fixture
def client(app, candidate):
    test_client = app.test_client()
    with test_client.session_transaction() as flask_session:
        flask_session["user_id"] = candidate["user_id"]
        flask_session["user_name"] = "Step1 Candidate"
    return test_client
