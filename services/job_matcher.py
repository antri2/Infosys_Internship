"""Deterministic profile-skill matching and combined job ranking.

The displayed Profile Skill Fit percentage is intentionally separate from the
combined ranking score. It answers "How well do the user's stored skills fit
this job's required/preferred skills?" and is not a probability of getting
the job.
"""
from services.skill_normalizer import (
    normalize_skill_list,
    skill_comparison_key,
    split_skill_text,
)


PROFILE_REQUIRED_WEIGHT = 0.85
PROFILE_PREFERRED_WEIGHT = 0.15

RANK_SEMANTIC_WEIGHT = 0.45
RANK_REQUIRED_WEIGHT = 0.45
RANK_PREFERRED_WEIGHT = 0.10


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _semantic_label(score: float) -> str:
    if score >= 0.80:
        return "strong"
    if score >= 0.72:
        return "good"
    if score >= 0.65:
        return "moderate"
    return "limited"


def _format_skills(skills: list[str], limit: int = 5) -> str:
    shown = skills[:limit]
    suffix = ", ..." if len(skills) > limit else ""
    return ", ".join(shown) + suffix


def _split_ratios(matched: list[str], available: list[str]) -> float:
    return len(matched) / len(available) if available else 0.0


def compute_match(
    user_skills: list[str],
    job: dict,
    semantic_score: float | None = None,
) -> dict:
    """Calculate Profile Skill Fit and a combined semantic/skill ranking score."""
    normalized_user = normalize_skill_list(user_skills)
    user_keys = {skill_comparison_key(skill) for skill in normalized_user}

    required = normalize_skill_list(split_skill_text(job.get("required_skills")))
    preferred = normalize_skill_list(split_skill_text(job.get("preferred_skills")))
    required_keys = {skill_comparison_key(skill) for skill in required}
    preferred_keys = {skill_comparison_key(skill) for skill in preferred}

    matched_required = [skill for skill in required if skill_comparison_key(skill) in user_keys]
    missing_required = [skill for skill in required if skill_comparison_key(skill) not in user_keys]
    matched_preferred = [skill for skill in preferred if skill_comparison_key(skill) in user_keys]
    missing_preferred = [skill for skill in preferred if skill_comparison_key(skill) not in user_keys]

    required_ratio = _split_ratios(matched_required, required)
    preferred_ratio = _split_ratios(matched_preferred, preferred)
    has_profile_skills = bool(normalized_user)
    has_job_skills = bool(required or preferred)
    match_available = has_profile_skills and has_job_skills

    if match_available:
        skill_fit_ratio = (
            PROFILE_REQUIRED_WEIGHT * required_ratio
            + PROFILE_PREFERRED_WEIGHT * preferred_ratio
        )
        match_percent = round(_clamp(skill_fit_ratio) * 100)
    else:
        skill_fit_ratio = 0.0
        match_percent = None

    if semantic_score is None and job.get("score") is not None:
        semantic_score = job["score"]

    semantic_quality = None
    semantic_label = None
    if semantic_score is not None:
        semantic_quality = _clamp(float(semantic_score))
        semantic_label = _semantic_label(semantic_quality)

    if semantic_quality is None:
        ranking_score = skill_fit_ratio
    elif match_available:
        ranking_score = (
            RANK_SEMANTIC_WEIGHT * semantic_quality
            + RANK_REQUIRED_WEIGHT * required_ratio
            + RANK_PREFERRED_WEIGHT * preferred_ratio
        )
    else:
        ranking_score = semantic_quality

    reasons = []
    if semantic_label is not None:
        section = "skills" if job.get("matched_chunk") == "skills" else "job details"
        reasons.append(
            f"{semantic_label.capitalize()} semantic match based on the job's {section}."
        )

    if not has_profile_skills:
        reasons.append("Add skills to your profile to calculate Profile Skill Fit.")
    else:
        reasons.append(
            f"You match {len(matched_required)} of {len(required)} required skills"
            + (f": {_format_skills(matched_required)}." if matched_required else ".")
        )
        if missing_required:
            reasons.append(f"Missing required skills: {_format_skills(missing_required)}.")
        if matched_preferred:
            reasons.append(
                f"You also match preferred skills: {_format_skills(matched_preferred)}."
            )
        elif missing_preferred:
            reasons.append(
                f"Preferred skills not yet in your profile: {_format_skills(missing_preferred)}."
            )

    return {
        "match_percent": match_percent,
        "match_available": match_available,
        "matched_skills": matched_required,
        "missing_skills": missing_required,
        "matched_preferred": matched_preferred,
        "missing_preferred": missing_preferred,
        "required_total": len(required),
        "preferred_total": len(preferred),
        "required_ratio": round(required_ratio, 6),
        "preferred_ratio": round(preferred_ratio, 6),
        "semantic_score": round(semantic_quality, 6) if semantic_quality is not None else None,
        "semantic_label": semantic_label,
        "ranking_score": round(_clamp(ranking_score), 6),
        "match_reasons": reasons,
    }


def rank_jobs(
    user_skills: list[str],
    candidate_jobs: list[dict],
    top_k: int | None = None,
) -> list[dict]:
    """Combine semantic relevance with required/preferred skill fit."""
    ranked = []
    for job in candidate_jobs:
        enriched = {**job}
        try:
            enriched["job_id"] = int(job["job_id"])
        except (KeyError, TypeError, ValueError):
            pass

        match_info = compute_match(
            user_skills,
            job,
            semantic_score=job.get("score"),
        )
        enriched.update(match_info)
        ranked.append(enriched)

    ranked.sort(
        key=lambda job: (
            -job["ranking_score"],
            -(job["match_percent"] if job["match_percent"] is not None else -1),
            -(job["semantic_score"] if job["semantic_score"] is not None else -1.0),
            job.get("job_id", 0),
        )
    )
    return ranked if top_k is None else ranked[:top_k]
