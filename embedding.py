"""Embedding model lifecycle and local tensor-cache helpers.

The Hugging Face model is loaded lazily and cached once per process.  Health
checks can inspect lifecycle state without importing a model from the network
or allocating model memory.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

import torch
from sentence_transformers import SentenceTransformer

from config import (
    CACHE_DIR,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DEVICE,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_REVISION,
)

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model: SentenceTransformer | None = None
_model_error_type: str | None = None

PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "


def get_cache_path(pdf_folder: str | os.PathLike[str]) -> str:
    """Return the legacy per-folder embedding cache path."""

    cache_name = os.path.basename(os.fspath(pdf_folder))
    if not cache_name:
        cache_name = "all_documents"
    return os.path.join(CACHE_DIR, f"{cache_name}.pt")


def save_embeddings(path: str | os.PathLike[str], data: Any) -> None:
    """Persist a tensor-like embedding artifact below its parent directory."""

    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(data, cache_path)
    logger.info("Saved embedding cache path=%s", cache_path)


def load_cached_embeddings(
    cache_path: str | os.PathLike[str],
) -> Any | None:
    """Load a trusted tensor cache, returning ``None`` when it does not exist."""

    path = Path(cache_path)
    if not path.exists():
        return None
    # Embedding cache files are application-created tensors.  ``weights_only``
    # avoids arbitrary pickle object construction when supported by PyTorch.
    try:
        return torch.load(path, weights_only=True)
    except TypeError:  # pragma: no cover - compatibility with older PyTorch
        return torch.load(path)


def get_embeddings(
    model: SentenceTransformer,
    chunks: list[dict[str, Any]],
    pdf_folder: str | os.PathLike[str],
) -> Any:
    """Return cached embeddings or create and persist them."""

    cache_path = get_cache_path(pdf_folder)
    embeddings = load_cached_embeddings(cache_path)
    if embeddings is not None:
        return embeddings

    embeddings = embed_chunks(model, chunks)
    save_embeddings(cache_path, embeddings)
    return embeddings


def load_embedding_model(*, force_reload: bool = False) -> SentenceTransformer:
    """Load the configured SentenceTransformer once per process.

    ``force_reload`` exists for explicit lifecycle tests and operator tooling;
    normal request paths should rely on the process-local singleton.
    """

    global _model, _model_error_type

    if _model is not None and not force_reload:
        return _model

    with _model_lock:
        if _model is not None and not force_reload:
            return _model

        kwargs: dict[str, str] = {}
        if EMBEDDING_MODEL_REVISION:
            kwargs["revision"] = EMBEDDING_MODEL_REVISION
        if EMBEDDING_DEVICE:
            kwargs["device"] = EMBEDDING_DEVICE

        logger.info(
            "Loading embedding model name=%s revision=%s device=%s",
            EMBEDDING_MODEL,
            EMBEDDING_MODEL_REVISION or "default",
            EMBEDDING_DEVICE or "auto",
        )
        try:
            loaded_model = SentenceTransformer(EMBEDDING_MODEL, **kwargs)
        except Exception as exc:
            _model_error_type = type(exc).__name__
            logger.exception("Embedding model failed to load")
            raise

        _model = loaded_model
        _model_error_type = None
        logger.info("Embedding model loaded")
        return loaded_model


def get_embedding_model_status() -> dict[str, str | None]:
    """Return lifecycle metadata without loading or probing the model."""

    if _model is not None:
        state = "loaded"
    elif _model_error_type is not None:
        state = "error"
    else:
        state = "not_loaded"
    return {
        "state": state,
        "model": EMBEDDING_MODEL,
        "revision": EMBEDDING_MODEL_REVISION or None,
        "device": EMBEDDING_DEVICE or "auto",
        "error_type": _model_error_type,
    }


def embed_chunks(
    model: SentenceTransformer,
    chunks: list[dict[str, Any]],
) -> Any:
    """Encode chunk text into a tensor suitable for retrieval."""

    texts = [chunk["text"] for chunk in chunks]
    embeddings = embed_passages(
        model,
        texts,
        convert_to_tensor=True,
    )
    logger.info(
        "Generated embeddings count=%s dimension=%s",
        len(embeddings),
        len(embeddings[0]) if len(embeddings) else 0,
    )
    return embeddings


def embed_passages(
    model: SentenceTransformer,
    texts: list[str],
    *,
    convert_to_tensor: bool = False,
) -> Any:
    """Batch-encode E5 passage inputs as normalized vectors."""

    if not texts:
        return []
    prefixed = [_with_prefix(text, PASSAGE_PREFIX) for text in texts]
    return model.encode(
        prefixed,
        batch_size=EMBEDDING_BATCH_SIZE,
        convert_to_tensor=convert_to_tensor,
        normalize_embeddings=True,
    )


def embed_query(
    model: SentenceTransformer,
    question: str,
    *,
    convert_to_tensor: bool = False,
) -> Any:
    """Encode one E5 query input as a normalized vector."""

    return model.encode(
        _with_prefix(question, QUERY_PREFIX),
        convert_to_tensor=convert_to_tensor,
        normalize_embeddings=True,
    )


def embedding_rows_to_lists(embeddings: Any) -> list[list[float]]:
    """Convert a batched tensor/array result to plain vector lists."""

    rows: list[list[float]] = []
    for embedding in embeddings:
        if hasattr(embedding, "tolist"):
            rows.append(embedding.tolist())
        else:
            rows.append(list(embedding))
    return rows


def _with_prefix(text: str, prefix: str) -> str:
    normalized = text.strip()
    if normalized.casefold().startswith(prefix):
        return normalized
    return f"{prefix}{normalized}"
