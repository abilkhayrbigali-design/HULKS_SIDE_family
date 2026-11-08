"""SQLite lifetime cap. No transaction survives an await or an SDK call."""

import asyncio
import logging
from contextlib import contextmanager
from dataclasses import asdict
from decimal import Decimal

from sqlalchemy import insert, select, update

from app.diagnostics import log_internal_error
from app.evaluation.budget import (
    MAX_MICROUSD,
    BudgetQuote,
    conservative_settlement,
    make_quote,
    micros_to_usd,
    usd_to_micros,
    validate_quote,
)
from app.evaluation.errors import EvaluationError
from app.models.budget import BudgetAccount, BudgetReservation
from app.models.data import now, uuid

logger = logging.getLogger("cqa.budget")
ACCOUNT = BudgetAccount.__table__
RESERVATION = BudgetReservation.__table__


@contextmanager
def _write(engine):
    # SQLite serializes competing writers before they inspect the available cap.
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def _read(connection):
    account = connection.execute(select(ACCOUNT).where(ACCOUNT.c.id == "global")).mappings().one()
    amounts = [account[key] for key in ("limit_micros", "committed_micros", "reserved_micros")]
    if any(type(value) is not int or not 0 <= value <= MAX_MICROUSD for value in amounts):
        raise RuntimeError("Invalid budget account")
    rows = connection.execute(
        select(RESERVATION.c.state, RESERVATION.c.reserved_micros, RESERVATION.c.charged_micros)
    ).all()
    active = sum(row.reserved_micros for row in rows if row.state == "reserved")
    unknown = sum(row.reserved_micros for row in rows if row.state == "unknown")
    committed = sum(row.charged_micros for row in rows if row.state == "settled")
    # All arithmetic is Python integer arithmetic, never an overflowing SQL SUM/addition.
    if (
        active + unknown != account["reserved_micros"]
        or committed != account["committed_micros"]
        or committed + active + unknown > MAX_MICROUSD
    ):
        raise RuntimeError("Inconsistent budget account")
    return (
        account,
        active,
        unknown,
        sum(r.state == "reserved" for r in rows),
        sum(r.state == "unknown" for r in rows),
    )


class SqlBudgetGuard:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings
        # FIFO within this process: a new job cannot repeatedly overtake a waiting job.
        # Only reserve takes this lock. Settlement and status remain available.
        self._reserve_lock = asyncio.Lock()
        self._abandoned = set()

    def _quote(self):
        return make_quote(
            model=self.settings.openai_model,
            price_version=self.settings.llm_price_version,
            max_output_tokens=self.settings.llm_max_output_tokens,
            service_tier=self.settings.llm_service_tier,
        )

    def initialize(self):
        """Startup only: cap is absolute, abandoned holds are never refunded."""
        limit = usd_to_micros(self.settings.ai_budget_usd)
        with _write(self.engine) as connection:
            exists = connection.execute(select(ACCOUNT.c.id)).first()
            if exists is None:
                connection.execute(
                    insert(ACCOUNT).values(
                        id="global",
                        limit_micros=limit,
                        committed_micros=0,
                        reserved_micros=0,
                        accounting_started_at=now(),
                    )
                )
            _read(connection)
            connection.execute(update(ACCOUNT).values(limit_micros=limit))
            recovered = connection.execute(
                update(RESERVATION)
                .where(RESERVATION.c.state == "reserved")
                .values(state="unknown", settled_at=now())
            ).rowcount
        logger.info("event=ai_budget_initialized records=%d", recovered)

    @staticmethod
    def _unavailable(exc):
        log_internal_error("AI_BUDGET_UNAVAILABLE", exc)
        logger.error("event=ai_budget_failed error=AI_BUDGET_UNAVAILABLE")
        return EvaluationError("AI_BUDGET_UNAVAILABLE")

    def _mark_unknown(self, reservation_id):
        # A commit callback/receipt may fail after the durable reservation. Never leave
        # that abandoned hold advertised as an active request which can soon refund.
        self._abandoned.add(reservation_id)
        try:
            with _write(self.engine) as connection:
                connection.execute(
                    update(RESERVATION)
                    .where(RESERVATION.c.id == reservation_id, RESERVATION.c.state == "reserved")
                    .values(state="unknown", settled_at=now())
                )
            self._abandoned.discard(reservation_id)
        except Exception:
            # No second diagnostic; the original failure is handled at its boundary.
            # On restart initialize() again conservatively marks any surviving hold.
            pass

    def _reserve_once(self, context, attempt, quote, reservation_id):
        amount = usd_to_micros(quote.reserved_usd)
        with _write(self.engine) as connection:
            # Retry failed conservative cleanup before permitting any later request.
            abandoned = tuple(self._abandoned)
            if abandoned:
                connection.execute(
                    update(RESERVATION)
                    .where(RESERVATION.c.id.in_(abandoned), RESERVATION.c.state == "reserved")
                    .values(state="unknown", settled_at=now())
                )
            duplicate = connection.execute(
                select(RESERVATION.c.id).where(
                    RESERVATION.c.evaluation_id == context.evaluation_id,
                    RESERVATION.c.attempt == attempt,
                )
            ).first()
            if duplicate is not None:
                raise EvaluationError("AI_BUDGET_RESERVATION_CONFLICT")
            account, active, unknown, _, _ = _read(connection)
            limit, committed = account["limit_micros"], account["committed_micros"]
            if limit == 0:
                raise EvaluationError("AI_BUDGET_DISABLED")
            available = max(0, limit - committed - active - unknown)
            if amount > available:
                if active > 0 and amount <= limit - committed - unknown:
                    return False
                raise EvaluationError("AI_BUDGET_EXCEEDED")
            frozen = asdict(quote)
            frozen["reserved_usd"] = str(quote.reserved_usd)
            connection.execute(
                insert(RESERVATION).values(
                    id=reservation_id,
                    account_id="global",
                    evaluation_id=context.evaluation_id,
                    attempt=attempt,
                    quote=frozen,
                    reserved_micros=amount,
                    charged_micros=None,
                    state="reserved",
                    created_at=now(),
                    settled_at=None,
                )
            )
            connection.execute(
                update(ACCOUNT).values(reserved_micros=account["reserved_micros"] + amount)
            )
        return True

    async def reserve(self, *, context, attempt, quote):
        validate_quote(quote)
        # A foreign quote cannot authorize a policy different from this application's.
        if quote != self._quote() or type(attempt) is not int or attempt < 1:
            raise EvaluationError("AI_BUDGET_POLICY_UNSUPPORTED")
        reservation_id = uuid()
        waiting_logged = False
        async with self._reserve_lock:
            while True:
                try:
                    if self._reserve_once(context, attempt, quote, reservation_id):
                        logger.info("event=ai_budget_reserved records=1")
                        return reservation_id
                except EvaluationError as exc:
                    logger.warning("event=ai_budget_rejected error=%s", exc.code)
                    raise
                except Exception as exc:
                    self._mark_unknown(reservation_id)
                    raise self._unavailable(exc) from None
                if not waiting_logged:
                    logger.info("event=ai_budget_waiting error=AI_BUDGET_WAITING")
                    waiting_logged = True
                # Bounded polling also notices another process's settlement. Both
                # the connection and its transaction have already closed.
                await asyncio.sleep(0.05)

    async def settle(self, *, reservation_id, usage):
        try:
            with _write(self.engine) as connection:
                row = (
                    connection.execute(
                        select(RESERVATION).where(RESERVATION.c.id == reservation_id)
                    )
                    .mappings()
                    .one()
                )
                if row["state"] != "reserved":
                    return  # terminal settlement is idempotent; unknown never reopens
                account, _, _, _, _ = _read(connection)
                frozen = dict(row["quote"])
                frozen["reserved_usd"] = Decimal(frozen["reserved_usd"])
                quote = BudgetQuote(**frozen)
                charge = conservative_settlement(quote, usage)
                known = charge is not None
                values = {"state": "unknown", "settled_at": now()}
                if known:
                    charged = usd_to_micros(charge)
                    if charged > row["reserved_micros"]:
                        raise RuntimeError("Settlement exceeds reservation")
                    connection.execute(
                        update(ACCOUNT).values(
                            reserved_micros=account["reserved_micros"] - row["reserved_micros"],
                            committed_micros=account["committed_micros"] + charged,
                        )
                    )
                    values.update(state="settled", charged_micros=charged)
                connection.execute(
                    update(RESERVATION).where(RESERVATION.c.id == reservation_id).values(**values)
                )
            logger.log(
                logging.INFO if known else logging.WARNING,
                "event=ai_budget_settled status=%s records=1",
                "settled" if known else "unknown",
            )
        except Exception as exc:
            self._mark_unknown(reservation_id)
            raise self._unavailable(exc) from None

    def status(self):
        try:
            with self.engine.connect() as connection:
                # sqlite3 legacy transaction mode does not BEGIN on SELECT itself.
                # Account and reservation aggregates must come from one read snapshot.
                connection.exec_driver_sql("BEGIN")
                account, active, unknown, active_count, unknown_count = _read(connection)
            available = max(
                0,
                account["limit_micros"] - account["committed_micros"] - account["reserved_micros"],
            )
            quote, reason = None, None
            try:
                quote = self._quote()
            except EvaluationError:
                reason = "AI_BUDGET_POLICY_UNSUPPORTED"
            if account["limit_micros"] == 0:
                reason = "AI_BUDGET_DISABLED"
            elif quote is not None and available < usd_to_micros(quote.reserved_usd):
                can_wait = active > 0 and account["limit_micros"] - account[
                    "committed_micros"
                ] - unknown >= usd_to_micros(quote.reserved_usd)
                reason = "AI_BUDGET_WAITING" if can_wait else "AI_BUDGET_EXCEEDED"
            return {
                "currency": "USD",
                "limit_usd": str(micros_to_usd(account["limit_micros"])),
                "committed_upper_usd": str(micros_to_usd(account["committed_micros"])),
                "reserved_usd": str(micros_to_usd(account["reserved_micros"])),
                "available_usd": str(micros_to_usd(available)),
                "next_request_upper_usd": str(quote.reserved_usd) if quote else None,
                "active_reservations": active_count,
                "unknown_reservations": unknown_count,
                "model": self.settings.openai_model,
                "service_tier": self.settings.llm_service_tier,
                "pricing_version": quote.price_version if quote else None,
                "accounting_started_at": account["accounting_started_at"],
                "enabled": reason is None,
                "blocked_reason": reason,
            }
        except Exception as exc:
            raise self._unavailable(exc) from None
