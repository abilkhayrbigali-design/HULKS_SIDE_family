"""Offline policy configuration boundaries, independent of any provider or ledger."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.config import ConfigurationUnavailable, Settings


def test_default_budget_is_zero_and_tier_is_explicit_standard():
    settings = Settings(_env_file=None)
    assert settings.ai_budget_usd == Decimal("0")
    assert settings.llm_service_tier == "default"
    assert settings.llm_price_version == ""
    # Configuration of the key remains separate from the persisted spending policy.
    with pytest.raises(ConfigurationUnavailable, match="AI API key is not configured"):
        settings.require_llm()


@pytest.mark.parametrize(
    ("value", "expected_micro_usd"),
    [
        ("0", 0),
        ("0.000001", 1),
        ("1.0000000", 1_000_000),
        ("12.345678", 12_345_678),
        ("9223372036854.775807", 2**63 - 1),
    ],
)
def test_budget_preserves_exact_micro_usd(value, expected_micro_usd):
    amount = Settings(_env_file=None, CQA_AI_BUDGET_USD=value).ai_budget_usd
    assert isinstance(amount, Decimal)
    assert amount * 1_000_000 == expected_micro_usd


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        "",
        "NaN",
        "sNaN",
        "Infinity",
        "-Infinity",
        "-0.000001",
        "0.0000001",
        "9223372036854.775808",
    ],
)
def test_budget_rejects_nonfinite_negative_fractional_micro_usd_and_overflow(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, CQA_AI_BUDGET_USD=value)


@pytest.mark.parametrize("tier", ["auto", "flex", "priority", "scale", "", "DEFAULT"])
def test_unsupported_service_tiers_are_rejected(tier):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, CQA_LLM_SERVICE_TIER=tier)


def test_budget_and_tier_load_from_environment_without_dotenv(monkeypatch):
    monkeypatch.setenv("CQA_AI_BUDGET_USD", "1.234567")
    monkeypatch.setenv("CQA_LLM_SERVICE_TIER", "default")
    monkeypatch.setenv("CQA_LLM_PRICE_VERSION", "gpt-6-luna-standard-2026-11-08-v1")
    settings = Settings(_env_file=None)
    assert settings.ai_budget_usd == Decimal("1.234567")
    assert settings.llm_service_tier == "default"
    assert settings.llm_price_version == "gpt-6-luna-standard-2026-11-08-v1"


def test_readonly_configuration_allows_an_unknown_model_without_authorizing_spend():
    settings = Settings(
        _env_file=None, OPENAI_MODEL="unsupported-model", CQA_LLM_PRICE_VERSION="unknown-version"
    )
    assert settings.openai_model == "unsupported-model"
    assert settings.llm_price_version == "unknown-version"
    assert settings.ai_budget_usd == 0


def test_presence_of_a_key_does_not_enable_budget():
    settings = Settings(_env_file=None, OPENAI_API_KEY="synthetic-invalid-test-key")
    settings.require_llm()
    assert settings.ai_budget_usd == Decimal("0")


def test_invalid_budget_diagnostic_does_not_include_its_input():
    marker = "synthetic-private-configuration-marker"
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, CQA_AI_BUDGET_USD=marker)
    assert marker not in str(caught.value)


@pytest.mark.parametrize("value", [" ", "\t", "\r\n", "\u00a0", "\u2003"])
def test_blank_model_is_rejected_before_readonly_budget_serialization(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, OPENAI_MODEL=value)


@pytest.mark.parametrize("value", ["unknown-model", " gpt-6-luna "])
def test_nonblank_model_is_preserved_for_exact_provider_policy_check(value):
    assert Settings(_env_file=None, OPENAI_MODEL=value).openai_model == value


def test_invalid_model_diagnostic_does_not_echo_configuration_input():
    marker = "synthetic-private-model-setting-marker"
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, OPENAI_MODEL=[marker])
    assert marker not in str(caught.value)
