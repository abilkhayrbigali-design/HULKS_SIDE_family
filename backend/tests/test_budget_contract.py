"""New budget wire amounts are exact strings, separate from legacy provenance cost."""

from decimal import Decimal

import pytest
from test_contracts import CONTRACT, fixture, validator


@pytest.mark.parametrize("filename", ["disabled", "enabled", "waiting", "unknown-hold"])
def test_synthetic_budget_examples_preserve_amounts_and_hold_semantics(filename):
    budget = fixture(f"budget/{filename}.json")
    validator("AIBudget").validate(budget)
    assert Decimal(budget["available_usd"]) == max(
        Decimal("0"),
        Decimal(budget["limit_usd"])
        - Decimal(budget["committed_upper_usd"])
        - Decimal(budget["reserved_usd"]),
    )
    if budget["enabled"]:
        assert budget["blocked_reason"] is None
        assert Decimal(budget["available_usd"]) >= Decimal(budget["next_request_upper_usd"])
    if filename == "waiting":
        assert budget["active_reservations"] == 1
        assert budget["unknown_reservations"] == 0
        assert budget["blocked_reason"] == "AI_BUDGET_WAITING"
    if filename == "unknown-hold":
        assert budget["active_reservations"] == 0
        assert budget["unknown_reservations"] == 1
        assert budget["blocked_reason"] == "AI_BUDGET_EXCEEDED"


@pytest.mark.parametrize(
    "field",
    ["limit_usd", "committed_upper_usd", "reserved_usd", "available_usd", "next_request_upper_usd"],
)
@pytest.mark.parametrize("value", [1, 0.1, True, "1", "0.1", "01.000000", "-0.000001", "NaN"])
def test_budget_does_not_accept_floats_or_noncanonical_money_strings(field, value):
    budget = fixture("budget/enabled.json")
    budget[field] = value
    assert not validator("AIBudget").is_valid(budget)


def test_unknown_policy_can_report_null_quote_and_version():
    budget = fixture("budget/disabled.json")
    budget["limit_usd"] = budget["available_usd"] = "1.000000"
    budget["blocked_reason"] = "AI_BUDGET_POLICY_UNSUPPORTED"
    validator("AIBudget").validate(budget)


def test_budget_is_a_readonly_endpoint_with_safe_unavailable_response():
    path = CONTRACT["paths"]["/api/v1/ai-budget"]
    assert set(path) == {"get"}
    assert "requestBody" not in path["get"]
    assert set(path["get"]["responses"]) == {"200", "503"}
