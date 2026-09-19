"""
M2.2 -- RAG pipeline: build the vector index, and search it.

    Job Dataset -> Chunking -> Embeddings -> FAISS -> Semantic Search -> Top-K Jobs

build_index()      reads data/jobs_clean.csv, chunks + embeds every
                    posting, saves the FAISS index + metadata to
                    data/vector_store/. Run this once after the dataset
                    changes.
semantic_search()  embeds a query, searches the index, returns the
                    top-k unique job postings (collapsing the 2 chunks
                    per job back into one result per job).
"""
import csv
import json
from functools import lru_cache
from pathlib import Path

import faiss

from services.Embedding_service import embed_texts, embed_query
from services.Job_chunker import build_chunks

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs_clean.csv"
STORE_DIR = Path(__file__).resolve().parent.parent / "data" / "vector_store"
INDEX_PATH = STORE_DIR / "jobs.index"
METADATA_PATH = STORE_DIR / "metadata.json"
JOBS_LOOKUP_PATH = STORE_DIR / "jobs_lookup.json"


def build_index():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        jobs = list(csv.DictReader(f))
    print(f"Loaded {len(jobs)} clean job postings from {DATA_PATH.name}")

    all_chunks = []
    for job in jobs:
        all_chunks.extend(build_chunks(job))
    print(f"Split into {len(all_chunks)} chunks ({len(all_chunks) // len(jobs)} per posting)")

    texts = [c["text"] for c in all_chunks]
    print("Generating embeddings (first run downloads the model, ~100MB)...")
    vectors = embed_texts(texts)
    dim = vectors.shape[1]

    index = faiss.IndexFlatIP(dim)  # inner product on normalized vectors = cosine similarity
    index.add(vectors)

    STORE_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))

    # metadata.json: vector position -> {job_id, job_title, company, chunk_type}
    jobs_by_id = {job["job_id"]: job for job in jobs}
    metadata = {}
    for i, c in enumerate(all_chunks):
        job = jobs_by_id[c["job_id"]]
        metadata[str(i)] = {
            "job_id": c["job_id"],
            "job_title": job["title"],
            "company": job["company"],
            "chunk_type": c["chunk_type"],
        }
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f)

    with open(JOBS_LOOKUP_PATH, "w", encoding="utf-8") as f:
        json.dump(jobs_by_id, f)

    print(f"Saved FAISS index ({index.ntotal} vectors, dim={dim}) to {INDEX_PATH}")
    print(f"Saved metadata to {METADATA_PATH}")
    print(f"Saved job lookup table to {JOBS_LOOKUP_PATH}")


@lru_cache(maxsize=1)
def _load_store():
    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            "Vector index not found. Run rag_service.build_index() "
            "(or `python -c \"from services.rag_service import build_index; build_index()\"`) first."
        )
    index = faiss.read_index(str(INDEX_PATH))
    with open(METADATA_PATH, encoding="utf-8") as f:
        metadata = json.load(f)
    with open(JOBS_LOOKUP_PATH, encoding="utf-8") as f:
        jobs_lookup = json.load(f)
    return index, metadata, jobs_lookup


def semantic_search(query: str, top_k: int = 5) -> list[dict]:
    """
    Returns up to top_k unique job postings ranked by cosine similarity
    to the query. Each result is the full job record plus `score`
    (0-1, higher = more relevant) and `matched_chunk` ("overview" or
    "skills" -- whichever part of the posting matched best).
    """
    index, metadata, jobs_lookup = _load_store()

    query_vector = embed_query(query).reshape(1, -1)
    fetch_k = min(top_k * 6, index.ntotal)  # over-fetch chunks before collapsing to unique jobs
    scores, indices = index.search(query_vector, fetch_k)

    best_per_job = {}  # job_id -> (score, chunk_type)
    for score, idx in zip(scores[0], indices[0]):
        if idx == -1:
            continue
        chunk_info = metadata[str(idx)]
        job_id = chunk_info["job_id"]
        if job_id not in best_per_job or score > best_per_job[job_id][0]:
            best_per_job[job_id] = (float(score), chunk_info["chunk_type"])

    ranked = sorted(best_per_job.items(), key=lambda kv: kv[1][0], reverse=True)[:top_k]

    results = []
    for job_id, (score, chunk_type) in ranked:
        job = dict(jobs_lookup[job_id])
        job["score"] = round(score, 4)
        job["matched_chunk"] = chunk_type
        results.append(job)
    return results