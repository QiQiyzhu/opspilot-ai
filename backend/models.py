from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Integer, ForeignKey, DateTime, Boolean, Float, Text, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from backend.db import Base


def now():
    return datetime.now(timezone.utc)


def uid():
    return uuid4().hex


class Entity:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Customer(Entity, Base):
    __tablename__ = "customers"
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    tier: Mapped[str] = mapped_column(String(30), default="standard")
    language: Mapped[str] = mapped_column(String(20), default="en")


class Product(Entity, Base):
    __tablename__ = "products"
    name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    warranty_days: Mapped[int] = mapped_column(Integer, default=365)


class Inventory(Entity, Base):
    __tablename__ = "inventory"
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), unique=True)
    available: Mapped[int] = mapped_column(Integer)
    warehouse: Mapped[str] = mapped_column(String(64), default="SIM-NORTH")


class Order(Entity, Base):
    __tablename__ = "orders"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True)
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tracking: Mapped[str | None] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)


class SupportTicket(Entity, Base):
    __tablename__ = "tickets"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"))
    subject: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(32), default="open")
    priority: Mapped[str] = mapped_column(String(32), default="normal")
    notes: Mapped[list] = mapped_column(JSONB, default=list)
    __table_args__ = (Index("ix_tickets_open", "customer_id", "created_at", postgresql_where=(status == "open")),)


class KnowledgeDocument(Entity, Base):
    __tablename__ = "knowledge_documents"
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    format: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    __table_args__ = (
        UniqueConstraint("title", "version"),
        Index("ix_knowledge_metadata", "metadata", postgresql_using="gin"),
    )


class Policy(Entity, Base):
    __tablename__ = "policies"
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"), unique=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    rules: Mapped[dict] = mapped_column(JSONB)


class Chunk(Entity, Base):
    __tablename__ = "chunks"
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    section: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    effective_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    embedding: Mapped[list] = mapped_column(Vector(384))


class Conversation(Entity, Base):
    __tablename__ = "conversations"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Support conversation")


class Message(Entity, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)


class AgentRun(Entity, Base):
    __tablename__ = "agent_runs"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    state: Mapped[str] = mapped_column(String(32), default="INTAKE")
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    input: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict] = mapped_column(JSONB)
    plan: Mapped[list] = mapped_column(JSONB, default=list)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    verification: Mapped[list] = mapped_column(JSONB, default=list)
    proposal_id: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[float | None] = mapped_column(Float)
    tokens: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_runs_status_created", "status", "created_at"),)


class RunEvent(Entity, Base):
    __tablename__ = "run_events"
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)


class ToolCall(Entity, Base):
    __tablename__ = "tool_calls"
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    transport: Mapped[str] = mapped_column(String(16))
    risk: Mapped[str] = mapped_column(String(32))
    arguments: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20))
    duration_ms: Mapped[float] = mapped_column(Float)


class Proposal(Entity, Base):
    __tablename__ = "proposals"
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"))
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSONB)
    parameters: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    requested_by: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    before_state: Mapped[dict | None] = mapped_column(JSONB)
    after_state: Mapped[dict | None] = mapped_column(JSONB)
    verification: Mapped[dict | None] = mapped_column(JSONB)


class Refund(Entity, Base):
    __tablename__ = "refunds"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="submitted")


class Replacement(Entity, Base):
    __tablename__ = "replacements"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="requested")


class InventoryMovement(Entity, Base):
    __tablename__ = "inventory_movements"
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), unique=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    inventory_id: Mapped[str] = mapped_column(ForeignKey("inventory.id"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    quantity_delta: Mapped[int] = mapped_column(Integer)
    before_available: Mapped[int] = mapped_column(Integer)
    after_available: Mapped[int] = mapped_column(Integer)


class AuditEntry(Entity, Base):
    __tablename__ = "audit_entries"
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    detail: Mapped[dict] = mapped_column(JSONB)


class Registry(Entity, Base):
    __tablename__ = "registry"
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    active_version: Mapped[int] = mapped_column(Integer, default=1)
    versions: Mapped[list] = mapped_column(JSONB)


class Memory(Entity, Base):
    __tablename__ = "memories"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    scope: Mapped[str] = mapped_column(String(20))
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid: Mapped[bool] = mapped_column(Boolean, default=True)


class EvaluationCase(Entity, Base):
    __tablename__ = "evaluation_cases"
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSONB)


class EvaluationRun(Entity, Base):
    __tablename__ = "evaluation_runs"
    kind: Mapped[str] = mapped_column(String(32))
    dataset_id: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    metrics: Mapped[dict] = mapped_column(JSONB)
    results: Mapped[list] = mapped_column(JSONB)
    config: Mapped[dict] = mapped_column(JSONB)


class Alert(Entity, Base):
    __tablename__ = "alerts"
    metric: Mapped[str] = mapped_column(String(100), index=True)
    threshold: Mapped[float] = mapped_column(Float)
    current_value: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="open")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def as_dict(row):
    if row is None:
        return None
    result = {}
    for column in row.__table__.columns:
        attr = "meta" if column.name == "metadata" else column.name
        value = getattr(row, attr)
        if column.name == "embedding":
            continue
        result[column.name] = value.isoformat() if isinstance(value, datetime) else value
    return result
