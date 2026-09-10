"""Actual rechunking + ONNX indexing into a PostgreSQL temporary vector table. No production mutation."""

import json
import time
import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import select, text
from backend.db import engine, session_scope
from backend.models import KnowledgeDocument, now
from backend.rag import (
    current_documents,
    parse_sections,
    chunk_sections,
    embed_documents,
    embed_query,
    tokenize,
    lexical_rerank,
)
from evals.datasets import rag_cases
from evals.runner import retrieval_metrics, aggregate_rag, save


def run():
    with session_scope() as s:
        docs = list(s.scalars(select(KnowledgeDocument).where(*current_documents())))
    comparisons = []
    for size in [40, 100, 240]:
        corpus = []
        for doc in docs:
            for section, body in chunk_sections(parse_sections(doc.content, doc.format), size, min(20, size // 4)):
                corpus.append({"document_id": doc.id, "section": section, "title": doc.title, "text": body})
        started = time.perf_counter()
        vectors = embed_documents([f"{r['title']} {r['section']}: {r['text']}" for r in corpus])
        index_ms = (time.perf_counter() - started) * 1000
        bm25 = BM25Okapi([tokenize(r["title"] + " " + r["section"] + " " + r["text"]) for r in corpus])
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TEMP TABLE ablation_chunks (id int PRIMARY KEY, embedding vector(384)) ON COMMIT DROP")
            )
            conn.execute(
                text("INSERT INTO ablation_chunks (id,embedding) VALUES (:id,CAST(:v AS vector))"),
                [{"id": i, "v": json.dumps(v)} for i, v in enumerate(vectors)],
            )
            for mode in ["keyword", "dense", "hybrid", "hybrid_rerank"]:
                for top_k in [3, 5, 10]:
                    rows = []
                    for case in rag_cases():
                        started = time.perf_counter()
                        embed_query.cache_clear()
                        qv = embed_query(case["question"]) if mode != "keyword" else [0.0] * 384
                        scores = conn.execute(
                            text("SELECT id, 1 - (embedding <=> CAST(:v AS vector)) AS score FROM ablation_chunks"),
                            {"v": json.dumps(qv)},
                        ).all()
                        dense = [float(r.score) if mode != "keyword" else 0.0 for r in scores]
                        lexical = bm25.get_scores(tokenize(case["question"]))
                        lexorder = np.argsort(-lexical, kind="stable").tolist()
                        denorder = np.argsort(-np.array(dense), kind="stable").tolist()
                        candidates = []
                        for i, record in enumerate(corpus):
                            score = float(lexical[i]) if mode == "keyword" else dense[i]
                            if mode.startswith("hybrid"):
                                score = 1 / (61 + lexorder.index(i)) + 1 / (61 + denorder.index(i))
                            candidates.append(
                                {**record, "score": score, "lexical_score": float(lexical[i]), "vector_score": dense[i]}
                            )
                        candidates.sort(key=lambda r: -r["score"])
                        ranked = candidates[: max(top_k, 15)]
                        if mode == "hybrid_rerank":
                            ranked.sort(key=lambda r: -lexical_rerank(case["question"], r))
                        selected = [r for r in ranked[:top_k] if r["lexical_score"] > 0 or r["vector_score"] >= 0.65]
                        rows.append(
                            {
                                "case_id": case["id"],
                                **retrieval_metrics(selected, case),
                                "duration_ms": (time.perf_counter() - started) * 1000,
                            }
                        )
                    metrics = aggregate_rag(rows)
                    comparisons.append(
                        {
                            "chunk_words": size,
                            "chunk_count": len(corpus),
                            "mode": mode,
                            "top_k": top_k,
                            "index_ms": index_ms,
                            **metrics,
                        }
                    )
    report = {
        "created_at": now().isoformat(),
        "provenance": "SYNTHETIC BENCHMARK",
        "results": comparisons,
        "implementation": "PostgreSQL temporary vector table, exact cosine; BAAI/bge-small-en-v1.5 ONNX CPU; query cache cleared per case",
        "limitations": "Corpus-scale development benchmark, no held-out real users. Answer success is gold-evidence coverage proxy, not LLM answer quality. Human review pending.",
    }
    save("rag-ablation", report)
    print(json.dumps(comparisons, indent=2))


if __name__ == "__main__":
    run()
