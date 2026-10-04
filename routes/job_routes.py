"""
M2.2 -- Exposes relevance-filtered RAG search over HTTP.
"""
import logging

from flask import Blueprint, jsonify, request

from services.rag_service import MAX_TOP_K, semantic_search


job_bp = Blueprint("jobs", __name__, url_prefix="/jobs")
logger = logging.getLogger(__name__)


@job_bp.route("/search", methods=["GET"])
def search_jobs():
    """
    GET /jobs/search?q=<natural language query>&top_k=5

    Example:
        /jobs/search?q=internship in machine learning with Python
    """
    query = request.args.get("q", "").strip()
    top_k = request.args.get("top_k", default=5, type=int)

    if not query:
        return jsonify({"error": "Missing query parameter 'q'"}), 400
    if top_k is None or not 1 <= top_k <= MAX_TOP_K:
        return jsonify({"error": f"top_k must be between 1 and {MAX_TOP_K}"}), 400

    try:
        results = semantic_search(query, top_k=top_k)
    except FileNotFoundError:
        return jsonify({"error": "Vector store is not available. Build the FAISS index first."}), 503
    except Exception:
        logger.exception("Public semantic job search failed")
        return jsonify({"error": "Semantic job search is temporarily unavailable."}), 503

    return jsonify({"query": query, "count": len(results), "results": results})
