"""Global lifetime upper-cost account; every SDK permission is single-use."""

from sqlalchemy import JSON, CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.data import Base


class BudgetAccount(Base):
    __tablename__ = "ai_budget_accounts"
    __table_args__ = (
        CheckConstraint("id = 'global'"),
        CheckConstraint("limit_micros BETWEEN 0 AND 9223372036854775807"),
        CheckConstraint("committed_micros BETWEEN 0 AND 9223372036854775807"),
        CheckConstraint("reserved_micros BETWEEN 0 AND 9223372036854775807"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    limit_micros: Mapped[int]
    committed_micros: Mapped[int]
    reserved_micros: Mapped[int]
    accounting_started_at: Mapped[str]


class BudgetReservation(Base):
    __tablename__ = "ai_budget_reservations"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "attempt"),
        CheckConstraint("attempt > 0"),
        CheckConstraint("state IN ('reserved', 'settled', 'unknown')"),
        CheckConstraint("reserved_micros BETWEEN 1 AND 9223372036854775807"),
        CheckConstraint(
            "(state = 'settled' AND charged_micros IS NOT NULL "
            "AND charged_micros BETWEEN 0 AND reserved_micros) "
            "OR (state != 'settled' AND charged_micros IS NULL)"
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("ai_budget_accounts.id"))
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id"))
    attempt: Mapped[int]
    quote: Mapped[dict] = mapped_column(JSON)
    reserved_micros: Mapped[int]
    charged_micros: Mapped[int | None]
    state: Mapped[str]
    created_at: Mapped[str]
    settled_at: Mapped[str | None]
