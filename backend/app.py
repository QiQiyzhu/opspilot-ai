import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from backend.config import settings
from backend.providers import provider_readiness
from backend.db import session_scope, db_health
from backend.models import (
    Customer,
    Order,
    Inventory,
    SupportTicket,
    Refund,
    Replacement,
    Conversation,
    Message,
    AgentRun,
    Proposal,
    KnowledgeDocument,
    Chunk,
    Registry,
    Memory,
    EvaluationRun,
    Alert,
    RunEvent,
    as_dict,
)
from backend.security import current_user, require, Principal
from backend.business import get_entity, list_entities, add_note, propose, decide, cancel_run
from backend import rag, agent, registry, analytics
from backend.cache import limiter
from backend.mcp_server import mcp_app, MCPAuthentication


@asynccontextmanager
async def lifespan(app):
    if settings().seed_on_start:
        from backend.seed import seed

        await asyncio.to_thread(seed)
    # In-process worker interruption is observable, never silently converted into success.
    with session_scope() as s:
        for run in s.scalars(select(AgentRun).where(AgentRun.status.in_(["queued", "running"]))):
            run.status, run.state, run.error = (
                "failed",
                "FAILED",
                "Worker restarted; replay requires an explicit new run",
            )
    async with mcp_app.router.lifespan_context(mcp_app):
        yield
    for task in list(agent.TASKS.values()):
        task.cancel()
    if agent.TASKS:
        await asyncio.gather(*list(agent.TASKS.values()), return_exceptions=True)


app = FastAPI(title="OpsPilot AI • NovaMart SIMULATED BUSINESS", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origins.split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
)
router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
REPORT_FOLDER = Path(__file__).resolve().parents[1] / "evals" / "reports"


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationInput(Payload):
    customer_id: str = Field(max_length=64)
    title: str = Field("Support conversation", max_length=200)


class MessageInput(Payload):
    conversation_id: str
    text: str = Field(min_length=1, max_length=5000)
    order_id: str | None = None
    config: dict = Field(default_factory=dict)


class TicketInput(Payload):
    customer_id: str
    order_id: str | None = None
    subject: str = Field(min_length=1, max_length=300)


class NoteInput(Payload):
    text: str = Field(min_length=1, max_length=3000)
    idempotency_key: str = Field(min_length=3, max_length=160)


class ProposalInput(Payload):
    action: Literal["refund", "replacement", "cancel"]
    reason: str = Field(min_length=3, max_length=3000)
    idempotency_key: str = Field(min_length=3, max_length=160)
    run_id: str | None = None


class DecisionInput(Payload):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=3, max_length=3000)
    idempotency_key: str = Field(min_length=3, max_length=160)


class KnowledgeInput(Payload):
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1)
    format: Literal["md", "txt", "html", "json"]
    content: str = Field(min_length=1, max_length=500000)
    effective_date: str
    expires_at: str | None = None
    active: bool = True
    metadata: dict = Field(default_factory=dict)


class SearchInput(Payload):
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["keyword", "dense", "hybrid", "hybrid_rerank"] = "hybrid_rerank"
    top_k: int = Field(5, ge=1, le=20)
    filters: dict = Field(default_factory=dict)


class MemoryInput(Payload):
    customer_id: str
    scope: Literal["case", "preference", "operational"]
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=3000)
    source: str = Field(min_length=5, max_length=1000)
    expires_at: datetime | None = None


@app.get("/api/health")
def health():
    try:
        database = db_health()
    except Exception as exc:
        raise HTTPException(503, {"status": "database_unavailable", "error_type": type(exc).__name__}) from exc
    return {"status": "ok", "business": "SIMULATED BUSINESS", "provider": settings().provider, **database}


@router.get("/me")
def me(user: Principal = Depends(current_user)):
    return {**user.__dict__, "business": "SIMULATED BUSINESS", "provider": settings().provider}


def list_endpoint(model):
    def handler(
        customer_id: str | None = None,
        order_id: str | None = None,
        status: str | None = None,
        include_evaluation: bool = False,
    ):
        return list_entities(
            model, customer_id=customer_id, order_id=order_id, status=status, include_evaluation=include_evaluation
        )

    return handler


def get_endpoint(model):
    def handler(entity_id: str):
        return get_entity(model, entity_id)

    return handler


for path, model in [
    ("customers", Customer),
    ("orders", Order),
    ("inventory", Inventory),
    ("tickets", SupportTicket),
    ("refunds", Refund),
    ("replacements", Replacement),
    ("conversations", Conversation),
    ("runs", AgentRun),
    ("approvals", Proposal),
    ("knowledge", KnowledgeDocument),
    ("memories", Memory),
    ("alerts", Alert),
    ("evaluations", EvaluationRun),
]:
    router.add_api_route("/" + path, list_endpoint(model), methods=["GET"], name="list_" + path)
for path, model in [("customers", Customer), ("orders", Order), ("tickets", SupportTicket), ("approvals", Proposal)]:
    router.add_api_route("/" + path + "/{entity_id}", get_endpoint(model), methods=["GET"], name="get_" + path)


@router.post("/conversations")
def conversations(data: ConversationInput, user: Principal = Depends(current_user)):
    require(user, "operator", "admin")
    get_entity(Customer, data.customer_id)
    with session_scope() as s:
        row = Conversation(**data.model_dump())
        s.add(row)
        s.flush()
        return {**as_dict(row), "messages": []}


@router.get("/conversations/{entity_id}")
def conversation(entity_id: str):
    row = get_entity(Conversation, entity_id)
    with session_scope() as s:
        row["messages"] = [
            as_dict(m)
            for m in s.scalars(select(Message).where(Message.conversation_id == entity_id).order_by(Message.created_at))
        ]
    return row


@router.post("/messages", status_code=202)
async def messages(data: MessageInput, user: Principal = Depends(current_user)):
    require(user, "operator", "admin")
    if not limiter.allow(user.id):
        raise HTTPException(429, "Run creation rate limit exceeded")
    if data.config.get("fault"):
        require(user, "admin")
        if not settings().allow_faults:
            raise HTTPException(403, "Fault injection disabled")
    run_id = agent.create_run(data.conversation_id, data.text, data.order_id, data.config)
    agent.enqueue(run_id, user)
    return {"run_id": run_id, "conversation_id": data.conversation_id, "status": "queued"}


@router.get("/runs/{run_id}")
def run(run_id: str):
    return agent.run_detail(run_id)


@router.get("/runs/{run_id}/events")
async def events(run_id: str, request: Request, after: int = 0):
    agent.run_detail(run_id)
    try:
        cursor = max(after, int(request.headers.get("last-event-id", "0")))
    except ValueError:
        raise HTTPException(422, "Last-Event-ID must be an integer") from None

    async def stream():
        nonlocal cursor
        while True:
            if await request.is_disconnected():
                break
            with session_scope() as s:
                rows = [
                    as_dict(e)
                    for e in s.scalars(
                        select(RunEvent)
                        .where(RunEvent.run_id == run_id, RunEvent.sequence > cursor)
                        .order_by(RunEvent.sequence)
                    )
                ]
                status = s.get(AgentRun, run_id).status
            for row in rows:
                cursor = row["sequence"]
                yield f"id: {cursor}\nevent: {row['type']}\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
            if status in agent.TERMINAL:
                break
            if not rows:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: str, user: Principal = Depends(current_user)):
    require(user, "operator", "admin")
    row = agent.run_detail(run_id)
    if row["status"] in agent.TERMINAL:
        return row
    await asyncio.to_thread(cancel_run, run_id, user)
    task = agent.TASKS.get(run_id)
    if task:
        task.cancel()
    else:
        agent.event(run_id, "run.cancelled", {"reason": "Operator cancelled waiting run"})
    return agent.run_detail(run_id)


@router.post("/runs/{run_id}/replay", status_code=202)
async def replay(run_id: str, user: Principal = Depends(current_user)):
    row = agent.run_detail(run_id)
    return await messages(
        MessageInput(
            conversation_id=row["conversation_id"],
            text=row["input"],
            order_id=row["config"].get("order_id"),
            config=row["config"],
        ),
        user,
    )


@router.post("/tickets")
def create_ticket(data: TicketInput, user: Principal = Depends(current_user)):
    require(user, "operator", "admin")
    get_entity(Customer, data.customer_id)
    if data.order_id and get_entity(Order, data.order_id)["customer_id"] != data.customer_id:
        raise HTTPException(403, "Order/customer mismatch")
    with session_scope() as s:
        row = SupportTicket(**data.model_dump())
        s.add(row)
        s.flush()
        return as_dict(row)


@router.post("/tickets/{ticket_id}/notes")
def note(ticket_id: str, data: NoteInput, user: Principal = Depends(current_user)):
    return add_note(ticket_id, data.text, data.idempotency_key, user)


@router.post("/orders/{order_id}/proposals")
def proposal(order_id: str, data: ProposalInput, user: Principal = Depends(current_user)):
    if data.run_id is not None:
        raise HTTPException(403, "Run association is server-managed; staff proposals cannot attach an arbitrary run")
    return propose(order_id, data.action, data.reason, data.idempotency_key, user, data.run_id)


@router.post("/approvals/{proposal_id}/decision")
async def approval(proposal_id: str, data: DecisionInput, user: Principal = Depends(current_user)):
    result = await asyncio.to_thread(decide, proposal_id, data.decision, data.reason, data.idempotency_key, user)
    await agent.resume_approval(result)
    return result


@router.get("/tools")
def tools():
    from backend.tools import catalog

    return catalog()


@router.post("/knowledge")
def knowledge_ingest(data: KnowledgeInput, user: Principal = Depends(current_user)):
    require(user, "admin")
    try:
        return rag.ingest(data.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/knowledge/{entity_id}")
def knowledge_detail(entity_id: str):
    doc = get_entity(KnowledgeDocument, entity_id)
    with session_scope() as s:
        doc["chunks"] = [as_dict(c) for c in s.scalars(select(Chunk).where(Chunk.document_id == entity_id))]
    return doc


@router.post("/knowledge/{entity_id}/activate")
def knowledge_activate(entity_id: str, user: Principal = Depends(current_user)):
    require(user, "admin")
    with session_scope() as s:
        row = s.get(KnowledgeDocument, entity_id)
        if not row:
            raise HTTPException(404, "Document not found")
        for other in s.scalars(select(KnowledgeDocument).where(KnowledgeDocument.title == row.title).with_for_update()):
            other.active = other.id == row.id
        return as_dict(row)


@router.post("/retrieval/search")
def retrieval(data: SearchInput):
    return rag.search(data.query, data.mode, data.top_k, data.filters)


@router.get("/models")
def models():
    cfg = settings()
    readiness = provider_readiness(cfg)
    return {
        "items": [
            {
                "id": "fake-rules-v1",
                "provider": "fake",
                "configured": True,
                "description": "Deterministic intent router; not an LLM",
            },
            {
                "id": cfg.provider_model or "not-configured",
                "provider": "deepseek",
                **readiness,
                "description": "DeepSeek JSON intent; server authorization remains mandatory",
            },
            {
                "id": cfg.provider_model or "not-configured",
                "provider": "openai-compatible",
                **readiness,
                "description": "Opt-in real API provider",
            },
            {
                "id": cfg.provider_model or "not-configured",
                "provider": "qwen",
                **readiness,
                "description": "Qwen compatible endpoint adapter",
            },
        ],
        "embedding": {"model": cfg.embedding_model, "runtime": "ONNX CPU", "dimension": 384},
        "reranker": "lexical-feature-v1; not a model",
    }


@router.get("/prompts")
def prompts():
    return list_entities(Registry, kind="prompt")


@router.get("/workflows")
def workflows():
    return list_entities(Registry, kind="workflow")


@router.get("/prompts/{entity_id}")
@router.get("/workflows/{entity_id}")
def registry_detail(entity_id: str):
    return get_entity(Registry, entity_id)


@router.post("/prompts/{entity_id}/versions")
@router.post("/workflows/{entity_id}/versions")
def registry_version(entity_id: str, data: dict, user: Principal = Depends(current_user)):
    require(user, "admin")
    return registry.add_version(entity_id, data)


@router.get("/prompts/{entity_id}/diff")
@router.get("/workflows/{entity_id}/diff")
def registry_diff(entity_id: str, from_version: int, to_version: int):
    return registry.diff(entity_id, from_version, to_version)


@router.post("/prompts/{entity_id}/release")
def release(entity_id: str, data: dict, user: Principal = Depends(current_user)):
    require(user, "admin")
    return registry.release(entity_id, data.get("version"), data.get("evaluation_id"))


@router.post("/workflows/{entity_id}/run")
async def workflow_run(entity_id: str, data: MessageInput, user: Principal = Depends(current_user)):
    data.config["workflow_id"] = entity_id
    return await messages(data, user)


@router.post("/memories")
def memory(data: MemoryInput, user: Principal = Depends(current_user)):
    require(user, "operator", "admin")
    get_entity(Customer, data.customer_id)
    with session_scope() as s:
        row = Memory(**data.model_dump(), confidence=1.0)
        row.source = f"Operator {user.id} confirmation: {row.source}"
        s.add(row)
        s.flush()
        return as_dict(row)


@router.post("/memories/{entity_id}/invalidate")
def invalidate(entity_id: str, data: dict, user: Principal = Depends(current_user)):
    require(user, "operator", "admin")
    with session_scope() as s:
        row = s.get(Memory, entity_id)
        if not row:
            raise HTTPException(404, "Memory not found")
        row.valid = False
        row.source += " | invalidated by " + user.id + ": " + str(data.get("reason", "operator request"))
        return as_dict(row)


@router.delete("/memories/{entity_id}")
def delete_memory(entity_id: str, user: Principal = Depends(current_user)):
    require(user, "admin")
    with session_scope() as s:
        row = s.get(Memory, entity_id)
        if not row:
            raise HTTPException(404, "Memory not found")
        s.delete(row)
    return {"deleted": entity_id}


@router.get("/evaluations/datasets")
def datasets():
    from evals.datasets import dataset_catalog

    return dataset_catalog()


@router.get("/evaluations/reports")
def reports():
    items = []
    for path in sorted(REPORT_FOLDER.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            items.append({"file": path.name, "artifact_type": "invalid_json", "error": "Unable to read JSON artifact"})
            continue
        # Docker and other tools may emit a list/scalar, not a benchmark object.
        # One artifact must never hide all otherwise-valid benchmark reports.
        if isinstance(value, dict):
            items.append({**value, "file": path.name})
        else:
            items.append({"file": path.name, "artifact_type": "json_data", "data": value})
    return {"items": items}


@router.get("/evaluations/{entity_id}")
def evaluation_detail(entity_id: str):
    return get_entity(EvaluationRun, entity_id)


@router.post("/evaluations")
async def evaluation_run(data: dict, user: Principal = Depends(current_user)):
    require(user, "admin")
    from evals.runner import run_evaluation

    return await run_evaluation(data)


@router.get("/dashboard")
def dashboard():
    return analytics.dashboard()


@router.post("/alerts/evaluate")
def alerts_evaluate(user: Principal = Depends(current_user)):
    require(user, "admin")
    return {"items": analytics.evaluate_alerts()}


@router.post("/alerts/{entity_id}/acknowledge")
def acknowledge(entity_id: str, user: Principal = Depends(current_user)):
    require(user, "operator", "admin")
    with session_scope() as s:
        row = s.get(Alert, entity_id)
        if not row:
            raise HTTPException(404, "Alert not found")
        row.status = "acknowledged"
        return as_dict(row)


app.include_router(router)
app.mount("/mcp", MCPAuthentication(mcp_app))
frontend = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend.is_dir():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="console")
