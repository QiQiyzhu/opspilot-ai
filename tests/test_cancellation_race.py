from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
import time
from uuid import uuid4
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, func, text
from backend.db import session_scope
from backend.models import Order, AgentRun, Conversation, Refund, now
from backend.business import propose, decide, cancel_run, get_entity
from backend.security import Principal
from backend.app import app

OP = Principal("race-op", "Concurrency test operator", "operator")
REVIEWER = Principal("race-reviewer", "Concurrency test reviewer", "approver")


def context(customer="cus_ava", state="running"):
    with session_scope() as s:
        order = Order(
            id="test_" + uuid4().hex,
            customer_id=customer,
            product_id="prod_speaker",
            amount_cents=12900,
            status="delivered",
            purchased_at=now() - timedelta(days=8),
            delivered_at=now() - timedelta(days=5),
        )
        conversation = Conversation(customer_id="cus_ava", title="Automated scenario race")
        s.add_all([order, conversation])
        s.flush()
        run = AgentRun(
            conversation_id=conversation.id,
            status=state,
            state="ACT",
            category="refund",
            input="Refund",
            config={"order_id": order.id},
        )
        s.add(run)
        s.flush()
        return order.id, run.id


def outcome(fn):
    try:
        return fn()
    except HTTPException as e:
        return {"http_status": e.status_code, "detail": e.detail}


def wait_for_database_lock_wait(run_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with session_scope() as s:
            waiting = s.scalar(
                text("""SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted
                AND objid=((hashtextextended(:key,0)) & 4294967295)::oid
                AND classid=((hashtextextended(:key,0) >> 32) & 4294967295)::oid"""),
                {"key": "run:" + run_id},
            )
        if waiting:
            return
        time.sleep(0.01)
    raise AssertionError("Contending request never appeared as an actual PostgreSQL advisory-lock waiter")


def test_approval_wins_linearization_cancel_waits_then_rejects():
    oid, rid = context()
    p = propose(oid, "refund", "Concurrent request", uuid4().hex, OP, rid)
    acquired, release, other_started = Event(), Event(), Event()

    def hold():
        acquired.set()
        assert release.wait(5)

    def cancel():
        other_started.set()
        return outcome(lambda: cancel_run(rid, OP))

    with ThreadPoolExecutor(max_workers=2) as pool:
        approving = pool.submit(decide, p["id"], "approve", "Reviewed", uuid4().hex, REVIEWER, False, hold)
        assert acquired.wait(5)
        cancelling = pool.submit(cancel)
        assert other_started.wait(2)
        wait_for_database_lock_wait(rid)
        assert not cancelling.done()
        release.set()
        approved = approving.result(5)
        cancelled = cancelling.result(5)
    assert approved["verification"]["verified"] and cancelled["http_status"] == 409
    assert get_entity(AgentRun, rid)["status"] != "cancelled"
    assert get_entity(Order, oid)["status"] == "refunded"
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Refund).where(Refund.order_id == oid)) == 1


def test_cancel_wins_linearization_approval_waits_then_rejects():
    oid, rid = context()
    p = propose(oid, "refund", "Concurrent request", uuid4().hex, OP, rid)
    acquired, release, other_started = Event(), Event(), Event()

    def hold():
        acquired.set()
        assert release.wait(5)

    def approve():
        other_started.set()
        return outcome(lambda: decide(p["id"], "approve", "Reviewed", uuid4().hex, REVIEWER))

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancelling = pool.submit(cancel_run, rid, OP, hold)
        assert acquired.wait(5)
        approving = pool.submit(approve)
        assert other_started.wait(2)
        wait_for_database_lock_wait(rid)
        assert not approving.done()
        release.set()
        assert cancelling.result(5)["status"] == "cancelled"
        assert approving.result(5)["http_status"] == 409
    assert get_entity(Order, oid)["status"] == "delivered"
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Refund).where(Refund.order_id == oid)) == 0


def test_proposal_rejects_cross_customer_run_association():
    oid, rid = context(customer="cus_noah")
    with pytest.raises(HTTPException) as e:
        propose(oid, "refund", "Wrong customer", uuid4().hex, OP, rid)
    assert e.value.status_code == 403


@pytest.mark.parametrize("state", ["completed", "cancelled", "waiting_approval", "failed"])
def test_proposal_rejects_nonrunning_run(state):
    oid, rid = context(state=state)
    with pytest.raises(HTTPException) as e:
        propose(oid, "refund", "Invalid state", uuid4().hex, OP, rid)
    assert e.value.status_code == 409


def test_proposal_rejects_different_order_bound_to_run():
    oid, rid = context()
    other, _ = context()
    with pytest.raises(HTTPException) as e:
        propose(other, "refund", "Wrong order", uuid4().hex, OP, rid)
    assert e.value.status_code == 409


def test_staff_api_cannot_attach_arbitrary_run():
    oid, rid = context()
    client = TestClient(app, headers={"Authorization": "Bearer demo-admin"})
    response = client.post(
        f"/api/orders/{oid}/proposals",
        json={"action": "refund", "reason": "Attach run", "idempotency_key": uuid4().hex, "run_id": rid},
    )
    assert response.status_code == 403
