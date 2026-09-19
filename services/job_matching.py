"""
Lightweight skill-matching logic used by the Opportunities page.

This is deliberately simple (set overlap on normalized skill names) --
M2.3's job-resume matching agent can later replace compute_match()'s
internals with an LLM-reasoned score without changing its signature,
so routes/templates don't need to change.
"""


def _normalize(skill: str) -> str:
    return skill.strip().lower()


def _split_skills(csv_text: str) -> list[str]:
    if not csv_text:
        return []
    return [s.strip() for s in csv_text.split(",") if s.strip()]


def compute_match(user_skills: list[str], job: dict) -> dict:
    """
    user_skills: list of skill name strings from the user's profile.
    job: a job dict with 'required_skills' and 'preferred_skills' as
         comma-separated strings (matches the jobs_clean.csv schema).

    Returns: {
        match_percent: int (0-100, based on required skills only),
        matched_skills: [str],   # required skills the user already has
        missing_skills: [str],   # required skills the user is missing
        matched_preferred: [str] # preferred/bonus skills the user has
    }
    """
    user_set = {_normalize(s) for s in user_skills}
    required = _split_skills(job.get("required_skills", ""))
    preferred = _split_skills(job.get("preferred_skills", ""))

    matched = [s for s in required if _normalize(s) in user_set]
    missing = [s for s in required if _normalize(s) not in user_set]
    matched_preferred = [s for s in preferred if _normalize(s) in user_set]

    match_percent = round(len(matched) / len(required) * 100) if required else 0

    return {
        "match_percent": match_percent,
        "matched_skills": matched,
        "missing_skills": missing,
        "matched_preferred": matched_preferred,
    }