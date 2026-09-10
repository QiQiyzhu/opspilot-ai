# Database design and actual SQL

The local runtime is PostgreSQL 17.11 with pgvector 0.8.6. `backend/models.py` declares the schema using SQLAlchemy; `backend/db.py` refuses to substitute another database. `CREATE EXTENSION vector` must succeed. Vector columns hold real 384-dimensional BGE ONNX embeddings. Exact cosine search is appropriate for the small seeded corpus; no HNSW acceleration is claimed.

| Table group | Relationships and constraints |
| --- | --- |
| customers / products / inventory | customer email and product SKU unique; inventory product foreign key and unique row |
| orders | customer/product FKs, immutable paid cents, status/version, delivery timestamp |
| tickets | customer/order FKs, operator notes and priority |
| knowledge_documents / policies / chunks | title+version unique; executable policy refers to a document; chunks preserve section/version/effective date/vector |
| conversations / messages / agent_runs | one customer context, immutable run config snapshots, response and outcome |
| proposals / refunds / replacements | proposal key unique; one refund and one replacement per order, separate proposal FK; business status excludes mutually incompatible actions |
| inventory_movements | one reservation journal per proposal, with order/product/inventory foreign keys and committed before/after/delta; allows verification without comparing to later global stock |
| run_events / tool_calls / audit_entries | run+sequence unique; append events; actor/before/after and idempotency key audit |
| registry / memories / evaluation_cases / evaluation_runs / alerts | version history, source-backed memory, frozen synthetic labels and recorded reports |

Indexes exist for customer lookup, orders.customer_id, orders.status, open tickets(customer_id,created_at) with a partial `status='open'` predicate, knowledge category, knowledge metadata GIN, and run(status,created_at). A B-tree on customer_id helps selective equality lookups; when almost every seeded order belongs to Ava, a sequential scan can be cheaper. Leading wildcard matching, functions on indexed columns, type casts and missing partial predicates can prevent index use. Tiny policy tables commonly use sequential scans even with valid GIN indexes. Never force an index merely to obtain a prettier EXPLAIN screenshot.

Actual JOIN/GROUP BY and metrics SQL is in [operations.sql](../analytics/sql/operations.sql). Four real `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plans are saved in [sql-explain.json](../evals/reports/sql-explain.json); run `python -m analytics.explain` after loading your database to regenerate them. They contain measured timings and planner choices, not hypothetical output.

```sql
CREATE INDEX ix_runs_status_created ON agent_runs(status, created_at);
SELECT c.id, c.name, count(r.id), sum(r.amount_cents)
FROM customers c JOIN orders o ON o.customer_id=c.id
LEFT JOIN refunds r ON r.order_id=o.id GROUP BY c.id,c.name;
BEGIN;
SELECT * FROM proposals WHERE id = :proposal_id FOR UPDATE;
SELECT * FROM orders WHERE id = :order_id FOR UPDATE;
-- Recheck active policy, order version and stock; insert refund, update order, append audit.
COMMIT;
```

The executable implementation uses bound parameters, transaction-scoped advisory locks for idempotency and row locks for business consistency. Unique constraints are the final backstop. Refund ledger write, order status and approval audit commit together; stock reservation also locks inventory. A separate session verifies committed state. Failed verification does not pretend the transaction was rolled back.

Schema bootstrap uses `create_all` for this new standalone version. Historical migration upgrades, DB roles with least privilege, backups, retention and point-in-time restore drills are outstanding production work. The local demo role owns its dedicated database; do not reuse it against a production database.
