"""Short, fact-grounded AI summaries for one selected job.

Groq chooses which verified skills to emphasize, but the final prose is
rendered from a closed set of M2 match fields. This prevents the model from
inventing profile facts while still providing AI-guided personalization.
"""
from services.context_builder import flatten_candidate_text
from services.llm_client import extract_json_object, generate


def _unique(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        cleaned = " ".join(str(value or "").split())
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _join_skills(skills: list[str], limit: int = 5) -> str:
    shown = skills[:limit]
    suffix = ", ..." if len(skills) > limit else ""
    return ", ".join(shown) + suffix


def _render_summary(matched: list[str], match_info: dict) -> str:
    matched = _unique(matched)
    missing_required = _unique(list(match_info.get("missing_skills", [])))
    missing_preferred = _unique(list(match_info.get("missing_preferred", [])))

    if matched:
        first = f"Your {_join_skills(matched)} skills match several requirements for this role."
    elif missing_required or missing_preferred:
        first = "This role lists skills that are not currently confirmed in your profile."
    else:
        first = "Your current profile matches the main skills listed for this role."

    if missing_required:
        second = f"Missing required skills include {_join_skills(missing_required)}."
    elif missing_preferred:
        second = f"Preferred skills not yet in your profile include {_join_skills(missing_preferred)}."
    else:
        second = "Your current profile matches the main skills listed for this role."

    return first if first == second else f"{first} {second}"


def _fallback_summary(match_info: dict) -> str:
    matched = _unique(
        list(match_info.get("matched_skills", []))
        + list(match_info.get("matched_preferred", []))
    )
    return _render_summary(matched, match_info)


def _build_prompt(candidate: dict, job: dict, match_info: dict) -> str:
    allowed_matched = _unique(
        list(match_info.get("matched_skills", []))
        + list(match_info.get("matched_preferred", []))
    )
    missing_required = _unique(list(match_info.get("missing_skills", [])))
    missing_preferred = _unique(list(match_info.get("missing_preferred", [])))

    return f"""Choose which verified skills are most relevant to mention in a short
career summary for the selected job. Return JSON only.

Strict rules:
- "matched_skills" may contain only exact names from the verified matched list.
- Never return a skill that is not in that list.
- Do not write prose, probability, chances, guarantees, or selection likelihood.
- Missing skills will be added separately from verified M2 data.

Candidate actual context:
{flatten_candidate_text(candidate)}

Selected job:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Required skills: {job.get('required_skills') or 'None listed'}
Preferred skills: {job.get('preferred_skills') or 'None listed'}

Verified matched skills: {', '.join(allowed_matched) or 'None'}
Verified missing required skills: {', '.join(missing_required) or 'None'}
Verified missing preferred skills: {', '.join(missing_preferred) or 'None'}

Return exactly this JSON shape:
{{"matched_skills": ["verified skill", "..."]}}
"""


def _select_grounded_matches(data: dict, match_info: dict) -> list[str]:
    allowed = _unique(
        list(match_info.get("matched_skills", []))
        + list(match_info.get("matched_preferred", []))
    )
    allowed_by_key = {skill.casefold(): skill for skill in allowed}
    requested = data.get("matched_skills", [])
    if not isinstance(requested, list):
        return []
    selected = []
    for value in requested:
        canonical = allowed_by_key.get(str(value or "").strip().casefold())
        if canonical:
            selected.append(canonical)
    return _unique(selected) or allowed


def generate_job_summary(candidate: dict, job: dict, match_info: dict) -> dict:
    """Use Groq to select emphasis, then render strictly grounded prose."""
    fallback = _fallback_summary(match_info)
    try:
        raw_response = generate(
            _build_prompt(candidate, job, match_info),
            max_tokens=140,
            temperature=0.2,
        )
        data = extract_json_object(raw_response)
        selected_matches = _select_grounded_matches(data, match_info)
        return {
            "summary": _render_summary(selected_matches, match_info),
            "used_fallback": False,
        }
    except Exception:
        # Deterministic output covers provider, network, timeout, and parse errors.
        return {"summary": fallback, "used_fallback": True}
