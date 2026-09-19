"""
M2.2 -- Embedding generation.

Uses fastembed (ONNX Runtime, not PyTorch) so there's no multi-GB torch
install -- just onnxruntime + a small model, downloaded once (~100MB)
and cached locally. Fully offline after that first download.

Model: BAAI/bge-small-en-v1.5 -- 384-dim vectors, strong short-text
retrieval performance. To use your mentor's exact pick instead, change
MODEL_NAME to "sentence-transformers/all-MiniLM-L6-v2" -- fastembed
supports that model too, no other code changes needed.
"""
from functools import lru_cache

import numpy as np

MODEL_NAME = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=1)
def _get_model():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=MODEL_NAME)


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embeds a list of texts -> (N, 384) float32 array, L2-normalized
    so inner product = cosine similarity."""
    model = _get_model()
    vectors = np.array(list(model.embed(texts)), dtype="float32")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1e-8
    return vectors / norms


def embed_query(text: str) -> np.ndarray:
    """Embeds a single query string -> (384,) float32 vector."""
    return embed_texts([text])[0]