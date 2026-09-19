"""
MySQL connection handling. Every route gets a connection via get_db(),
which Flask reuses within one request and closes automatically afterward.
"""
import pymysql
import pymysql.cursors
from flask import g

import config


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
        )
    return g.db


def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    app.teardown_appcontext(close_db)


def init_db():
    """Creates all tables if they don't already exist. Run once at startup."""
    schema_path = __file__.replace("db.py", "schema.sql")
    with open(schema_path, "r") as f:
        schema_sql = f.read()

    connection = pymysql.connect(
        host=config.MYSQL_HOST, port=config.MYSQL_PORT,
        user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
    )
    try:
        with connection.cursor() as cursor:
            for statement in schema_sql.split(";"):
                statement = statement.strip()
                if statement:
                    cursor.execute(statement)
        connection.commit()
    finally:
        connection.close()
