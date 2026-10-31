"""Shared semantic retrieval and recommendation helpers.

Job sources, in priority order:

1. **Adzuna live API** -- used when it is configured *and* returns usable jobs.
2. **Local canonical dataset** -- the 185-row CSV -> MySQL -> FAISS pipeline.

The local dataset is always the fallback. If Adzuna is unconfigured, disabled,
unreachable, slow, erroring, or returns nothing usable, retrieval silently falls
through to the FAISS pipeline exactly as it did before Adzuna existed, so the
app never shows an error just because the third party is unavailable.
"""
import logging

import config
from services.job_matcher import compute_match, rank_jobs
from services.rag_service import MAX_TOP_K, MIN_SEMANTIC_SCORE
from services.skill_normalizer import normalize_skill_list


logger = logging.getLogger(__name__)

LOCAL_SOURCE = "local"


def default_location() -> str:
    """Where live jobs are searched by default (config-driven, default India)."""
    return (config.ADZUNA_DEFAULT_LOCATION or "India").strip()


def build_default_query(user_skills: list[str]) -> str:
    """Query used when a signed-in user opens Opportunities without searching.

    Their own skills make the best query when they have any, because they
    describe the kind of work they are looking for. Otherwise a safe, broadly
    useful entry-level phrasing is used so the page is never empty and the user
    never has to search just to see something.
    """
    skills = [skill for skill in (user_skills or []) if skill and skill.strip()]
    if skills:
        # A handful of skills keeps the query focused; a long list dilutes it.
        return ", ".join(skills[:5])
    return (config.ADZUNA_DEFAULT_QUERY or "entry level technology jobs").strip()


def search_jobs(
    query: str,
    top_k: int = 20,
    min_score: float = MIN_SEMANTIC_SCORE,
) -> list[dict]:
    """Return relevant FAISS results, or an empty list when retrieval fails."""
    try:
        from services.rag_service import semantic_search

        return semantic_search(query, top_k=top_k, min_score=min_score)
    except FileNotFoundError:
        logger.exception("Vector store is unavailable")
        return []
    except Exception:
        logger.exception("Semantic job retrieval failed")
        return []


def _live_query(query: str) -> str:
    """Adzuna-specific query shaping.

    Adzuna reads a comma list as "all of these", so a five-skill profile sent
    as "Python, SQL, MySQL, Excel, Power BI" matches a single posting. Asking
    for "any of these" is what "show me relevant opportunities" actually means,
    and it is what turns a one-card page into a full list.

    Only the live call is reshaped. The local FAISS pipeline keeps the comma
    list, which embeds well as a single piece of text.
    """
    parts = [part.strip() for part in (query or "").split(",") if part.strip()]
    if len(parts) < 2:
        return query
    return " OR ".join(parts[:3])


def _live_jobs(query: str, user_skills: list[str], top_k: int) -> list[dict]:
    """Fetch Adzuna jobs and score them with the existing profile matcher.

    Matching is reused verbatim from services.job_matcher -- the same
    ``compute_match`` that scores the local dataset -- so Profile Skill Fit,
    matched/missing skills and the match reasons behave identically for live
    jobs. The only difference is ordering: live jobs carry no embedding, so
    ``compute_match`` gives them no semantic component and their ranking score is
    the skill fit alone. We therefore keep Adzuna's own relevance order as the
    tie-break, so a keyword search still surfaces what Adzuna considered
    relevant.
    """
    from services import adzuna_service

    fetched = adzuna_service.search_jobs(
        _live_query(query),
        location=default_location(),
        results_per_page=max(top_k, 1),
    )
    if not fetched:
        return []

    enriched = []
    for position, job in enumerate(fetched):
        try:
            match = compute_match(user_skills, job)
        except Exception:
            logger.exception("Live job %s could not be scored; skipping it.", position)
            continue
        enriched.append((position, {**job, **match, "source": "adzuna"}))

    enriched.sort(key=lambda item: (-item[1].get("ranking_score") or 0.0, item[0]))
    return [job for _, job in enriched]


def recommend_jobs(
    query: str,
    user_skills: list[str],
    top_k: int = 20,
) -> list[dict]:
    """Retrieve, normalize, combine, and rank jobs for one user/query."""
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be an integer between 1 and {MAX_TOP_K}")

    normalized_skills = normalize_skill_list(user_skills)
    effective_query = (query or "").strip()
    if not effective_query:
        effective_query = build_default_query(normalized_skills)

    # 1) Live source first.
    live = _live_jobs(effective_query, normalized_skills, top_k)
    if live:
        return live[:top_k]

    # 2) Fallback: the existing local dataset, unchanged.
    candidate_k = min(MAX_TOP_K, max(top_k * 3, top_k))
    candidates = search_jobs(effective_query, top_k=candidate_k)
    ranked = rank_jobs(normalized_skills, candidates, top_k=top_k)
    return [{**job, "source": job.get("source") or LOCAL_SOURCE} for job in ranked]