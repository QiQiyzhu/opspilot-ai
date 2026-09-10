import json
from copy import deepcopy

import httpx
import pytest
from sqlalchemy import select, func
from fastapi import HTTPException

from backend import agent
from backend.config import Settings
from backend.db import session_scope
from backend.intent_contract import disposition, next_step, with_contract
from backend.models import Conversation, Proposal
from backend.providers import ModelResult
from backend.security import Principal
from evals.intent_contract_eval import evaluate, evaluate_rows, load_dataset


@pytest.mark.parametrize("category,kind", [("ambiguous", "clarify"), ("policy_conflict", "review")])
async def test_uncertain_intent_stops_before_business_tools_and_persists_next_step(monkeypatch, category, kind):
    async def response(message, prompt):
        assert "Intent taxonomy v2" in prompt
        return ModelResult({"category": category, "order_id": "ord_recent", "decision_summary": "Authored contract fixture"}, "fixture", 0, "fixture")

    monkeypatch.setattr(agent.PROVIDERS["fake"], "understand", response)
    with session_scope() as s:
        conversation = Conversation(customer_id="cus_ava", title="Intent next-step contract")
        s.add(conversation)
        s.flush()
        cid = conversation.id
        before = s.scalar(select(func.count()).select_from(Proposal))
    rid = agent.create_run(cid, "Please help with refund or replacement ord_recent", config={"intent_contract_version": 1})
    await agent.execute(rid, Principal("test-contract", "Test", "operator"))
    detail = agent.run_detail(rid)
    assert detail["status"] == "completed" and detail["next_step"]["kind"] == kind
    assert detail["config"]["intent_contract_version"] == 2  # client cannot bypass the server contract
    assert not detail["tool_calls"] and detail["proposal_id"] is None
    assert detail["response"] != "" and detail["next_step"]["draft"]
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Proposal)) == before


def test_policy_conflict_is_distinct_from_clarification_and_never_invents_eligibility():
    assert next_step("policy_conflict", "ord_x")["kind"] == "review"
    assert next_step("ambiguous", "ord_x")["kind"] == "clarify"
    assert next_step("refund", "ord_x") is None
    assert disposition("refund", None) == "need_order"
    assert disposition("refund", "ord_x") == "proposal_candidate"
    assert disposition("policy_conflict", "ord_x", version=1) == "policy"
    assert with_contract("original prompt").startswith("original prompt\n\n")


def test_custom_workflow_cannot_write_before_the_clarification_gate():
    from backend.registry import validate_workflow
    from backend.seed import SUPPORT_NODES

    nodes = deepcopy(SUPPORT_NODES)
    assert validate_workflow({"nodes": nodes})  # retrieval before interpretation is allowed
    nodes.insert(1, {"id": "premature-note", "type": "Tool", "config": {"name": "create_ticket_note"}})
    with pytest.raises(HTTPException) as error:
        validate_workflow({"nodes": nodes})
    assert error.value.status_code == 422


def test_ablation_scores_semantic_error_separately_from_json_and_next_step():
    rows = [{
        "variant": variant, "case_id": "case", "split": "test", "repeat": 1,
        "expected_category": "ambiguous", "expected_next": "clarify",
        "result": {"data": {"category": category, "order_id": "ord_x"}},
    } for variant, category in [("baseline", "refund"), ("taxonomy", "ambiguous")]]
    metrics = evaluate_rows(rows)
    assert metrics["baseline"]["premature_action_candidates"] == 1
    assert metrics["full"]["next_step_accuracy"] == 1
    assert metrics["workflow_only"]["premature_action_candidates"] == 1  # workflow cannot fix a wrongly confident action


async def test_frozen_evaluation_is_opt_in_budgeted_and_mock_results_are_not_real(tmp_path):
    calls = []

    def fail(request):
        calls.append(request)
        return httpx.Response(401, text="private server detail")

    cfg = Settings(_env_file=None, provider="deepseek", provider_model="deepseek-flash", provider_url="https://api.deepseek.com", provider_key="authored-test-key")
    transport = httpx.MockTransport(fail)
    path = tmp_path / "report.json"
    ready = await evaluate(split="test", config=cfg, transport=transport, output=path)
    assert ready["http_attempts"] == 0 and not calls and ready["planned_http_calls"] == 32
    with pytest.raises(ValueError, match="budget"):
        await evaluate(execute=True, split="test", max_calls=31, config=cfg, transport=transport)
    result = await evaluate(execute=True, split="test", config=cfg, transport=transport, output=path)
    assert len(calls) == 1 and result["status"] == "failed" and result["real_model_runs"] == 0
    assert "private server detail" not in path.read_text()
    assert json.loads(path.read_text())["gate"] is None
    assert len(load_dataset()["cases"]) == 24
