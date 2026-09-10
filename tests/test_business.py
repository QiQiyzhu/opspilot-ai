from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from backend.db import session_scope, db_health
from backend.models import Order, Refund, Proposal, AuditEntry, now
from backend.business import propose, decide, add_note, get_entity, BusinessVerifier
from backend.security import Principal

OP = Principal("test-op", "Test operator", "operator")
APP = Principal("test-app", "Test approver", "approver")
VIEW = Principal("test-view", "Test viewer", "viewer")


def fresh_order(status="delivered", age=5):
    oid = "test_" + uuid4().hex
    with session_scope() as s:
        s.add(
            Order(
                id=oid,
                customer_id="cus_ava",
                product_id="prod_speaker",
                amount_cents=12900,
                status=status,
                purchased_at=now() - timedelta(days=age + 3),
                delivered_at=now() - timedelta(days=age),
            )
        )
    return oid


def test_real_postgresql_pgvector():
    h = db_health()
    assert "PostgreSQL" in h["database"] and h["pgvector"]


@pytest.mark.parametrize(
    "action,status", [("refund", "delivered"), ("replacement", "delivered"), ("cancel", "pending")]
)
def test_action_approval_and_independent_verification(action, status):
    oid = fresh_order(status)
    p = propose(oid, action, "Request test", uuid4().hex, OP)
    assert get_entity(Order, oid)["status"] == status
    p = decide(p["id"], "approve", "Reviewed evidence", uuid4().hex, APP)
    assert p["approved_by"] == APP.id and p["verification"]["verified"]
    assert p["before_state"]["status"] != p["after_state"]["status"]
    assert BusinessVerifier.verify(p["id"])["method"] == "independent_database_read"


def test_concurrent_same_refund_request_executes_once_and_retry_returns_verified():
    oid = fresh_order()
    p = propose(oid, "refund", "Request", uuid4().hex, OP)
    key = uuid4().hex

    def approve(_):
        return decide(p["id"], "approve", "Concurrent test", key, APP)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(approve, range(12)))
    assert all(r["verification"]["verified"] for r in results)
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Refund).where(Refund.order_id == oid)) == 1
        assert s.scalar(select(func.count()).select_from(AuditEntry).where(AuditEntry.target == p["id"])) == 1


def test_different_concurrent_proposals_cannot_refund_same_order_twice():
    oid = fresh_order()
    p1 = propose(oid, "refund", "Request one", uuid4().hex, OP)
    p2 = propose(oid, "refund", "Request two", uuid4().hex, OP)

    def approve(p):
        try:
            return decide(p["id"], "approve", "Review", uuid4().hex, APP)["status"]
        except HTTPException as e:
            return e.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(approve, [p1, p2]))
    assert sorted(map(str, values)) == ["409", "executed"]


def test_transaction_rollback_and_timeout_retry():
    oid = fresh_order()
    p = propose(oid, "refund", "Request", uuid4().hex, OP)
    key = uuid4().hex
    with pytest.raises(RuntimeError, match="Injected"):
        decide(p["id"], "approve", "Review", key, APP, inject_write_failure=True)
    assert get_entity(Order, oid)["status"] == "delivered"
    assert get_entity(Proposal, p["id"])["status"] == "pending"
    first = decide(p["id"], "approve", "Review", key, APP)
    # Caller loses first response after commit, then retries same request.
    second = decide(p["id"], "approve", "Review", key, APP)
    assert first["id"] == second["id"] and second["verification"]["verified"]


@pytest.mark.parametrize("user", [OP, VIEW])
def test_approval_server_role_blocks_unprivileged(user):
    p = propose(fresh_order(), "refund", "Request", uuid4().hex, OP)
    with pytest.raises(HTTPException) as exc:
        decide(p["id"], "approve", "Spoof reviewer", uuid4().hex, user)
    assert exc.value.status_code == 403


def test_idempotency_argument_collision_rejected():
    key = uuid4().hex
    propose(fresh_order(), "refund", "Request", key, OP)
    with pytest.raises(HTTPException) as exc:
        propose(fresh_order(), "refund", "Other order", key, OP)
    assert exc.value.status_code == 409


def test_policy_age_enforced_before_proposal():
    with pytest.raises(HTTPException) as exc:
        propose(fresh_order(age=31), "refund", "Demand illegal refund", uuid4().hex, OP)
    assert exc.value.status_code == 409


def test_note_idempotency_and_viewer_denial():
    key = uuid4().hex
    a = add_note("tic_refund", "Test idempotent note", key, OP)
    b = add_note("tic_refund", "Test idempotent note", key, OP)
    assert len(a["notes"]) == len(b["notes"])
    with pytest.raises(HTTPException):
        add_note("tic_refund", "Unauthorized", uuid4().hex, VIEW)
