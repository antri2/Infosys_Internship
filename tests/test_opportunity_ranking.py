import routes.opportunities as opportunities_module
from database.db import get_db
from services.job_matcher import compute_match
from services.opportunity_service import recommend_jobs, search_jobs
from services.rag_service import semantic_search


def _add_profile_skills(app, user_id, skills):
    with app.app_context():
        connection = get_db()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM skills WHERE user_id = %s", (user_id,))
            for skill in skills:
                cursor.execute(
                    "INSERT INTO skills (user_id, name, category) VALUES (%s, %s, 'other')",
                    (user_id, skill),
                )
        connection.commit()


def test_relevant_semantic_query_passes_relevance_filter():
    results = semantic_search("JavaScript React frontend developer", top_k=10)

    assert results
    assert all(result["score"] >= 0.65 for result in results)
    assert all(result["semantic_label"] in {"moderate", "good", "strong"} for result in results)


def test_unrelated_semantic_query_returns_no_jobs():
    results = semantic_search(
        "quantum blockchain astrophysics underwater basket weaving",
        top_k=20,
    )

    assert results == []


def test_retrieval_failure_returns_empty_instead_of_csv_rows(monkeypatch):
    def broken_search(*args, **kwargs):
        raise RuntimeError("simulated vector failure")

    monkeypatch.setattr("services.rag_service.semantic_search", broken_search)

    assert search_jobs("Python", top_k=20) == []


def test_recommend_jobs_uses_larger_candidate_pool_and_final_limit(monkeypatch):
    captured = {}

    def fake_search(query, top_k=20, min_score=0.65):
        captured["query"] = query
        captured["top_k"] = top_k
        return [
            {
                "job_id": str(index),
                "title": f"Job {index}",
                "required_skills": "Python",
                "preferred_skills": "",
                "score": 0.70 + index / 100,
                "matched_chunk": "skills",
            }
            for index in range(1, 6)
        ]

    monkeypatch.setattr("services.rag_service.semantic_search", fake_search)
    results = recommend_jobs("", ["JS", "Python"], top_k=2)

    assert captured["query"] == "JavaScript, Python"
    assert captured["top_k"] == 6
    assert len(results) == 2
    assert results[0]["match_available"] is True


def test_opportunities_page_labels_score_and_shows_reasons(app, client, candidate):
    _add_profile_skills(app, candidate["user_id"], ["JS", "React.js", "PostgreSQL", "ML"])

    response = client.get("/opportunities/?q=JavaScript React frontend")

    assert response.status_code == 200
    assert b"Skill Fit" in response.data
    assert b"not a probability of getting the job" in response.data
    assert b"JavaScript" in response.data

    # The reasoning itself is rendered by the dialog rather than on every card,
    # so it is asserted where it now lives. The reasons are still carried into
    # the dialog per job.
    modal_js = open("static/js/job_modal.js", encoding="utf-8").read()
    assert "Why this matches your profile" in modal_js
    assert "Skills fit" in modal_js
    html = response.get_data(as_text=True)
    assert "data-match-reasons=" in html


def test_dashboard_uses_profile_skill_fit_label(app, client, candidate):
    _add_profile_skills(app, candidate["user_id"], ["Python", "SQL", "Statistics"])

    response = client.get("/home")

    assert response.status_code == 200
    assert b"Skill Fit" in response.data
    assert b"% Match" not in response.data


def test_dashboard_and_opportunities_use_shared_recommendation_logic(
    app, client, candidate, monkeypatch
):
    _add_profile_skills(app, candidate["user_id"], ["JavaScript", "React"])
    calls = []
    job = {
        "job_id": 1,
        "title": "Frontend Developer",
        "company": "Test Company",
        "location": "Remote",
        "job_type": "Full-time",
        "domain": "Web Development",
        "description": "Frontend role",
        "responsibilities": "Build UI",
        "required_skills": "JavaScript, React",
        "preferred_skills": "",
        "qualifications": "Graduate",
        "experience_required": "0-1 years",
        "education_required": "Graduate",
        "stipend_or_salary": "",
        "apply_link": "",
        "score": 0.80,
        "matched_chunk": "skills",
    }

    def fake_recommend(query, user_skills, top_k=20):
        calls.append({"query": query, "skills": user_skills, "top_k": top_k})
        return [{**job, **compute_match(user_skills, job, semantic_score=job["score"])}]

    monkeypatch.setattr(opportunities_module, "recommend_jobs", fake_recommend)
    monkeypatch.setattr("services.opportunity_service.recommend_jobs", fake_recommend)

    opportunities_response = client.get("/opportunities/?q=JavaScript React")
    dashboard_response = client.get("/home")

    assert opportunities_response.status_code == 200
    assert dashboard_response.status_code == 200
    # Both pages go through the same shared recommend_jobs(); Opportunities
    # asks for 20, the Dashboard asks for exactly the nine cards it renders.
    assert [call["top_k"] for call in calls] == [20, 9]
    assert b"Skill Fit" in opportunities_response.data
    assert b"Skill Fit" in dashboard_response.data


def test_public_search_rejects_invalid_top_k(client):
    assert client.get("/jobs/search?q=python&top_k=0").status_code == 400
    assert client.get("/jobs/search?q=python&top_k=101").status_code == 400
