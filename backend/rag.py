"""Real ONNX embeddings + PostgreSQL vector distance; BM25 and explicit lexical reranking."""

import hashlib
import json
import re
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
import numpy as np
from bs4 import BeautifulSoup
from fastembed import TextEmbedding
from rank_bm25 import BM25Okapi
from sqlalchemy import select, or_, update
from backend.config import settings
from backend.db import session_scope
from backend.models import KnowledgeDocument, Chunk, Policy, as_dict, now

_lock = threading.Lock()


@lru_cache(maxsize=1)
def embedding_model():
    return TextEmbedding(model_name=settings().embedding_model, cache_dir=settings().model_cache, threads=2)


@lru_cache(maxsize=512)
def embed_query(text):
    with _lock:
        return next(embedding_model().query_embed(text)).tolist()


def embed_documents(texts):
    with _lock:
        return [v.tolist() for v in embedding_model().embed(texts, batch_size=16)]


def tokenize(text):
    stop = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "the",
        "this",
        "to",
        "what",
        "when",
        "with",
        "you",
        "your",
        "novamart",
    }
    return [token for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower()) if token not in stop]


def parse_sections(content: str, fmt: str):
    if len(content.encode()) > 1_000_000:
        raise ValueError("Document exceeds 1 MB limit")
    if fmt == "html":
        soup = BeautifulSoup(content, "html.parser")
        for bad in soup(["script", "style", "iframe"]):
            bad.decompose()
        for heading in soup.find_all(re.compile(r"^h[1-6]$")):
            heading.replace_with("\n## " + heading.get_text(" ") + "\n")
        content = soup.get_text("\n")
    elif fmt == "json":
        obj = json.loads(content)
        if not isinstance(obj, dict):
            raise ValueError("JSON document must be an object of named sections")
        content = "\n".join(
            f"## {key}\n{value if isinstance(value, str) else json.dumps(value)}" for key, value in obj.items()
        )
    elif fmt not in {"md", "txt"}:
        raise ValueError("Supported formats: md, txt, html, json")
    section, lines, result = "Overview", [], []
    for line in content.replace("\x00", "").splitlines():
        heading = re.match(r"^#{1,6}\s+(.+)", line)
        if heading:
            if lines:
                result.append((section, " ".join(lines)))
            section, lines = heading[1].strip(), []
        elif line.strip():
            lines.append(re.sub(r"\s+", " ", line.strip()))
    if lines:
        result.append((section, " ".join(lines)))
    return result


def chunk_sections(sections, size=100, overlap=20):
    if not 30 <= size <= 500 or not 0 <= overlap < size:
        raise ValueError("chunk size must be 30..500; overlap less than size")
    chunks = []
    for section, body in sections:
        words = body.split()
        for start in range(0, len(words), size - overlap):
            chunks.append((section, " ".join(words[start : start + size])))
            if start + size >= len(words):
                break
    return chunks


def ingest(data):
    sections = parse_sections(data["content"], data["format"])
    parts = chunk_sections(sections, data.get("chunk_size", 100))
    if not parts:
        raise ValueError("Document has no usable text")
    vectors = embed_documents([f"{data['title']} {section}: {body}" for section, body in parts])
    effective = datetime.fromisoformat(data["effective_date"]).replace(tzinfo=timezone.utc)
    expires = (
        datetime.fromisoformat(data["expires_at"]).replace(tzinfo=timezone.utc) if data.get("expires_at") else None
    )
    with session_scope() as s:
        if data.get("active", True):
            s.execute(update(KnowledgeDocument).where(KnowledgeDocument.title == data["title"]).values(active=False))
        doc = KnowledgeDocument(
            id=data.get("id"),
            title=data["title"],
            category=data["category"],
            version=data["version"],
            active=data.get("active", True),
            effective_date=effective,
            expires_at=expires,
            format=data["format"],
            content=data["content"],
            meta={
                **data.get("metadata", {}),
                "sha256": hashlib.sha256(data["content"].encode()).hexdigest(),
                "embedding_model": settings().embedding_model,
                "chunk_size": data.get("chunk_size", 100),
                "source_class": "SIMULATED BUSINESS",
            },
        )
        s.add(doc)
        s.flush()
        for index, ((section, body), vector) in enumerate(zip(parts, vectors, strict=True)):
            s.add(
                Chunk(
                    id=f"{doc.id}_{index}",
                    document_id=doc.id,
                    title=doc.title,
                    section=section,
                    text=body,
                    version=doc.version,
                    effective_date=effective,
                    meta={"category": doc.category, "ordinal": index},
                    embedding=vector,
                )
            )
        if "rules" in data:
            s.add(Policy(document_id=doc.id, category=doc.category, rules=data["rules"]))
        return as_dict(doc)


def current_documents():
    return (
        KnowledgeDocument.active.is_(True),
        KnowledgeDocument.effective_date <= now(),
        or_(KnowledgeDocument.expires_at.is_(None), KnowledgeDocument.expires_at > now()),
    )


def active_policy(category):
    with session_scope() as s:
        row = s.execute(
            select(Policy, KnowledgeDocument)
            .join(KnowledgeDocument)
            .where(Policy.category == category, *current_documents())
            .order_by(KnowledgeDocument.version.desc())
        ).first()
        if not row:
            return None
        return {
            "policy_id": row[0].id,
            "document_id": row[1].id,
            "title": row[1].title,
            "version": row[1].version,
            "rules": row[0].rules,
            "effective_date": row[1].effective_date.isoformat(),
        }


def lexical_rerank(query, row):
    """Non-model feature scorer: coverage and exact title/section overlap. Not a cross-encoder."""
    q = set(tokenize(query))
    body = set(tokenize(row["text"]))
    header = set(tokenize(row["title"] + " " + row["section"]))
    return len(q & body) / max(len(q), 1) + 0.4 * len(q & header) / max(len(q), 1) + 0.2 * row["vector_score"]


def cached_search(query, mode="hybrid_rerank", top_k=5):
    from backend.cache import cache

    with session_scope() as s:
        active_ids = list(
            s.scalars(select(KnowledgeDocument.id).where(*current_documents()).order_by(KnowledgeDocument.id))
        )
    fingerprint = hashlib.sha256(json.dumps([query, mode, top_k, active_ids]).encode()).hexdigest()
    key = "opspilot:retrieval:" + fingerprint
    hit = cache.get(key)
    if hit is not None:
        return {
            **hit,
            "cache_hit": True,
            "cache_mode": "bounded_local" if cache.degraded_until > time.monotonic() else "redis",
        }
    result = search(query, mode, top_k)
    cache.set(key, result, ttl=30)
    return {
        **result,
        "cache_hit": False,
        "cache_mode": "bounded_local" if cache.degraded_until > time.monotonic() else "redis",
    }


def search(query, mode="hybrid_rerank", top_k=5, filters=None):
    started = time.perf_counter()
    if mode not in {"keyword", "dense", "hybrid", "hybrid_rerank"} or not 1 <= top_k <= 20:
        raise ValueError("Invalid retrieval mode or top_k")
    filters = filters or {}
    # All modes use the same active-policy filter; exact distance is appropriate for the small evaluation corpus.
    vector = embed_query(query) if mode != "keyword" else [0.0] * 384
    with session_scope() as s:
        stmt = select(Chunk, Chunk.embedding.cosine_distance(vector).label("distance")).join(KnowledgeDocument)
        stmt = stmt.where(*current_documents())
        if filters.get("category"):
            stmt = stmt.where(KnowledgeDocument.category == filters["category"])
        rows = s.execute(stmt).all()
    if not rows:
        return {
            "query": query,
            "mode": mode,
            "filters": filters,
            "candidates": [],
            "results": [],
            "duration_ms": (time.perf_counter() - started) * 1000,
            "embedding_model": settings().embedding_model,
            "reranker": "lexical-feature-v1 (non-model)",
        }
    texts = [tokenize(f"{r[0].title} {r[0].section} {r[0].text}") for r in rows]
    bm25 = BM25Okapi(texts).get_scores(tokenize(query))
    dense_scores = [1 - float(r[1]) if mode != "keyword" else 0.0 for r in rows]
    lexical_order = np.argsort(-bm25, kind="stable").tolist()
    dense_order = np.argsort(-np.array(dense_scores), kind="stable").tolist()
    candidates = []
    for i, (chunk, _) in enumerate(rows):
        score = float(bm25[i]) if mode == "keyword" else dense_scores[i]
        if mode.startswith("hybrid"):
            score = 1 / (60 + lexical_order.index(i) + 1) + 1 / (60 + dense_order.index(i) + 1)
        row = as_dict(chunk)
        row.update(chunk_id=chunk.id, lexical_score=float(bm25[i]), vector_score=dense_scores[i], score=score)
        candidates.append(row)
    candidates.sort(key=lambda r: (-r["score"], r["chunk_id"]))
    reranked = [dict(r) for r in candidates[: max(top_k, 15)]]
    if mode == "hybrid_rerank":
        for row in reranked:
            row["rerank_score"] = lexical_rerank(query, row)
        reranked.sort(key=lambda r: (-r["rerank_score"], r["chunk_id"]))
    # Low confidence retrieval remains visible in trace, but is not answer evidence.
    results = [r for r in reranked[:top_k] if r["lexical_score"] > 0 or r["vector_score"] >= 0.65]
    return {
        "query": query,
        "mode": mode,
        "filters": filters,
        "candidates": candidates[:30],
        "results": results,
        "duration_ms": (time.perf_counter() - started) * 1000,
        "embedding_model": settings().embedding_model,
        "reranker": "lexical-feature-v1 (non-model)" if mode == "hybrid_rerank" else None,
    }
