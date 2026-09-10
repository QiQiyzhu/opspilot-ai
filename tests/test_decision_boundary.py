from evals.decision_case import execute_boundary


def test_refund_evidence_does_not_bypass_reviewer_or_stale_eligibility():
    result = execute_boundary(include_retrieval=False)
    assert result["checks"]["stale_eligibility_rechecked"]
    stale = next(s for s in result["steps"] if s["id"] == "stale-eligibility")
    assert stale["observed"]["status_code"] == 409
    assert stale["database_after"]["proposal_status"] == "pending"
    assert stale["database_after"]["refund_count"] == stale["database_after"]["audit_count"] == 0
