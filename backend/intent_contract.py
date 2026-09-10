"""Versioned meaning and next steps. These rules never establish eligibility or authorize money."""

VERSION = 2
TAXONOMY = """
Intent taxonomy v2. Choose the customer's requested goal, respecting explicit negation.
- ambiguous: the customer has not selected an outcome, is deciding between alternatives, or reports delivery
  damage without a preferred remedy. Asking whether to refund OR replace is uncertainty, not policy_conflict.
- policy_conflict: explicitly contradictory policy guidance, or a demand for remedies this NovaMart system
  cannot combine/support: both a full refund AND a replacement, partial refunds, or goodwill compensation.
  Use this to request human review; it does not mean a model has checked actual eligibility.
- knowledge_qa: general policy, comparison, settlement-time or warranty question without a selected order action.
- refund/replacement/cancellation: a selected action. A negated remedy is not the requested action.
  Missing order ID leaves that action category intact with order_id=null; the server will ask for the ID.
- order_query: current order/shipping facts; troubleshooting: technical help; out_of_scope: unrelated requests.
Do not infer a customer preference from their inconvenience, damage, membership or urgency.
Do not invent an order identifier or claim a policy check/approval already happened.
""".strip()


def with_contract(prompt: str) -> str:
    return prompt + "\n\n" + TAXONOMY


def disposition(category: str, order_id: str | None, *, version=VERSION) -> str:
    """Observable next-step contract; proposal_candidate is permission to check, never to execute."""
    if category == "ambiguous" or (version >= 2 and category == "missing_information"):
        return "clarify"
    if category == "policy_conflict" and version >= 2:
        return "review"
    if category in {"refund", "replacement", "cancellation"}:
        return "proposal_candidate" if order_id else "need_order"
    if category == "order_query":
        return "lookup" if order_id else "need_order"
    if category == "troubleshooting":
        return "troubleshoot"
    if category == "out_of_scope":
        return "out_of_scope"
    return "policy"


def next_step(category: str, order_id: str | None) -> dict | None:
    kind = disposition(category, order_id)
    if kind == "clarify":
        return {
            "kind": kind,
            "title": "Clarify the customer's preferred outcome",
            "question": "Would the customer prefer a refund, a replacement, or technical help? Record their answer before starting a new action request.",
            "detail": "No business action or proposal has been created. A preference is not approval or eligibility.",
            "draft": "Please confirm your preferred outcome: a refund, a replacement, or technical help. We will check eligibility after you choose.",
            "contract_version": VERSION,
        }
    if kind == "review":
        return {
            "kind": kind,
            "title": "A human policy review is needed",
            "question": "Record the conflicting guidance or requested exception, and ask support to review the current policy.",
            "detail": "The model has not determined eligibility. Do not promise an exception, create a refund proposal, or treat this as a customer's unresolved choice.",
            "draft": "Please share the conflicting policy statements or explain the exception you are requesting. A support reviewer must check the current policy before we proceed.",
            "contract_version": VERSION,
        }
    return None
