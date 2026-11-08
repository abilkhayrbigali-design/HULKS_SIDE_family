"""SQL-free D-027 policy; conservative accounting bounds, never a provider invoice.

Official model/pricing pages were verified on 2026-11-08. Standard Luna accepts
1,050,000 context tokens and 128,000 output tokens. Reservations cover the full
input ceiling at the long-context 12h cache-write rate plus the output ceiling,
including the 10% regional premium. No heuristic tokenizer estimate is required.
https://developers.openai.com/api/docs/models/gpt-6-luna
https://developers.openai.com/api/docs/pricing
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Protocol

from pydantic import ValidationError

from app.evaluation.errors import EvaluationError
from app.evaluation.schemas import Usage

MODEL = "gpt-6-luna"
PRICE_VERSION = "gpt-6-luna-standard-2026-11-08-v1"
INPUT_CEILING = 1_050_000
OUTPUT_CEILING = 128_000
LONG_CONTEXT_THRESHOLD = 272_000
MAX_MICROUSD = 2**63 - 1
MICRO = Decimal("0.000001")
MILLION = Decimal(1_000_000)
REGION_MULTIPLIER = Decimal("1.10")


@dataclass(frozen=True)
class EvaluationContext:
    evaluation_id: str


_context: ContextVar[EvaluationContext | None] = ContextVar("cqa_budget_evaluation", default=None)


@contextmanager
def evaluation_scope(evaluation_id: str) -> Iterator[EvaluationContext]:
    """Worker-scoped identity; no new arguments on injected pipeline.evaluate."""
    context = EvaluationContext(evaluation_id)
    token = _context.set(context)
    try:
        yield context
    finally:
        _context.reset(token)


def current_context() -> EvaluationContext | None:
    return _context.get()


def usd_to_micros(value: Decimal) -> int:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value < 0
        or value > Decimal(MAX_MICROUSD) / MILLION
    ):
        raise EvaluationError("AI_BUDGET_POLICY_UNSUPPORTED")
    amount = value.quantize(MICRO, rounding=ROUND_CEILING) * MILLION
    if amount > MAX_MICROUSD:
        raise EvaluationError("AI_BUDGET_POLICY_UNSUPPORTED")
    return int(amount)


def micros_to_usd(value: int) -> Decimal:
    if type(value) is not int or not 0 <= value <= MAX_MICROUSD:
        raise EvaluationError("AI_BUDGET_POLICY_UNSUPPORTED")
    return (Decimal(value) / MILLION).quantize(MICRO)


def _reserved(max_output_tokens: int) -> Decimal:
    return micros_to_usd(
        usd_to_micros(
            (
                Decimal(INPUT_CEILING) * Decimal("0.50")
                + Decimal(max_output_tokens) * Decimal("0.75")
            )
            * REGION_MULTIPLIER
            / MILLION
        )
    )


@dataclass(frozen=True)
class BudgetQuote:
    model: str
    price_version: str
    input_tokens_upper: int
    max_output_tokens: int
    reserved_usd: Decimal


def validate_quote(quote: BudgetQuote) -> None:
    """Ledger must validate even manually constructed or reconstructed quotes."""
    if (
        not isinstance(quote, BudgetQuote)
        or quote.model != MODEL
        or quote.price_version != PRICE_VERSION
        or type(quote.input_tokens_upper) is not int
        or quote.input_tokens_upper != INPUT_CEILING
        or type(quote.max_output_tokens) is not int
        or not 0 < quote.max_output_tokens <= OUTPUT_CEILING
        or not isinstance(quote.reserved_usd, Decimal)
        or not quote.reserved_usd.is_finite()
        or quote.reserved_usd != _reserved(quote.max_output_tokens)
    ):
        raise EvaluationError("AI_BUDGET_POLICY_UNSUPPORTED")


def make_quote(
    *, model: str, price_version: str, max_output_tokens: int, service_tier: str = "default"
) -> BudgetQuote:
    if (
        model != MODEL
        or price_version != PRICE_VERSION
        or service_tier != "default"
        or type(max_output_tokens) is not int
        or not 0 < max_output_tokens <= OUTPUT_CEILING
    ):
        raise EvaluationError("AI_BUDGET_POLICY_UNSUPPORTED")
    quote = BudgetQuote(
        model, price_version, INPUT_CEILING, max_output_tokens, _reserved(max_output_tokens)
    )
    validate_quote(quote)
    return quote


def conservative_settlement(quote: BudgetQuote, usage: Usage | dict | None) -> Decimal | None:
    """Known validated attempt upper charge, or None: retain the complete reservation.

    All inputs are charged at the worst cache-write rate; no cache discount is
    presumed. Cached/reasoning counts are subsets, never additional tokens.
    """
    try:
        validate_quote(quote)
        usage = Usage.model_validate(usage)
    except (EvaluationError, ValidationError):
        return None
    fields = (
        usage.input_tokens,
        usage.output_tokens,
        usage.total_tokens,
        usage.cached_input_tokens,
        usage.reasoning_output_tokens,
    )
    if (
        usage.request_count != 1
        or any(value is None for value in fields)
        or not 0 < usage.input_tokens <= quote.input_tokens_upper
        or usage.output_tokens > quote.max_output_tokens
        or usage.total_tokens != usage.input_tokens + usage.output_tokens
        or usage.cached_input_tokens > usage.input_tokens
        or usage.reasoning_output_tokens > usage.output_tokens
    ):
        return None
    long_context = usage.input_tokens > LONG_CONTEXT_THRESHOLD
    charge = (
        (
            Decimal(usage.input_tokens) * Decimal("0.50" if long_context else "0.25")
            + Decimal(usage.output_tokens) * Decimal("0.75" if long_context else "0.50")
        )
        * REGION_MULTIPLIER
        / MILLION
    )
    charge = micros_to_usd(usd_to_micros(charge))
    return charge if charge <= quote.reserved_usd else None


class BudgetGuard(Protocol):
    async def reserve(self, *, context: EvaluationContext, attempt: int, quote: BudgetQuote) -> str:
        """Persist before return; wait for transient contention without an open transaction."""
        ...

    async def settle(self, *, reservation_id: str, usage: Usage | None) -> None:
        """Idempotent known settlement; None/unknown never releases a reservation."""
        ...
