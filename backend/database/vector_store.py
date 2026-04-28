"""
Vector store for RAG over extracted paper full texts.
Uses ChromaDB + OpenAI text-embedding-3-small.
Falls back to keyword search if ChromaDB/OpenAI not available.
"""
from __future__ import annotations
import re
import logging
from typing import Optional
from config import VECTOR_PATH, OPENAI_API_KEY

logger = logging.getLogger(__name__)

_CHUNK_SIZE    = 1800
_CHUNK_OVERLAP = 250
_COLLECTION    = "mof_papers"


def _get_collection():
    import chromadb
    client = chromadb.PersistentClient(path=str(VECTOR_PATH))
    return client.get_or_create_collection(
        name=_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def _embed(texts: list[str]) -> list[list[float]]:
    import requests
    r = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                 "Content-Type": "application/json"},
        json={"model": "text-embedding-3-small", "input": texts},
        timeout=30,
    )
    r.raise_for_status()
    return [item["embedding"] for item in r.json()["data"]]


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Public wrapper — returns embeddings or None if unavailable."""
    if not OPENAI_API_KEY or not texts:
        return None
    try:
        return _embed(texts)
    except Exception as e:
        logger.error("embed_texts failed: %s", e)
        return None


def chunk_text(text: str) -> list[str]:
    """Public wrapper around the internal chunker."""
    return _chunk_text(text)


def index_paper(paper_id: int, title: str, doi: str, full_text: str) -> int:
    """Chunk paper text and index into ChromaDB. Returns chunk count."""
    if not OPENAI_API_KEY:
        logger.warning("No OPENAI_API_KEY — skipping vector indexing")
        return 0
    try:
        col    = _get_collection()
        chunks = _chunk_text(full_text)
        ids    = [f"paper_{paper_id}_chunk_{i}" for i in range(len(chunks))]
        metas  = [{"paper_id": paper_id, "title": title, "doi": doi, "chunk": i}
                  for i in range(len(chunks))]
        # Batch embed (OpenAI allows up to 2048 inputs)
        embeds = _embed(chunks)
        col.upsert(ids=ids, documents=chunks, embeddings=embeds, metadatas=metas)
        return len(chunks)
    except Exception as e:
        logger.error("Vector indexing failed: %s", e)
        return 0


def retrieve(query: str, n_results: int = 5) -> list[dict]:
    """
    Retrieve top-n chunks most relevant to query.
    Returns list of {text, title, doi, paper_id, score}.
    """
    if not OPENAI_API_KEY:
        return []
    try:
        col     = _get_collection()
        q_embed = _embed([query])[0]
        results = col.query(
            query_embeddings=[q_embed],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        out = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            out.append({
                "text":     doc,
                "title":    meta.get("title", ""),
                "doi":      meta.get("doi", ""),
                "paper_id": meta.get("paper_id"),
                "score":    round(1 - dist, 3),
            })
        return out
    except Exception as e:
        logger.error("Vector retrieval failed: %s", e)
        return []


def _chunk_text(text: str) -> list[str]:
    if len(text) <= _CHUNK_SIZE:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + _CHUNK_SIZE, len(text))
        if end < len(text):
            b = text.rfind(". ", start + _CHUNK_SIZE // 2, end)
            if b != -1:
                end = b + 1
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - _CHUNK_OVERLAP
    return chunks
