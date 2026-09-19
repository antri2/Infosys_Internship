"""
M2.1 -- Load the cleaned dataset into MySQL.

Reads data/jobs_clean.csv and upserts every row into the `jobs` table.
Safe to run multiple times -- existing job_ids are updated, not
duplicated.

Run (from the career_ai/ folder, so `config` and `database` import
correctly):
    python data/load_jobs_to_db.py
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql
import config

CLEAN_PATH = Path(__file__).resolve().parent / "jobs_clean.csv"

COLUMNS = [
    "job_id", "title", "company", "location", "job_type", "domain",
    "description", "responsibilities", "required_skills", "preferred_skills",
    "qualifications", "experience_required", "education_required",
    "stipend_or_salary", "apply_link",
]


def main():
    with open(CLEAN_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    connection = pymysql.connect(
        host=config.MYSQL_HOST, port=config.MYSQL_PORT,
        user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
    )
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    update_clause = ", ".join(f"{c}=VALUES({c})" for c in COLUMNS if c != "job_id")
    sql = (
        f"INSERT INTO jobs ({', '.join(COLUMNS)}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_clause}"
    )

    try:
        with connection.cursor() as cursor:
            for row in rows:
                values = [row.get(c, "") for c in COLUMNS]
                cursor.execute(sql, values)
        connection.commit()
        print(f"Loaded {len(rows)} jobs into the `jobs` table.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()