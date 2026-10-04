import csv
import json
from pathlib import Path

from Data.Loads_jobs_to_dataset import read_clean_jobs, verify_jobs
from database import db
from database.db import get_db
from services.context_builder import flatten_candidate_text, get_candidate_context
from services.rag_service import validate_store_against_csv
from services.resume_parser import _parse_llm_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _mysql_job_ids(app):
    with app.app_context():
        connection = get_db()
        with connection.cursor() as cursor:
            cursor.execute("SELECT job_id FROM jobs ORDER BY job_id")
            return [int(row["job_id"]) for row in cursor.fetchall()]


def test_csv_faiss_and_mysql_canonical_job_ids_match(app):
    with open(PROJECT_ROOT / "Data/jobs_clean.csv", newline="", encoding="utf-8-sig") as f:
        csv_ids = {int(row["job_id"]) for row in csv.DictReader(f)}
    lookup = json.loads(
        (PROJECT_ROOT / "Data/vector_store/jobs_lookup.json").read_text(encoding="utf-8")
    )
    faiss_ids = {int(job_id) for job_id in lookup}
    mysql_ids = set(_mysql_job_ids(app))

    assert len(csv_ids) == 185
    assert csv_ids == faiss_ids
    assert csv_ids == mysql_ids
    assert validate_store_against_csv() == {
        "job_count": 185,
        "vector_count": 370,
        "dimension": 384,
    }


def test_explicit_job_sync_verifies_every_canonical_row(app):
    jobs = read_clean_jobs()
    with app.app_context():
        result = verify_jobs(get_db(), jobs)
    assert result == {"canonical_count": 185, "verified_count": 185}


def test_schema_init_does_not_reload_or_duplicate_jobs(app):
    before = _mysql_job_ids(app)
    db.init_db()
    after = _mysql_job_ids(app)

    assert before == after
    assert len(after) == 185


def test_fresh_schema_contains_step1_and_existing_m3_tables(app):
    required = {
        "certifications",
        "cover_letters",
        "skill_gap_reports",
        "tailored_resumes",
    }
    with app.app_context():
        connection = get_db()
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            tables = {next(iter(row.values())) for row in cursor.fetchall()}
            cursor.execute("SHOW COLUMNS FROM applications LIKE 'resume_id'")
            assert cursor.fetchone() is not None
    assert required.issubset(tables)


def test_certifications_are_optional_and_normalized_in_parser_output():
    base = {
        "summary": None,
        "skills": [],
        "education": [],
        "experience": [],
        "projects": [],
        "cgpa": None,
    }
    assert _parse_llm_output(json.dumps(base))["certifications"] == []

    base["certifications"] = ["invalid", {"name": "AWS", "issuer": "Amazon"}]
    parsed = _parse_llm_output(json.dumps(base))
    assert parsed["certifications"] == [{"name": "AWS", "issuer": "Amazon"}]


def test_cgpa_and_certification_context_loads_without_schema_error(app, candidate):
    with app.app_context():
        context = get_candidate_context(get_db(), candidate["user_id"])

    assert float(context["cgpa"]) == 8.5
    assert context["resume"]["id"] == candidate["resume_id"]
    assert context["certifications"][0]["name"] == "AWS Certified Developer"
    assert "CGPA: 8.5" in flatten_candidate_text(context)
