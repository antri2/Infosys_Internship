"""Shared semantic retrieval and recommendation helpers."""
import logging

from services.job_matcher import rank_jobs
from services.rag_service import MAX_TOP_K, MIN_SEMANTIC_SCORE
from services.skill_normalizer import normalize_skill_list


logger = logging.getLogger(__name__)


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
        effective_query = ", ".join(normalized_skills) or "internship entry level"

    candidate_k = min(MAX_TOP_K, max(top_k * 3, top_k))
    candidates = search_jobs(effective_query, top_k=candidate_k)
    return rank_jobs(normalized_skills, candidates, top_k=top_k)
