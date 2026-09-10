# OpsPilot API v1

Base `/api`, backend `8003`, Vite `5176` proxy `/api` to `http://127.0.0.1:8003`. All timestamps ISO UTC; IDs strings; monetary amounts integer cents. NovaMart is **SIMULATED BUSINESS**. Default model is `fake-rules-v1`, a deterministic test provider, not an LLM. Never label synthetic evaluation as real customer effectiveness.

## Authentication

`GET /api/health` public. Every other endpoint uses `Authorization: Bearer <token>`; browser stores token only in sessionStorage. Server maps token to identity and role (`viewer`, `operator`, `approver`, `admin`); clients never choose identity/role in approval payloads. On local setup, `.env` config contains development tokens, documented as local only. UI has connection/token settings; frontend must not bake token into bundle. `GET /api/me` -> `{id,name,role,business:"SIMULATED BUSINESS",provider:"fake"}`. All errors FastAPI `{detail:string|object}`. No external real actions or real payment processing.

## Business console

List endpoints return `{items:[],total:number}`. `GET /customers`, `/orders`, `/inventory`, `/tickets`, `/refunds`, `/replacements`, `/conversations`, `/runs`, `/approvals`, `/knowledge`, `/prompts`, `/workflows`, `/evaluations`, `/memories`, `/alerts`. Optional filters customer_id, order_id, status where relevant. `GET /customers/{id}`, `/orders/{id}`, `/tickets/{id}` detail.

Default business lists exclude `eval_`/`test_` orders and their inventory, approval/refund/replacement/ticket records, benchmark conversations and evaluation runs. Pass `include_evaluation=true` to inspect those fixtures. Evaluation reports and analytics retain their full measured populations; list filtering never deletes evidence.

Customer: `{id,name,email,tier,language,created_at}`. Order: `{id,customer_id,product_id,quantity,amount_cents,status,purchased_at,delivered_at,tracking,version}`. Inventory: `{id,product_id,available,warehouse}`; product included as `product:{id,name,sku,warranty_days}`. Ticket: `{id,customer_id,order_id,subject,status,priority,notes:[{text,actor,created_at}],created_at}`. `POST /tickets` `{customer_id,order_id?,subject}`; `POST /tickets/{id}/notes` `{text,idempotency_key}`. Refund/Replacement `{id,order_id,proposal_id,status,amount_cents? ,created_at}`.

## Conversations and live runs

`POST /conversations` `{customer_id,title?}` -> Conversation `{id,customer_id,title,created_at,messages:[]}`.
`GET /conversations/{id}` includes `messages:[{id,role,text,run_id?,created_at}]`.
`POST /messages` `{conversation_id,text,order_id?,config?:{provider:"fake"|"openai-compatible"|"qwen",retrieval:"keyword"|"dense"|"hybrid"|"hybrid_rerank",top_k:5,transport:"native"|"mcp",memory:true,multi_agent:false,prompt_version:1,workflow_id:"support-qa",workflow_version:1}}` -> `{run_id,conversation_id,status:"queued"}`.
`GET /runs/{id}` -> `{id,conversation_id,status,state,category,input,response,config,plan:[],evidence:[],verification:[],tool_calls:[],trace:[],proposal_id?,duration_ms,tokens:null|{input,output},error?,created_at}`.
Terminal status `completed|failed|cancelled`, intermediate `queued|running|waiting_approval`. State machine `INTAKE|UNDERSTAND|RETRIEVE|PLAN|ACT|VERIFY|RESPOND|ESCALATE|COMPLETE|FAILED`.
`POST /runs/{id}/cancel` `{}`; `POST /runs/{id}/replay` `{}` -> new run using immutable config snapshot (high risk creates a fresh proposal; never auto approval).

`GET /runs/{id}/events?after=0` real SSE, use fetch+ReadableStream to attach Authorization (EventSource cannot). Each event `id: <sequence>`, `event: <type>`, `data: {sequence,type,run_id,created_at,payload}`. Supports `Last-Event-ID`. Events `run.started`, `plan.created`, `retrieval.completed`, `tool.started`, `tool.completed`, `approval.required`, `verification.completed`, `response.delta` payload `{text}`, `run.completed`, `run.failed`, `run.cancelled`, `security.detected`, `fallback.activated`. Trace persisted; disconnect does not cancel business run. Reconnect replays stored events.

## Approval (real server authorization and transaction)

Proposal `{id,run_id,order_id,action:"refund"|"replacement"|"cancel",reason,evidence:[],parameters:{},status:"pending"|"executed"|"rejected"|"failed",requested_by,approved_by?,approved_at?,before_state?,after_state?,verification?}`.
`POST /approvals/{id}/decision` `{decision:"approve"|"reject",reason,idempotency_key}` -> updated Proposal. Approver/admin only; actor derived from server token. Approval and cancellation share a run lock before proposal+order locks, establishing commit order. Approval rechecks policy/stock, executes once, writes audit, commits, rereads via verifier, and resumes the waiting run. Verification includes per-check booleans and, for replacement, a proposal-specific reservation journal. An already committed action cannot be cancelled; cancellation winning the lock prevents late approval. UI must show reason, policy evidence, order, action, parameters before approve; no optimistic "success".
`POST /orders/{id}/proposals` `{action,reason,idempotency_key}` operator/admin -> pending proposal; does not execute. Client-supplied `run_id` is rejected: association is managed inside the Agent and validated against conversation customer, order and active run. `GET /tools` returns schemas/permissions/risk/timeout.

## Knowledge and retrieval

Knowledge `{id,title,category,version,active,effective_date,expires_at,format,content,metadata,chunks:[{id,section,text,version,effective_date,metadata}]}`. `POST /knowledge` `{title,category,version:1,format:"md"|"txt"|"html"|"json",content,effective_date:"YYYY-MM-DD",expires_at:null,active:true,metadata:{}}` -> ingested document. `POST /knowledge/{id}/activate` `{}`. New active version invalidates prior versions of same title. `POST /retrieval/search` `{query,mode:"hybrid_rerank",top_k:5,filters?:{category}}` -> `{query,mode,filters,candidates:[{chunk_id,document_id,title,section,text,version,lexical_score,vector_score,score,rerank_score}],results:[...],duration_ms,embedding_model,reranker}`. Use returned evidence, do not invent citations.

## Registry / workflow / memory

`GET /models` -> `{items:[{id,provider,configured,description}]}`.
`GET /prompts/{id}` -> `{id,name,active_version,versions:[{version,content,created_at}]}`; `POST /prompts/{id}/versions` `{content}`; `GET /prompts/{id}/diff?from_version=1&to_version=2` -> `{diff:string}`; `POST /prompts/{id}/release` `{version,evaluation_id}` applies offline gate (409 when fail).
Workflow same version shape with `definition:{nodes:[{id,type:"Input"|"Retrieve"|"LLM"|"Tool"|"Condition"|"Approval"|"Output",config:{}}]}`. `POST /workflows/{id}/versions` `{definition}`; GET diff. Ordered validated workflow, not a claimed general DAG. `POST /workflows/{id}/run` same message payload plus version. Validation forbids high-risk execution bypassing approval.
Memory `{id,customer_id,scope:"case"|"preference"|"operational",key,value,source,confidence,expires_at,valid,created_at}`; `POST /memories` accepts verified operator fact `{customer_id,scope,key,value,source,expires_at?}`; `POST /memories/{id}/invalidate` `{reason}`; `DELETE /memories/{id}` admin. UI must not write generated guesses automatically.

## Evaluation / operations

`GET /evaluations/datasets` -> `{items:[{id,label,kind,case_count,provenance,human_review_status}]}`; `GET /evaluations/{id}` returns `{id,kind,status,provider,dataset_id,metrics,results:[],config,created_at}`; `POST /evaluations` `{kind:"rag"|"agent",dataset_id?,prompt_version:1,mode?:"hybrid_rerank"}` performs bounded actual evaluation (can take seconds), returns completed persisted report; synthetic badges required. `GET /evaluations/reports` -> shipped reproducible actual benchmark report summaries (empty if not run).
`GET /dashboard` -> `{business,provider,run_count,completed,failed,waiting_approval,p50_ms,p95_ms,tool_error_rate,escalation_rate,unsafe_action_count,token_usage:null|number,task_success_rate:null|number,retrieval_recall:null|number,category_counts:[],daily_runs:[],recent_runs:[],alerts:[],limitations:[]}`. Success/recall come from evaluated labeled cases; completion is not task success. Null means unavailable.
`POST /alerts/evaluate` `{}` computes actual recorded rules. `POST /alerts/{id}/acknowledge` `{}`. Failure injection available **only when enabled in dev server** via run config `fault:"provider_timeout"|"redis_unavailable"|"retrieval_error"|"tool_timeout"|"invalid_tool_schema"`; never a production public control.

## Demo seed

Stable customer `cus_ava`, orders `ord_recent` (delivered 5 days, refund/replacement eligible), `ord_old` (delivered 90 days, refund ineligible), `ord_pending` (unshipped), `ord_damaged` (eligible warranty). Other examples loaded in lists. Seed idempotent; does not reset existing decisions. Four demo walkthroughs in docs/demo.md. Clean demo data reset is CLI only and explicitly destructive for the selected demo database.
