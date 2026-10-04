"""
MySQL connection handling. Every route gets a connection via get_db(),
which Flask reuses within one request and closes automatically afterward.

init_db() is intentionally limited to schema/migration setup. The canonical
job dataset is synchronized explicitly through Data/Loads_jobs_to_dataset.py
so normal Flask startup never rewrites all job rows.
"""
import re
from pathlib import Path

import pymysql
import pymysql.cursors
from flask import g

import config


BASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BASE_DIR / "schema.sql"
M3_MIGRATION_PATH = BASE_DIR / "migration_m3.sql"


def get_db():
    if "db" not in g:
        g.db = pymysql.connect(
            host=config.MYSQL_HOST,
            port=config.MYSQL_PORT,
            user=config.MYSQL_USER,
            password=config.MYSQL_PASSWORD,
            database=config.MYSQL_DATABASE,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
            charset="utf8mb4",
        )
    return g.db


def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    app.teardown_appcontext(close_db)


def _execute_sql_file(cursor, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    for statement in sql.split(";"):
        statement = statement.strip()
        if statement:
            cursor.execute(statement)


def _application_resume_fk_exists(cursor) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = %s
          AND TABLE_NAME = 'applications'
          AND COLUMN_NAME = 'resume_id'
          AND REFERENCED_TABLE_NAME = 'resumes'
          AND REFERENCED_COLUMN_NAME = 'id'
        """,
        (config.MYSQL_DATABASE,),
    )
    return cursor.fetchone()[0] > 0


def _ensure_application_resume_schema(cursor) -> None:
    """Apply the applications.resume_id upgrade safely to old databases."""
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s
          AND TABLE_NAME = 'applications'
          AND COLUMN_NAME = 'resume_id'
        """,
        (config.MYSQL_DATABASE,),
    )
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "ALTER TABLE applications ADD COLUMN resume_id INT NULL AFTER job_id"
        )

    # A saved application is not an applied application.
    cursor.execute(
        "ALTER TABLE applications MODIFY COLUMN applied_on TIMESTAMP NULL DEFAULT NULL"
    )

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = %s
          AND TABLE_NAME = 'applications'
          AND COLUMN_NAME = 'resume_id'
        """,
        (config.MYSQL_DATABASE,),
    )
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "ALTER TABLE applications ADD INDEX idx_applications_resume_id (resume_id)"
        )

    if not _application_resume_fk_exists(cursor):
        cursor.execute(
            """
            ALTER TABLE applications
            ADD CONSTRAINT fk_applications_resume_id
            FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE SET NULL
            """
        )


def _ensure_interview_plan_job_nullable(cursor) -> None:
    """Allow preparation plans for custom roles without a selected job."""
    cursor.execute(
        """
        SELECT IS_NULLABLE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s
          AND TABLE_NAME = 'interview_prep_plans'
          AND COLUMN_NAME = 'job_id'
        """,
        (config.MYSQL_DATABASE,),
    )
    row = cursor.fetchone()
    is_nullable = row[0] if isinstance(row, (tuple, list)) else row.get("IS_NULLABLE") if row else None
    if row and is_nullable != "YES":
        cursor.execute(
            "ALTER TABLE interview_prep_plans MODIFY COLUMN job_id INT NULL"
        )


def init_db():
    """Create/update the configured database schema without loading job data."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", config.MYSQL_DATABASE):
        raise ValueError("MYSQL_DATABASE may contain only letters, numbers, and underscores")

    connection = pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        charset="utf8mb4",
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{config.MYSQL_DATABASE}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cursor.execute(f"USE `{config.MYSQL_DATABASE}`")
            _execute_sql_file(cursor, SCHEMA_PATH)
            _execute_sql_file(cursor, M3_MIGRATION_PATH)
            _ensure_application_resume_schema(cursor)
            _ensure_interview_plan_job_nullable(cursor)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
