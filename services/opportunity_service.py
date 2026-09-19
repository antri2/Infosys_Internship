"""
Shared helper for anywhere that needs "jobs ranked for this query", with
a safe fallback if the RAG vector index hasn't been built yet (so pages
don't crash during development/demo before rag_service.build_index()
has been run).
"""
import csv
from pathlib import Path

JOBS_CSV_FALLBACK = Path(__file__).resolve().parent.parent / "data" / "jobs_clean.csv"


def _fallback_jobs(limit: int = 30) -> list[dict]:
    if not JOBS_CSV_FALLBACK.exists():
        return []
    with open(JOBS_CSV_FALLBACK, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[:limit]


def search_jobs(query: str, top_k: int = 20) -> list[dict]:
    """
    Returns up to top_k jobs relevant to `query`. Prefers the RAG
    semantic search; if the vector index hasn't been built yet (or any
    other issue occurs), degrades to a plain CSV listing so pages still
    render instead of crashing.
    """
    try:
        from services.rag_service import semantic_search
        return semantic_search(query, top_k=top_k)
    except FileNotFoundError:
        return _fallback_jobs(top_k)
    except Exception:
        return _fallback_jobs(top_k)