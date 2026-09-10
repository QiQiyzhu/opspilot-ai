from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select
from backend.db import session_scope
from backend.models import Order, Refund, Replacement, InventoryMovement, now
from backend.business import propose, decide, BusinessVerifier
from backend.security import Principal

OP = Principal("mutation-op", "Mutation test operator", "operator")
APP = Principal("mutation-reviewer", "Mutation test reviewer", "approver")


def order():
    oid = "test_" + uuid4().hex
    with session_scope() as s:
        s.add(
            Order(
                id=oid,
                customer_id="cus_ava",
                product_id="prod_speaker",
                quantity=1,
                amount_cents=12900,
                status="delivered",
                purchased_at=now() - timedelta(days=8),
                delivered_at=now() - timedelta(days=5),
            )
        )
    return oid


def executed(action):
    oid = order()
    p = propose(oid, action, "Mutation scenario", uuid4().hex, OP)
    result = decide(p["id"], "approve", "Reviewed approved parameters", uuid4().hex, APP)
    assert result["verification"]["verified"]
    return oid, p["id"]


def test_refund_verifier_rejects_wrong_ledger_amount():
    _, pid = executed("refund")
    with session_scope() as s:
        record = s.scalar(select(Refund).where(Refund.proposal_id == pid))
        record.amount_cents = 1
    result = BusinessVerifier.verify(pid)
    assert not result["verified"] and not result["checks"]["approved_amount_matches"]


@pytest.mark.parametrize(
    "action,model,check",
    [("refund", Refund, "ledger_order_matches"), ("replacement", Replacement, "record_order_matches")],
)
def test_verifier_rejects_wrong_order_association(action, model, check):
    _, pid = executed(action)
    other = order()
    with session_scope() as s:
        record = s.scalar(select(model).where(model.proposal_id == pid))
        record.order_id = other
    result = BusinessVerifier.verify(pid)
    assert not result["verified"] and not result["checks"][check]


def test_replacement_verifier_rejects_wrong_reserved_quantity():
    _, pid = executed("replacement")
    with session_scope() as s:
        movement = s.scalar(select(InventoryMovement).where(InventoryMovement.proposal_id == pid))
        movement.quantity_delta = -2
        movement.after_available = movement.before_available - 2
    result = BusinessVerifier.verify(pid)
    assert not result["verified"] and not result["checks"]["approved_quantity_matches"]


def test_replacement_verifier_rejects_broken_inventory_arithmetic():
    _, pid = executed("replacement")
    with session_scope() as s:
        movement = s.scalar(select(InventoryMovement).where(InventoryMovement.proposal_id == pid))
        movement.after_available = movement.before_available
    result = BusinessVerifier.verify(pid)
    assert not result["verified"] and not result["checks"]["reservation_arithmetic"]


def test_other_orders_later_inventory_changes_do_not_invalidate_reservation():
    _, first = executed("replacement")
    _, second = executed("replacement")
    a, b = BusinessVerifier.verify(first), BusinessVerifier.verify(second)
    assert a["verified"] and b["verified"]
    assert a["reservation"]["after_available"] == b["reservation"]["before_available"]
    assert "not current global stock" in a["inventory_verification_scope"]
