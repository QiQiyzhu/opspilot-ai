import json
from pathlib import Path
from sqlalchemy import text
from backend.db import engine

QUERIES = {
    "customer_orders": "SELECT * FROM orders WHERE customer_id='cus_ava' ORDER BY created_at DESC LIMIT 20",
    "open_tickets": "SELECT * FROM tickets WHERE status='open' AND customer_id='cus_ava'",
    "run_lookup": "SELECT * FROM agent_runs WHERE status='failed' ORDER BY created_at DESC LIMIT 20",
    "metadata": "SELECT id FROM knowledge_documents WHERE metadata @> jsonb_build_object('fixture',true)",
}

if __name__ == "__main__":
    results = {}
    with engine.begin() as conn:
        conn.execute(text("ANALYZE"))
        for name, sql in QUERIES.items():
            results[name] = {
                "sql": sql,
                "plan": conn.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)).scalar(),
            }
    folder = Path(__file__).parents[1] / "evals" / "reports"
    folder.mkdir(exist_ok=True)
    (folder / "sql-explain.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("Saved actual PostgreSQL EXPLAIN ANALYZE for", len(results), "queries")
