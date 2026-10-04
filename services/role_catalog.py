"""Shared role-level labels and representative synchronized-job lookup.

The normal M3 selectors use these stable role labels instead of exposing every
company-specific posting.  A caller can still provide a specific job_id when
it needs an exact posting.
"""
from __future__ import annotations

import re


ROLE_OPTIONS = [
    "AI Engineer",
    "Machine Learning Engineer",
    "Data Scientist",
    "Software Engineer",
    "Data Analyst",
    "GenAI Engineer",
    "Product Analyst",
    "Business Analyst",
    "Full Stack Developer",
    "Frontend Developer",
    "Backend Developer",
    "DevOps Engineer",
    "Digital Marketing Analyst",
]

_ROLE_ALIASES = {
    "ml engineer": "Machine Learning Engineer",
    "machine learning engineer": "Machine Learning Engineer",
    "ai engineer": "AI Engineer",
    "genai engineer": "GenAI Engineer",
    "generative ai engineer": "GenAI Engineer",
    "data scientist": "Data Scientist",
    "software engineer": "Software Engineer",
    "data analyst": "Data Analyst",
    "product analyst": "Product Analyst",
    "business analyst": "Business Analyst",
    "full stack developer": "Full Stack Developer",
    "fullstack developer": "Full Stack Developer",
    "frontend developer": "Frontend Developer",
    "front end developer": "Frontend Developer",
    "backend developer": "Backend Developer",
    "back end developer": "Backend Developer",
    "devops engineer": "DevOps Engineer",
    "digital marketing analyst": "Digital Marketing Analyst",
}

# The synchronized catalog is intentionally kept unchanged.  These aliases
# only help a role-level selector choose a sensible representative posting for
# a family of titles (for example, ``ML Engineer`` or ``Data Science Intern``).
_ROLE_TITLE_PATTERNS = (
    (("ai engineer", "ai research", "ai ml", "artificial intelligence"), "AI Engineer"),
    (("machine learning engineer", "machine learning intern", "ml engineer", "ml intern"), "Machine Learning Engineer"),
    (("genai", "generative ai", "generative machine learning"), "GenAI Engineer"),
    (("data scientist", "data science intern"), "Data Scientist"),
    (("software engineer", "software development", "software testing"), "Software Engineer"),
    (("data analyst",), "Data Analyst"),
    (("product analyst",), "Product Analyst"),
    (("business analyst",), "Business Analyst"),
    (("full stack", "fullstack"), "Full Stack Developer"),
    (("frontend", "front end"), "Frontend Developer"),
    (("backend", "back end"), "Backend Developer"),
    (("devops", "site reliability", "cloud engineer"), "DevOps Engineer"),
    (("digital marketing", "content marketing", "seo"), "Digital Marketing Analyst"),
)

_ROLE_SEARCH_TERMS = {
    "AI Engineer": ("ai", "research", "machine learning"),
    "Machine Learning Engineer": ("machine learning", "ml"),
    "Data Scientist": ("data science", "data analyst", "statistics"),
    "Software Engineer": ("software", "developer", "web"),
    "Data Analyst": ("data analyst", "data science", "sql"),
    "GenAI Engineer": ("ai", "machine learning", "data science"),
    "Product Analyst": ("product analyst", "product management"),
    "Business Analyst": ("business analyst", "financial analyst"),
    "Full Stack Developer": ("full stack", "fullstack", "web"),
    "Frontend Developer": ("frontend", "react", "ui developer"),
    "Backend Developer": ("backend", "software", "web", "api"),
    "DevOps Engineer": ("devops", "cloud", "site reliability"),
    "Digital Marketing Analyst": ("digital marketing", "seo", "marketing"),
}


def role_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def canonical_role(value: str | None) -> str:
    """Normalize an explicitly selected role without guessing custom roles."""
    key = role_key(value)
    return _ROLE_ALIASES.get(key, " ".join(str(value or "").split()))


def _title_role(value: str | None) -> str:
    """Map a synchronized posting title to a stable role-level label."""
    key = role_key(value)
    if key in _ROLE_ALIASES:
        return _ROLE_ALIASES[key]
    for needles, role in _ROLE_TITLE_PATTERNS:
        if any(needle in key for needle in needles):
            return role
    return " ".join(str(value or "").split())


def role_options() -> list[str]:
    return list(ROLE_OPTIONS)


def find_role_job(db, role: str, preferred_job_id: int | None = None) -> dict | None:
    """Return an exact preferred job or a representative job for a role."""
    with db.cursor() as cursor:
        if preferred_job_id is not None:
            cursor.execute("SELECT * FROM jobs WHERE job_id = %s", (preferred_job_id,))
            preferred = cursor.fetchone()
            if preferred:
                return preferred
            return None
        cursor.execute("SELECT * FROM jobs ORDER BY job_id")
        jobs = cursor.fetchall()

    wanted = role_key(role)
    for job in jobs:
        if role_key(job.get("title")) == wanted:
            return job
    for job in jobs:
        if job_role(job) == canonical_role(role):
            return job
    for job in jobs:
        title = role_key(job.get("title"))
        if wanted and (wanted in title or title in wanted):
            return job

    # Fall back to role-family keywords when the catalog has internship or
    # adjacent-title variants rather than the exact role label.
    hints = _ROLE_SEARCH_TERMS.get(canonical_role(role), ())
    if hints:
        for job in jobs:
            title = role_key(job.get("title"))
            if any(hint in title for hint in hints):
                return job
    return None


def job_role(job: dict | None) -> str:
    return _title_role((job or {}).get("title"))
