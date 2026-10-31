from database.db import get_db


def _first_job(app):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT job_id, title FROM jobs ORDER BY job_id LIMIT 1")
            return cursor.fetchone()


def _first_jobs(app, limit=2):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT job_id, title FROM jobs ORDER BY job_id LIMIT %s", (limit,)
            )
            return cursor.fetchall()


def _application_rows(app, user_id, job_id):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT job_id, status, resume_id, applied_on FROM applications WHERE user_id = %s AND job_id = %s",
                (user_id, job_id),
            )
            return cursor.fetchall()


def _set_status(app, user_id, job_id, status):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "UPDATE applications SET status = %s WHERE user_id = %s AND job_id = %s",
                (status, user_id, job_id),
            )
        db.commit()


def test_save_creates_saved_application_with_current_resume(app, client, candidate):
    job = _first_job(app)

    response = client.post(f"/applications/{job['job_id']}/save")

    assert response.status_code == 201
    assert response.get_json()["status"] == "saved"
    rows = _application_rows(app, candidate["user_id"], job["job_id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "saved"
    assert rows[0]["resume_id"] == candidate["resume_id"]
    assert rows[0]["applied_on"] is None


def test_repeated_save_is_idempotent(app, client, candidate):
    job = _first_job(app)

    first = client.post(f"/applications/{job['job_id']}/save")
    second = client.post(f"/applications/{job['job_id']}/save")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["created"] is False
    assert len(_application_rows(app, candidate["user_id"], job["job_id"])) == 1


def test_save_does_not_downgrade_interview_status(app, client, candidate):
    job = _first_job(app)
    client.post(f"/applications/{job['job_id']}/save")
    _set_status(app, candidate["user_id"], job["job_id"], "interview")

    response = client.post(f"/applications/{job['job_id']}/save")

    assert response.status_code == 200
    assert response.get_json()["status"] == "interview"
    assert "preserved" in response.get_json()["message"]
    assert len(_application_rows(app, candidate["user_id"], job["job_id"])) == 1


def test_apply_creates_applied_application(app, client, candidate):
    job = _first_job(app)

    response = client.post(f"/applications/{job['job_id']}/apply")

    assert response.status_code == 201
    assert response.get_json()["status"] == "applied"
    rows = _application_rows(app, candidate["user_id"], job["job_id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "applied"
    assert rows[0]["resume_id"] == candidate["resume_id"]
    assert rows[0]["applied_on"] is not None


def test_save_then_apply_transition(app, client, candidate):
    job = _first_job(app)

    saved = client.post(f"/applications/{job['job_id']}/save")
    applied = client.post(f"/applications/{job['job_id']}/apply")

    assert saved.get_json()["status"] == "saved"
    assert applied.status_code == 200
    assert applied.get_json()["status"] == "applied"
    rows = _application_rows(app, candidate["user_id"], job["job_id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "applied"
    assert rows[0]["applied_on"] is not None


def test_repeated_apply_preserves_interview_status(app, client, candidate):
    job = _first_job(app)
    client.post(f"/applications/{job['job_id']}/apply")
    _set_status(app, candidate["user_id"], job["job_id"], "interview")

    response = client.post(f"/applications/{job['job_id']}/apply")

    assert response.status_code == 200
    assert response.get_json()["status"] == "interview"
    assert "preserved" in response.get_json()["message"]
    assert len(_application_rows(app, candidate["user_id"], job["job_id"])) == 1


def test_repeated_apply_preserves_rejected_status(app, client, candidate):
    job = _first_job(app)
    client.post(f"/applications/{job['job_id']}/apply")
    _set_status(app, candidate["user_id"], job["job_id"], "rejected")

    response = client.post(f"/applications/{job['job_id']}/apply")

    assert response.status_code == 200
    assert response.get_json()["status"] == "rejected"
    assert len(_application_rows(app, candidate["user_id"], job["job_id"])) == 1


def test_saved_and_applied_jobs_appear_in_my_applications(app, client, candidate):
    saved_job, applied_job = _first_jobs(app)

    assert client.post(f"/applications/{saved_job['job_id']}/save").status_code == 201
    assert client.post(f"/applications/{applied_job['job_id']}/apply").status_code == 201

    response = client.get("/applications/")

    assert response.status_code == 200
    assert saved_job["title"].encode() in response.data
    assert applied_job["title"].encode() in response.data
    assert b"Saved" in response.data
    assert b"Applied" in response.data


def test_missing_job_returns_json_404(app, client):
    response = client.post("/applications/999999999/save")

    assert response.status_code == 404
    assert response.is_json
    assert "could not be found" in response.get_json()["error"]
