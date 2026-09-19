"""
M2.2 -- Exposes the RAG search over HTTP so the frontend (or a quick
browser/Postman test) can query it.
"""
from flask import Blueprint, jsonify, request

from services.rag_service import semantic_search

job_bp = Blueprint("jobs", __name__, url_prefix="/jobs")


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

    try:
        results = semantic_search(query, top_k=top_k)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 503

    return jsonify({"query": query, "count": len(results), "results": results})