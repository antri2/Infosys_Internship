"""Conservative skill-name normalization for job matching.

The initial alias set is intentionally small and explicit. Add broader
aliases only after they are validated against the canonical job vocabulary.
"""

SKILL_ALIASES = {
    "js": "JavaScript",
    "ml": "Machine Learning",
    "react.js": "React",
    "postgresql": "Postgres",
}


def normalize_skill(skill: str | None) -> str:
    """Return a consistent display name for one skill."""
    if skill is None:
        return ""
    cleaned = " ".join(str(skill).strip().split())
    if not cleaned:
        return ""
    return SKILL_ALIASES.get(cleaned.casefold(), cleaned)


def skill_comparison_key(skill: str | None) -> str:
    """Return the case-insensitive key used for canonical skill comparison."""
    return normalize_skill(skill).casefold()


def normalize_skill_list(skills: list[str] | None) -> list[str]:
    """Normalize and deduplicate skills while preserving first-seen order."""
    normalized = []
    seen = set()
    for skill in skills or []:
        display_name = normalize_skill(skill)
        key = skill_comparison_key(display_name)
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(display_name)
    return normalized


def split_skill_text(csv_text: str | None) -> list[str]:
    """Split the dataset's comma-separated skill fields."""
    return [skill.strip() for skill in (csv_text or "").split(",") if skill.strip()]
