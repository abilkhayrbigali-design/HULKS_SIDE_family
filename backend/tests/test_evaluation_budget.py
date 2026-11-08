"""Offline pricing bounds and protocol invariants; no invoices or model accuracy claims."""

import asyncio
from dataclasses import replace
from decimal import Decimal

import pytest

from app.evaluation.budget import (
    INPUT_CEILING,
    MAX_MICROUSD,
    MODEL,
    PRICE_VERSION,
    conservative_settlement,
    current_context,
    evaluation_scope,
    make_quote,
    micros_to_usd,
    usd_to_micros,
    validate_quote,
)
from app.evaluation.errors import EvaluationError


def quote(**changes):
    return make_quote(
        **dict(model=MODEL, price_version=PRICE_VERSION, max_output_tokens=12000) | changes
    )


def usage(**changes):
    return (
        dict(
            request_count=1,
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            cached_input_tokens=30,
            reasoning_output_tokens=5,
        )
        | changes
    )


def test_full_context_long_cache_write_region_reservation_and_output_boundary():
    reserved = quote()
    assert reserved.input_tokens_upper == INPUT_CEILING
    assert reserved.reserved_usd == Decimal("0.587400")
    assert quote(max_output_tokens=128000).reserved_usd == Decimal("0.683100")
    validate_quote(reserved)


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "another-model"},
        {"price_version": ""},
        {"price_version": "unknown"},
        {"max_output_tokens": True},
        {"max_output_tokens": 0},
        {"max_output_tokens": 128001},
        {"service_tier": "auto"},
        {"service_tier": "fast"},
    ],
)
def test_unsupported_policy_fails_closed(changes):
    with pytest.raises(EvaluationError, match="pricing policy"):
        quote(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"reserved_usd": Decimal(0)},
        {"reserved_usd": Decimal("-1")},
        {"reserved_usd": Decimal("NaN")},
        {"reserved_usd": Decimal("0.000001")},
        {"input_tokens_upper": 100},
        {"input_tokens_upper": True},
        {"max_output_tokens": 1},
        {"model": "different"},
        {"price_version": "different"},
    ],
)
def test_ledger_must_revalidate_manually_constructed_quotes(changes):
    invalid = replace(quote(), **changes)
    with pytest.raises(EvaluationError):
        validate_quote(invalid)
    assert conservative_settlement(invalid, usage()) is None


def test_settlement_is_an_upper_bound_without_double_counting_token_subsets():
    assert conservative_settlement(quote(), usage()) == Decimal("0.000039")
    assert conservative_settlement(
        quote(), usage(cached_input_tokens=0, reasoning_output_tokens=0)
    ) == Decimal("0.000039")
    assert conservative_settlement(
        quote(), usage(input_tokens=272000, output_tokens=12000, total_tokens=284000)
    ) == Decimal("0.081400")
    assert conservative_settlement(
        quote(), usage(input_tokens=272001, output_tokens=12000, total_tokens=284001)
    ) == Decimal("0.159501")
    assert (
        conservative_settlement(
            quote(), usage(input_tokens=INPUT_CEILING, output_tokens=12000, total_tokens=1062000)
        )
        == quote().reserved_usd
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"request_count": 0},
        {"request_count": 2},
        {"input_tokens": None},
        {"input_tokens": True},
        {"input_tokens": -1},
        {"input_tokens": 0},
        {"output_tokens": None},
        {"total_tokens": None},
        {"cached_input_tokens": None},
        {"reasoning_output_tokens": None},
        {"input_tokens": INPUT_CEILING + 1, "total_tokens": INPUT_CEILING + 21},
        {"output_tokens": 12001, "total_tokens": 12101},
        {"total_tokens": 121},
        {"cached_input_tokens": 101},
        {"reasoning_output_tokens": 21},
    ],
)
def test_partial_unknown_or_inconsistent_usage_never_releases_reservation(changes):
    assert conservative_settlement(quote(), usage(**changes)) is None


def test_no_usage_retains_full_reservation():
    assert conservative_settlement(quote(), None) is None


def test_money_ceil_and_int64_limits():
    assert usd_to_micros(Decimal("0.0000001")) == 1
    assert usd_to_micros(Decimal("1e-999999999")) == 1
    assert usd_to_micros(Decimal("9223372036854.775807")) == MAX_MICROUSD
    assert micros_to_usd(MAX_MICROUSD) == Decimal("9223372036854.775807")
    for value in [Decimal("NaN"), Decimal("Infinity"), Decimal("-0.1"), Decimal("1e999999")]:
        with pytest.raises(EvaluationError):
            usd_to_micros(value)
    for value in [True, -1, MAX_MICROUSD + 1]:
        with pytest.raises(EvaluationError):
            micros_to_usd(value)


def test_context_is_isolated_between_tasks_and_restored_on_exception():
    async def run():
        ready = asyncio.Event()

        async def child(id_):
            with evaluation_scope(id_):
                await ready.wait()
                assert current_context().evaluation_id == id_
            assert current_context() is None

        tasks = [asyncio.create_task(child(str(index))) for index in range(2)]
        ready.set()
        await asyncio.gather(*tasks)
        with evaluation_scope("outer"):
            with pytest.raises(RuntimeError), evaluation_scope("inner"):
                raise RuntimeError("synthetic")
            assert current_context().evaluation_id == "outer"
        assert current_context() is None

    asyncio.run(run())
