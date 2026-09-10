-- Only observed runs. Completion is not labeled task success.
SELECT created_at::date AS day, count(*) AS runs
FROM agent_runs GROUP BY day ORDER BY day;

SELECT category, count(*) AS runs,
       avg((status = 'completed')::int) AS completion_rate
FROM agent_runs GROUP BY category;

SELECT name, count(*) AS calls, avg((status = 'error')::int) AS tool_error_rate
FROM tool_calls GROUP BY name;

SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms
FROM agent_runs WHERE duration_ms IS NOT NULL;

SELECT avg(steps) AS average_resolution_steps FROM
 (SELECT r.id, count(t.id) AS steps FROM agent_runs r
  LEFT JOIN tool_calls t ON t.run_id = r.id GROUP BY r.id) x;

SELECT avg((category IN ('out_of_scope','ambiguous') OR status='failed')::int) AS escalation_proxy
FROM agent_runs;

-- Labeled synthetic task success, never renamed to real customer effectiveness.
SELECT config->>'prompt_version' AS prompt_version,
       metrics->>'task_success_rate' AS synthetic_task_success_rate,
       provider, created_at
FROM evaluation_runs WHERE kind='agent' ORDER BY created_at;

SELECT result->>'category' AS category,
       avg((result->>'task_success')::boolean::int) AS synthetic_success
FROM evaluation_runs, jsonb_array_elements(results) AS result
WHERE kind='agent' GROUP BY result->>'category';

-- Useful business joins and aggregate: submitted simulated refunds per customer.
SELECT c.id,c.name,count(r.id) AS refund_count,sum(r.amount_cents) AS cents
FROM customers c JOIN orders o ON o.customer_id=c.id
LEFT JOIN refunds r ON r.order_id=o.id GROUP BY c.id,c.name ORDER BY cents DESC NULLS LAST;
