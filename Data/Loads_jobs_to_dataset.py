"""
M2.1 -- Explicitly load the cleaned canonical dataset into MySQL.

Reads Data/jobs_clean.csv and idempotently upserts every row into `jobs`.
This is intentionally not called during normal Flask startup. Run it after
schema initialization and whenever the canonical dataset changes:

    python Data/Loads_jobs_to_dataset.py
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql
import pymysql.cursors

import config


DATA_DIR = Path(__file__).resolve().parent
CLEAN_PATH = DATA_DIR / "jobs_clean.csv"

COLUMNS = [
    "job_id", "title", "company", "location", "job_type", "domain",
    "description", "responsibilities", "required_skills", "preferred_skills",
    "qualifications", "experience_required", "education_required",
    "stipend_or_salary", "apply_link",
]


def read_clean_jobs(path: Path = CLEAN_PATH) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _values_for_row(row: dict) -> list:
    values = [row.get(column, "") for column in COLUMNS]
    values[0] = int(values[0])
    return values


def sync_jobs(connection, jobs: list[dict] | None = None) -> int:
    """Upsert canonical jobs without deleting unrelated existing jobs."""
    rows = read_clean_jobs() if jobs is None else jobs
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    update_clause = ", ".join(
        f"{column}=VALUES({column})"
        for column in COLUMNS
        if column != "job_id"
    )
    sql = (
        f"INSERT INTO jobs ({', '.join(COLUMNS)}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_clause}"
    )

    with connection.cursor() as cursor:
        for row in rows:
            cursor.execute(sql, _values_for_row(row))
    connection.commit()
    return len(rows)


def verify_jobs(connection, jobs: list[dict] | None = None) -> dict:
    """Verify every canonical CSV row exists with identical loader data."""
    rows = read_clean_jobs() if jobs is None else jobs
    expected = {int(row["job_id"]): row for row in rows}

    with connection.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute(
            f"SELECT {', '.join(COLUMNS)} FROM jobs WHERE job_id IN "
            f"({', '.join(['%s'] * len(expected))})",
            tuple(expected),
        )
        actual = {int(row["job_id"]): row for row in cursor.fetchall()}

    missing_ids = sorted(set(expected) - set(actual))
    mismatched_ids = []
    for job_id in sorted(set(expected) & set(actual)):
        for column in COLUMNS:
            expected_value = str(expected[job_id].get(column, "") or "")
            actual_value = str(actual[job_id].get(column, "") or "")
            if expected_value != actual_value:
                mismatched_ids.append((job_id, column))
                break

    if missing_ids or mismatched_ids:
        raise RuntimeError(
            "Canonical job verification failed: "
            f"missing_ids={missing_ids[:10]}, "
            f"mismatched={mismatched_ids[:10]}"
        )

    return {"canonical_count": len(expected), "verified_count": len(actual)}


def main() -> None:
    jobs = read_clean_jobs()
    connection = pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset="utf8mb4",
    )
    try:
        loaded = sync_jobs(connection, jobs)
        database_result = verify_jobs(connection, jobs)
    finally:
        connection.close()

    from services.rag_service import validate_store_against_csv

    vector_result = validate_store_against_csv()

    print(
        f"Synchronized and verified {loaded} canonical jobs in "
        f"`{config.MYSQL_DATABASE}`."
    )
    print(
        f"FAISS verification: {vector_result['job_count']} jobs, "
        f"{vector_result['vector_count']} vectors, "
        f"dimension {vector_result['dimension']}."
    )
    print(database_result)


if __name__ == "__main__":
    main()
