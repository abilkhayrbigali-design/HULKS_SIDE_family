"""Read-only upper-estimate status; money is never a JSON floating point number."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt

from app.schemas.data import Schema, Text

Money = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,12})\.[0-9]{6}$")]
BudgetCode = Literal[
    "AI_BUDGET_DISABLED",
    "AI_BUDGET_EXCEEDED",
    "AI_BUDGET_POLICY_UNSUPPORTED",
    "AI_BUDGET_UNAVAILABLE",
    "AI_BUDGET_RESERVATION_CONFLICT",
    "AI_BUDGET_WAITING",
]


class AIBudget(Schema):
    currency: Literal["USD"]
    limit_usd: Money
    committed_upper_usd: Money
    reserved_usd: Money
    available_usd: Money
    next_request_upper_usd: Money | None
    active_reservations: Annotated[StrictInt, Field(ge=0)]
    unknown_reservations: Annotated[StrictInt, Field(ge=0)]
    model: Text
    service_tier: Literal["default"]
    pricing_version: Text | None
    accounting_started_at: datetime
    enabled: StrictBool
    blocked_reason: BudgetCode | None
