"""Normal business services. High-risk actions are only executed inside approval transactions."""

from sqlalchemy import select, text, func, or_
from fastapi import HTTPException
from backend.db import session_scope
from backend.models import (
    Order,
    Inventory,
    Product,
    SupportTicket,
    Refund,
    Replacement,
    Proposal,
    AuditEntry,
    KnowledgeDocument,
    Policy,
    AgentRun,
    Conversation,
    ToolCall,
    InventoryMovement,
    as_dict,
    now,
)
from backend.rag import current_documents
from backend.security import require


def get_entity(model, entity_id):
    with session_scope() as s:
        row = s.get(model, entity_id)
        if not row:
            raise HTTPException(404, f"{model.__name__} not found")
        result = as_dict(row)
        if model is Inventory:
            result["product"] = as_dict(s.get(Product, row.product_id))
        return result


def list_entities(model, **filters):
    with session_scope() as s:
        stmt = select(model)
        if not filters.pop("include_evaluation", False):
            if model.__tablename__ == "orders":
                stmt = stmt.where(~model.id.startswith("eval_"), ~model.id.startswith("test_"))
            elif model in (Refund, Replacement, Proposal, SupportTicket):
                stmt = stmt.where(
                    or_(
                        model.order_id.is_(None),
                        (~model.order_id.startswith("eval_")) & (~model.order_id.startswith("test_")),
                    )
                )
            elif model is Inventory:
                stmt = stmt.where(~model.product_id.startswith("eval_"), ~model.product_id.startswith("test_"))
            elif model.__tablename__ == "conversations":
                stmt = stmt.where(
                    ~model.title.startswith("SYNTHETIC BENCHMARK"),
                    ~model.title.startswith("Automated scenario"),
                    ~model.title.startswith("LOAD TEST"),
                )
            elif model.__tablename__ == "agent_runs":
                stmt = stmt.where(~model.config.has_key("evaluation_case"))
        for key, value in filters.items():
            if value is not None and hasattr(model, key):
                stmt = stmt.where(getattr(model, key) == value)
        total = s.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = s.scalars(stmt.order_by(model.created_at.desc()).limit(250)).all()
        items = [as_dict(r) for r in rows]
        if model is Inventory:
            for item in items:
                item["product"] = as_dict(s.get(Product, item["product_id"]))
        return {"items": items, "total": total}


def policy_in_session(s, category):
    row = s.execute(
        select(Policy, KnowledgeDocument)
        .join(KnowledgeDocument)
        .where(Policy.category == category, *current_documents())
        .order_by(KnowledgeDocument.version.desc())
    ).first()
    if row is None:
        raise HTTPException(409, "No active executable policy; escalate for review")
    return {"document_id": row[1].id, "title": row[1].title, "version": row[1].version, "rules": row[0].rules}


def eligibility_in_session(s, order, action):
    category = {"refund": "refund", "replacement": "warranty", "cancel": "shipping"}[action]
    policy = policy_in_session(s, category)
    rules = policy["rules"]
    age = (now() - order.delivered_at).days if order.delivered_at else None
    reason = "Eligible under current policy"
    eligible = True
    if action == "refund":
        eligible = order.status == "delivered" and age is not None and age <= rules["refund_days"]
        reason = f"Refund requires delivered status and delivery within {rules['refund_days']} days; age={age}, status={order.status}"
    elif action == "replacement":
        inventory = s.scalar(select(Inventory).where(Inventory.product_id == order.product_id))
        eligible = (
            order.status == "delivered"
            and age is not None
            and age <= rules["warranty_days"]
            and inventory is not None
            and inventory.available >= order.quantity
        )
        reason = f"Warranty limit {rules['warranty_days']} days; age={age}; available stock={inventory.available if inventory else 0}"
    elif action == "cancel":
        eligible = order.status in rules["cancellable_statuses"]
        reason = f"Cancellation allowed only before shipment; current status={order.status}"
    return {"eligible": eligible, "reason": reason, "action": action, "order_id": order.id, "policy": policy}


def eligibility(order_id, action):
    with session_scope() as s:
        order = s.get(Order, order_id)
        if not order:
            raise HTTPException(404, "Order not found")
        return eligibility_in_session(s, order, action)


def advisory_lock(s, key):
    # Transaction scoped, across processes. Hash collision only causes extra serialization.
    s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


def propose(order_id, action, reason, key, user, run_id=None):
    require(user, "operator", "admin")
    if action not in {"refund", "replacement", "cancel"}:
        raise HTTPException(422, "Unsupported action")
    with session_scope() as s:
        run = None
        if run_id:
            advisory_lock(s, "run:" + run_id)
            run = s.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
            if not run:
                raise HTTPException(404, "Associated run not found")
        advisory_lock(s, "proposal:" + key)
        existing = s.scalar(select(Proposal).where(Proposal.idempotency_key == key))
        if existing:
            if existing.order_id != order_id or existing.action != action or existing.run_id != run_id:
                raise HTTPException(409, "Idempotency key reused for different action")
            return as_dict(existing)
        if run and run.status != "running":
            raise HTTPException(409, "Only an active running agent may associate a proposal")
        order = s.scalar(select(Order).where(Order.id == order_id).with_for_update())
        if not order:
            raise HTTPException(404, "Order not found")
        if run:
            conversation = s.get(Conversation, run.conversation_id)
            if conversation.customer_id != order.customer_id:
                raise HTTPException(403, "Run conversation does not own this order")
            configured_order = run.config.get("order_id")
            observed = s.scalar(
                select(ToolCall.id).where(
                    ToolCall.run_id == run_id,
                    ToolCall.name == "get_order",
                    ToolCall.status == "success",
                    ToolCall.arguments["order_id"].astext == order_id,
                )
            )
            if (configured_order and configured_order != order_id) or (not configured_order and not observed):
                raise HTTPException(409, "Order is not bound to this run's verified business context")
            if run.proposal_id:
                raise HTTPException(409, "Run already has a proposal")
        check = eligibility_in_session(s, order, action)
        if not check["eligible"]:
            raise HTTPException(409, check)
        proposal = Proposal(
            order_id=order_id,
            action=action,
            reason=reason,
            evidence=[check["policy"]],
            parameters={
                "order_id": order_id,
                "amount_cents": order.amount_cents if action == "refund" else None,
                "quantity": order.quantity,
                "order_version": order.version,
            },
            requested_by=user.id,
            idempotency_key=key,
            run_id=run_id,
        )
        s.add(proposal)
        s.flush()
        if run:
            run.proposal_id = proposal.id
        return as_dict(proposal)


class BusinessVerifier:
    @staticmethod
    def verify(proposal_id):
        # Independent post-commit session: never treat a tool return as proof of a committed business effect.
        with session_scope() as s:
            p = s.get(Proposal, proposal_id)
            order = s.get(Order, p.order_id)
            item = None
            movement = None
            checks = {"proposal_executed": p.status == "executed", "order_exists": order is not None}
            if p.action == "refund":
                item = s.scalar(select(Refund).where(Refund.proposal_id == p.id))
                checks.update(
                    ledger_exists=item is not None,
                    ledger_order_matches=item is not None and item.order_id == p.order_id,
                    ledger_proposal_matches=item is not None and item.proposal_id == p.id,
                    approved_amount_matches=item is not None and item.amount_cents == p.parameters.get("amount_cents"),
                    order_amount_matches=order is not None and order.amount_cents == p.parameters.get("amount_cents"),
                    ledger_submitted=item is not None and item.status == "submitted",
                    order_status_matches=order is not None and order.status == "refunded",
                )
            elif p.action == "replacement":
                item = s.scalar(select(Replacement).where(Replacement.proposal_id == p.id))
                movement = s.scalar(select(InventoryMovement).where(InventoryMovement.proposal_id == p.id))
                quantity = p.parameters.get("quantity")
                stock = s.get(Inventory, movement.inventory_id) if movement else None
                checks.update(
                    record_exists=item is not None,
                    record_order_matches=item is not None and item.order_id == p.order_id,
                    record_requested=item is not None and item.status == "requested",
                    order_status_matches=order is not None and order.status == "replacement_requested",
                    reservation_exists=movement is not None,
                    reservation_order_matches=movement is not None and movement.order_id == p.order_id,
                    reservation_product_matches=movement is not None
                    and order is not None
                    and movement.product_id == order.product_id,
                    inventory_product_matches=stock is not None
                    and order is not None
                    and stock.product_id == order.product_id,
                    approved_quantity_matches=movement is not None
                    and isinstance(quantity, int)
                    and quantity > 0
                    and movement.quantity_delta == -quantity,
                    reservation_arithmetic=movement is not None
                    and movement.after_available == movement.before_available + movement.quantity_delta
                    and movement.after_available >= 0,
                )
            else:
                checks["order_status_matches"] = order is not None and order.status == "cancelled"
            valid = all(checks.values())
            evidence = {
                "verified": valid,
                "order_id": p.order_id,
                "observed_status": order.status if order else None,
                "record": as_dict(item),
                "checks": checks,
                "reservation": as_dict(movement),
                "inventory_verification_scope": "Committed proposal-specific reservation journal, not current global stock balance"
                if p.action == "replacement"
                else None,
                "checked_at": now().isoformat(),
                "method": "independent_database_read",
            }
            p.verification = evidence
            return evidence


def _decide_transaction(proposal_id, decision, reason, key, user, inject_write_failure=False, before_commit=None):
    require(user, "approver", "admin")
    with session_scope() as s:
        initial = s.get(Proposal, proposal_id)
        if not initial:
            raise HTTPException(404, "Proposal not found")
        if initial.run_id:
            # Same linearization lock as cancellation, always before proposal/order locks.
            advisory_lock(s, "run:" + initial.run_id)
            run = s.scalar(select(AgentRun).where(AgentRun.id == initial.run_id).with_for_update())
            if run.status == "cancelled":
                raise HTTPException(409, "The associated run was cancelled; create and review a new proposal")
        advisory_lock(s, "decision:" + key)
        audit = s.scalar(select(AuditEntry).where(AuditEntry.idempotency_key == key))
        if audit and (audit.target != proposal_id or audit.action != decision):
            raise HTTPException(409, "Idempotency key reused for a different decision")
        p = s.scalar(
            select(Proposal)
            .where(Proposal.id == proposal_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not p:
            raise HTTPException(404, "Proposal not found")
        if p.status != "pending":
            if (decision == "approve" and p.status == "executed") or (decision == "reject" and p.status == "rejected"):
                return as_dict(p)
            raise HTTPException(409, "Proposal already decided")
        order = s.scalar(select(Order).where(Order.id == p.order_id).with_for_update())
        before = as_dict(order)
        if decision == "approve":
            check = eligibility_in_session(s, order, p.action)
            if not check["eligible"]:
                raise HTTPException(409, {"message": "Eligibility changed; create new proposal", "check": check})
            if p.parameters["order_version"] != order.version:
                raise HTTPException(409, "Order changed since proposal; review a new proposal")
            if check["policy"]["document_id"] != p.evidence[0]["document_id"]:
                raise HTTPException(409, "Policy changed since proposal; review updated evidence")
            if p.action == "refund":
                s.add(Refund(order_id=order.id, proposal_id=p.id, amount_cents=order.amount_cents))
                order.status = "refunded"
            elif p.action == "replacement":
                stock = s.scalar(select(Inventory).where(Inventory.product_id == order.product_id).with_for_update())
                if stock.available < order.quantity:
                    raise HTTPException(409, "Stock changed")
                before_available = stock.available
                stock.available -= order.quantity
                s.add(
                    InventoryMovement(
                        proposal_id=p.id,
                        order_id=order.id,
                        inventory_id=stock.id,
                        product_id=order.product_id,
                        quantity_delta=-order.quantity,
                        before_available=before_available,
                        after_available=stock.available,
                    )
                )
                s.add(Replacement(order_id=order.id, proposal_id=p.id))
                order.status = "replacement_requested"
            else:
                order.status = "cancelled"
            order.version += 1
            p.status = "executed"
        elif decision == "reject":
            p.status = "rejected"
        else:
            raise HTTPException(422, "Decision must be approve or reject")
        p.approved_by, p.approved_at, p.decision_reason = user.id, now(), reason
        p.before_state, p.after_state = before, as_dict(order)
        s.add(
            AuditEntry(
                actor=user.id,
                action=decision,
                target=p.id,
                idempotency_key=key,
                detail={"reason": reason, "before": before, "after": as_dict(order), "action": p.action},
            )
        )
        if inject_write_failure:
            raise RuntimeError("Injected database write failure before commit")
        if before_commit:
            before_commit()  # Test hook; never exposed by REST/MCP.
    return get_entity(Proposal, proposal_id)


def decide(proposal_id, decision, reason, key, user, inject_write_failure=False, before_commit=None):
    result = _decide_transaction(proposal_id, decision, reason, key, user, inject_write_failure, before_commit)
    # Covers a retry after commit but before the first request managed to verify/respond.
    if result["status"] == "executed":
        BusinessVerifier.verify(proposal_id)
        result = get_entity(Proposal, proposal_id)
    return result


def cancel_run(run_id, user, before_commit=None):
    require(user, "operator", "admin")
    with session_scope() as s:
        advisory_lock(s, "run:" + run_id)
        run = s.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if not run:
            raise HTTPException(404, "Run not found")
        proposal = s.scalar(select(Proposal).where(Proposal.run_id == run_id, Proposal.status == "executed"))
        if proposal:
            raise HTTPException(409, "Business action already committed; cancellation cannot undo it")
        if run.status in {"completed", "failed", "cancelled"}:
            return as_dict(run)
        run.status, run.state = "cancelled", "FAILED"
        if before_commit:
            before_commit()  # Deterministic concurrency test hook, not an API parameter.
        return as_dict(run)


def add_note(ticket_id, text_value, key, user):
    require(user, "operator", "admin")
    with session_scope() as s:
        advisory_lock(s, "note:" + key)
        existing = s.scalar(select(AuditEntry).where(AuditEntry.idempotency_key == key))
        if existing:
            if existing.target != ticket_id or existing.detail.get("text") != text_value:
                raise HTTPException(409, "Idempotency key reused")
            return as_dict(s.get(SupportTicket, ticket_id))
        ticket = s.scalar(select(SupportTicket).where(SupportTicket.id == ticket_id).with_for_update())
        if not ticket:
            raise HTTPException(404, "Ticket not found")
        ticket.notes = ticket.notes + [{"text": text_value, "actor": user.id, "created_at": now().isoformat()}]
        s.add(
            AuditEntry(
                actor=user.id, action="ticket_note", target=ticket_id, idempotency_key=key, detail={"text": text_value}
            )
        )
        return as_dict(ticket)
