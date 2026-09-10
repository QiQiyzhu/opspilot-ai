import pytest
from sqlalchemy import select
from backend.db import session_scope
from backend.models import Inventory, Proposal, Refund, Replacement, Order
from backend.business import list_entities
from evals import runner
from evals.datasets import agent_cases


@pytest.mark.asyncio
async def test_evaluation_reservation_uses_its_own_inventory_and_lists_exclude_fixtures(monkeypatch):
    case = next(c for c in agent_cases() if c["category"] == "replacement" and c["expected_final_outcome"] == "execute")
    monkeypatch.setattr(runner, "agent_cases", lambda: [case])
    with session_scope() as s:
        before = s.scalar(select(Inventory.available).where(Inventory.product_id == "prod_speaker"))
    metrics, rows = await runner.eval_agent()
    assert metrics["task_success_rate"] == 1
    with session_scope() as s:
        assert s.scalar(select(Inventory.available).where(Inventory.product_id == "prod_speaker")) == before
        proposal = s.scalar(select(Proposal).where(Proposal.run_id == rows[0]["run_id"]))
        order = s.get(Order, proposal.order_id)
        stock = s.scalar(select(Inventory).where(Inventory.product_id == order.product_id))
        assert order.product_id.startswith("eval_")
        assert stock.available == case["order_state"]["inventory"] - order.quantity
        oid = order.id
    for model in (Order, Inventory, Proposal, Refund, Replacement):
        for item in list_entities(model)["items"]:
            identifier = item.get("order_id") or item.get("product_id") or item["id"]
            assert not identifier.startswith(("eval_", "test_"))
    included = list_entities(Replacement, order_id=oid, include_evaluation=True)
    assert included["total"] == 1 and included["items"][0]["order_id"] == oid
