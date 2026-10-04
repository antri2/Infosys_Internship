from services.job_matcher import compute_match, rank_jobs


def test_confirmed_aliases_match_canonical_job_skills():
    job = {
        "required_skills": "JavaScript, React, Postgres, Machine Learning",
        "preferred_skills": "Node.js, ML",
        "score": 0.82,
        "matched_chunk": "skills",
    }
    result = compute_match(["JS", "React.js", "PostgreSQL", "ML", "Node.js"], job)

    assert result["matched_skills"] == [
        "JavaScript",
        "React",
        "Postgres",
        "Machine Learning",
    ]
    assert result["missing_skills"] == []
    assert result["matched_preferred"] == ["Node.js", "Machine Learning"]
    assert result["match_percent"] == 100


def test_profile_skill_fit_uses_required_and_preferred_weights():
    job = {
        "required_skills": "JavaScript, React, Postgres, Machine Learning",
        "preferred_skills": "Node.js, Docker",
    }
    result = compute_match(["JS", "React.js", "PostgreSQL", "Docker"], job, semantic_score=0.78)

    # 3/4 required and 1/2 preferred: 85% * 0.75 + 15% * 0.5.
    assert result["match_percent"] == 71
    assert result["missing_skills"] == ["Machine Learning"]
    assert result["matched_preferred"] == ["Docker"]
    assert result["missing_preferred"] == ["Node.js"]


def test_match_reasons_are_understandable_and_deterministic():
    job = {
        "required_skills": "Python, SQL",
        "preferred_skills": "AWS",
        "score": 0.83,
        "matched_chunk": "skills",
    }
    result = compute_match(["Python"], job)

    joined = " ".join(result["match_reasons"])
    assert "Strong semantic match" in joined
    assert "1 of 2 required skills: Python" in joined
    assert "Missing required skills: SQL" in joined
    assert "Preferred skills not yet" in joined


def test_no_profile_skills_produces_semantic_only_result():
    job = {"required_skills": "Python", "preferred_skills": "SQL", "score": 0.79}
    result = compute_match([], job)

    assert result["match_available"] is False
    assert result["match_percent"] is None
    assert result["ranking_score"] == 0.79
    assert "Add skills" in " ".join(result["match_reasons"])


def test_combined_ranking_uses_semantic_and_required_skills():
    jobs = [
        {
            "job_id": "1",
            "required_skills": "Python, SQL, Docker, Git",
            "preferred_skills": "",
            "score": 0.80,
        },
        {
            "job_id": "2",
            "required_skills": "Python, SQL",
            "preferred_skills": "",
            "score": 0.78,
        },
    ]
    ranked = rank_jobs(["Python", "SQL"], jobs)

    assert [job["job_id"] for job in ranked] == [2, 1]
    assert isinstance(ranked[0]["job_id"], int)


def test_semantic_relevance_can_break_a_required_skill_tie():
    jobs = [
        {
            "job_id": "3",
            "required_skills": "Python, SQL, Git, Docker",
            "preferred_skills": "",
            "score": 0.95,
        },
        {
            "job_id": "4",
            "required_skills": "Python, SQL, Git, Docker",
            "preferred_skills": "",
            "score": 0.65,
        },
    ]
    ranked = rank_jobs(["Python", "SQL"], jobs)

    assert ranked[0]["job_id"] == 3
    assert ranked[0]["ranking_score"] > ranked[1]["ranking_score"]
