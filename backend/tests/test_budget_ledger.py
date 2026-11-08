"""Synthetic SQLite tests of durable permission, money conservation and fairness."""

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import httpx
import pytest
from openai import AsyncOpenAI
from sqlalchemy import event, select, text
from sqlalchemy.exc import OperationalError
from test_batches_api import batch_payload, wait_batch
from test_evaluations_api import SyntheticPipeline, inputs, wait_for
from test_evaluations_api import setup as evaluation_setup
from test_submissions_api import export

from app.config import Settings
from app.evaluation.budget import (
    MAX_MICROUSD,
    PRICE_VERSION,
    EvaluationContext,
    current_context,
    make_quote,
)
from app.evaluation.errors import EvaluationError
from app.evaluation.pipeline import EvaluationPipeline
from app.evaluation.provider import OpenAIProvider
from app.models.budget import BudgetAccount, BudgetReservation
from app.schemas.budget import AIBudget
from app.services.budget import SqlBudgetGuard
from app.services.worker import start_evaluation_worker, stop_evaluation_worker

setup = evaluation_setup
USAGE = dict(
    request_count=1,
    input_tokens=100,
    output_tokens=20,
    total_tokens=120,
    cached_input_tokens=0,
    reasoning_output_tokens=0,
)


def configured(cap="1", **patch):
    return Settings(
        _env_file=None,
        **{
            "OPENAI_API_KEY": "",
            "CQA_AI_BUDGET_USD": cap,
            "CQA_LLM_PRICE_VERSION": PRICE_VERSION,
            **patch,
        },
    )


def guard_for(setup, cap="1", **patch):
    _, factory, _, _ = setup
    guard = SqlBudgetGuard(factory.kw["bind"], configured(cap, **patch))
    guard.initialize()
    return guard


def contexts(setup, count=3):
    client, _, app, _ = setup
    client.portal.call(stop_evaluation_worker, app)
    payload = inputs(client)
    return [
        EvaluationContext(client.post("/api/v1/evaluations", json=payload).json()["id"])
        for _ in range(count)
    ]


def quote(guard):
    settings = guard.settings
    return make_quote(
        model=settings.openai_model,
        price_version=settings.llm_price_version,
        max_output_tokens=settings.llm_max_output_tokens,
    )


def test_zero_policy_and_get_never_create_permission(setup, caplog):
    client, factory, app, _ = setup
    context = contexts(setup, 1)[0]
    guard = guard_for(setup, "0")
    app.state.budget_guard = guard
    caplog.set_level(logging.INFO, logger="cqa")
    with factory() as db:
        before = db.get(BudgetAccount, "global").accounting_started_at
    for _ in range(2):
        response = client.get("/api/v1/ai-budget")
        assert response.status_code == 200
        status = AIBudget.model_validate(response.json())
        assert status.limit_usd == status.available_usd == "0.000000"
        assert status.next_request_upper_usd == "0.587400"
        assert status.blocked_reason == "AI_BUDGET_DISABLED"
        assert not status.enabled
    with pytest.raises(EvaluationError, match="budget") as exc:
        asyncio.run(guard.reserve(context=context, attempt=1, quote=quote(guard)))
    assert exc.value.code == "AI_BUDGET_DISABLED"
    with factory() as db:
        assert db.scalar(select(text("count(*)")).select_from(BudgetReservation)) == 0
        assert db.get(BudgetAccount, "global").accounting_started_at == before
    assert "event=ai_budget_rejected error=AI_BUDGET_DISABLED" in caplog.text


def test_wait_closes_transaction_is_fifo_and_known_usage_releases(setup):
    first, second, third = contexts(setup)
    guard = guard_for(setup)

    async def scenario():
        original = await guard.reserve(context=first, attempt=1, quote=quote(guard))
        order = []

        async def request(context):
            reservation = await guard.reserve(context=context, attempt=1, quote=quote(guard))
            order.append(context)
            await asyncio.sleep(0.01)
            await guard.settle(reservation_id=reservation, usage=USAGE)

        waiter = asyncio.create_task(request(second))
        await asyncio.sleep(0.07)
        newcomer = asyncio.create_task(request(third))
        await asyncio.sleep(0.01)
        assert not waiter.done() and not newcomer.done()
        status = guard.status()
        assert status["blocked_reason"] == "AI_BUDGET_WAITING"
        assert status["active_reservations"] == 1
        # A separate writer can acquire SQLite while reserve awaits settlement.
        with guard.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            connection.rollback()
        await guard.settle(reservation_id=original, usage=USAGE)
        await asyncio.wait_for(asyncio.gather(waiter, newcomer), 2)
        assert order == [second, third]

    asyncio.run(scenario())
    status = guard.status()
    assert status["committed_upper_usd"] == "0.000117"
    assert status["reserved_usd"] == "0.000000"
    assert status["enabled"]


@pytest.mark.parametrize(
    "usage", [None, {**USAGE, "output_tokens": None}, {**USAGE, "total_tokens": 1}]
)
def test_unknown_holds_are_terminal_and_never_assumed_refundable(setup, usage):
    first, second = contexts(setup, 2)
    guard = guard_for(setup)

    async def scenario():
        reservation = await guard.reserve(context=first, attempt=1, quote=quote(guard))
        await guard.settle(reservation_id=reservation, usage=usage)
        await guard.settle(reservation_id=reservation, usage=USAGE)
        with pytest.raises(EvaluationError) as exc:
            await asyncio.wait_for(
                guard.reserve(context=second, attempt=1, quote=quote(guard)), 0.5
            )
        assert exc.value.code == "AI_BUDGET_EXCEEDED"

    asyncio.run(scenario())
    status = guard.status()
    assert status["reserved_usd"] == "0.587400"
    assert status["committed_upper_usd"] == "0.000000"
    assert status["unknown_reservations"] == 1
    assert status["active_reservations"] == 0


def test_restart_cap_change_and_duplicate_permissions_never_reset(setup):
    first, second = contexts(setup, 2)
    guard = guard_for(setup)

    async def initial():
        r = await guard.reserve(context=first, attempt=1, quote=quote(guard))
        await guard.settle(reservation_id=r, usage=USAGE)
        await guard.reserve(context=second, attempt=1, quote=quote(guard))

    asyncio.run(initial())
    started = guard.status()["accounting_started_at"]
    reduced = guard_for(setup, "0.1")
    assert reduced.status()["available_usd"] == "0.000000"
    raised = guard_for(setup, "2")
    status = raised.status()
    assert status["limit_usd"] == "2.000000"
    assert status["committed_upper_usd"] == "0.000039"
    assert status["reserved_usd"] == "0.587400"
    assert status["accounting_started_at"] == started
    assert status["unknown_reservations"] == 1
    for context in (first, second):
        with pytest.raises(EvaluationError) as exc:
            asyncio.run(raised.reserve(context=context, attempt=1, quote=quote(raised)))
        assert exc.value.code == "AI_BUDGET_RESERVATION_CONFLICT"


def test_cancelled_waiter_creates_no_attempt_and_does_not_block_next(setup):
    first, second, third = contexts(setup)
    guard = guard_for(setup)

    async def scenario():
        r = await guard.reserve(context=first, attempt=1, quote=quote(guard))
        task = asyncio.create_task(guard.reserve(context=second, attempt=1, quote=quote(guard)))
        await asyncio.sleep(0.07)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await guard.settle(reservation_id=r, usage=USAGE)
        r = await asyncio.wait_for(guard.reserve(context=third, attempt=1, quote=quote(guard)), 1)
        await guard.settle(reservation_id=r, usage=USAGE)

    asyncio.run(scenario())
    with setup[1]() as db:
        assert (
            db.scalar(
                select(BudgetReservation.id).where(
                    BudgetReservation.evaluation_id == second.evaluation_id
                )
            )
            is None
        )


def test_durable_commit_then_callback_error_becomes_unknown(setup, monkeypatch, caplog):
    first, second = contexts(setup, 2)
    guard = guard_for(setup)
    original = guard._reserve_once

    def fail_after_commit(*args):
        assert original(*args)
        raise RuntimeError("PRIVATE_BUDGET_CALLBACK")

    monkeypatch.setattr(guard, "_reserve_once", fail_after_commit)
    with pytest.raises(EvaluationError) as exc:
        asyncio.run(guard.reserve(context=first, attempt=1, quote=quote(guard)))
    assert exc.value.code == "AI_BUDGET_UNAVAILABLE"
    assert guard.status()["unknown_reservations"] == 1
    monkeypatch.setattr(guard, "_reserve_once", original)
    with pytest.raises(EvaluationError) as exc:
        asyncio.run(guard.reserve(context=second, attempt=1, quote=quote(guard)))
    assert exc.value.code == "AI_BUDGET_EXCEEDED"
    assert "PRIVATE_BUDGET_CALLBACK" not in caplog.text
    assert "AI_BUDGET_UNAVAILABLE" in caplog.text


def test_reservation_insert_and_balance_rollback_together(setup, caplog):
    context = contexts(setup, 1)[0]
    guard = guard_for(setup)

    def fail_balance(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE ai_budget_accounts SET reserved_micros"):
            raise OperationalError("PRIVATE_BUDGET_SQL", {}, RuntimeError("PRIVATE_BUDGET_SQL"))

    event.listen(guard.engine, "before_cursor_execute", fail_balance)
    try:
        with pytest.raises(EvaluationError) as exc:
            asyncio.run(guard.reserve(context=context, attempt=1, quote=quote(guard)))
        assert exc.value.code == "AI_BUDGET_UNAVAILABLE"
    finally:
        event.remove(guard.engine, "before_cursor_execute", fail_balance)
    status = guard.status()
    assert status["active_reservations"] == status["unknown_reservations"] == 0
    assert status["reserved_usd"] == "0.000000"
    assert "PRIVATE_BUDGET_SQL" not in caplog.text


def test_independent_guards_serialize_reserve_against_same_sqlite(setup):
    first, second = contexts(setup, 2)
    guard = guard_for(setup, "0.587400")
    another = SqlBudgetGuard(guard.engine, guard.settings)
    barrier = threading.Barrier(2)

    def request(instance, context):
        async def run():
            barrier.wait(2)
            try:
                reservation = await instance.reserve(
                    context=context, attempt=1, quote=quote(instance)
                )
            except EvaluationError as exc:
                return exc.code
            await asyncio.sleep(0.05)
            await instance.settle(reservation_id=reservation, usage=None)
            return "permission"

        return asyncio.run(run())

    with ThreadPoolExecutor(2) as executor:
        futures = [
            executor.submit(request, instance, context)
            for instance, context in ((guard, first), (another, second))
        ]
        outcomes = sorted(future.result(timeout=3) for future in futures)
    assert outcomes == ["AI_BUDGET_EXCEEDED", "permission"]
    assert guard.status()["reserved_usd"] == "0.587400"
    assert guard.status()["unknown_reservations"] == 1


def test_settlement_rollback_keeps_full_unknown_hold(setup, caplog):
    context = contexts(setup, 1)[0]
    guard = guard_for(setup)
    reservation = asyncio.run(guard.reserve(context=context, attempt=1, quote=quote(guard)))

    def fail_balance(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE ai_budget_accounts SET committed_micros"):
            raise OperationalError("PRIVATE_SETTLE_SQL", {}, RuntimeError("PRIVATE_SETTLE_SQL"))

    event.listen(guard.engine, "before_cursor_execute", fail_balance)
    try:
        with pytest.raises(EvaluationError) as exc:
            asyncio.run(guard.settle(reservation_id=reservation, usage=USAGE))
        assert exc.value.code == "AI_BUDGET_UNAVAILABLE"
    finally:
        event.remove(guard.engine, "before_cursor_execute", fail_balance)
    status = guard.status()
    assert status["committed_upper_usd"] == "0.000000"
    assert status["reserved_usd"] == "0.587400"
    assert status["unknown_reservations"] == 1
    assert "PRIVATE_SETTLE_SQL" not in caplog.text


def test_int64_cap_uses_exact_python_arithmetic_and_forged_quote_is_rejected(setup):
    context = contexts(setup, 1)[0]
    guard = guard_for(setup, "9223372036854.775807")
    reservation = asyncio.run(guard.reserve(context=context, attempt=1, quote=quote(guard)))
    assert guard.status()["available_usd"] == "9223372036854.188407"
    asyncio.run(guard.settle(reservation_id=reservation, usage=USAGE))
    assert guard.status()["available_usd"] == "9223372036854.775768"
    from dataclasses import replace

    with pytest.raises(EvaluationError) as exc:
        asyncio.run(
            guard.reserve(
                context=context, attempt=2, quote=replace(quote(guard), reserved_usd=Decimal("0"))
            )
        )
    assert exc.value.code == "AI_BUDGET_POLICY_UNSUPPORTED"
    assert MAX_MICROUSD == 9223372036854775807


def test_budget_read_failure_is_safe503_and_does_not_initialize(setup, caplog, monkeypatch):
    client, _, app, _ = setup
    guard = app.state.budget_guard

    def fail():
        raise OperationalError("PRIVATE_BUDGET_READ", {}, RuntimeError("PRIVATE_BUDGET_READ"))

    monkeypatch.setattr(guard.engine, "connect", fail)
    response = client.get("/api/v1/ai-budget")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_BUDGET_UNAVAILABLE"
    assert "PRIVATE_BUDGET_READ" not in response.text + caplog.text


def test_worker_multiple_jobs_wait_and_all_finish_under_one_global_cap(setup):
    client, factory, app, _ = setup
    client.portal.call(stop_evaluation_worker, app)
    app.state.settings = configured()
    guard = guard_for(setup)

    class GuardedSyntheticPipeline(SyntheticPipeline):
        async def evaluate(self, *, transcript, checklist):
            context = current_context()
            assert context is not None
            reservation = await guard.reserve(context=context, attempt=1, quote=quote(guard))
            await asyncio.sleep(0.08)
            await guard.settle(reservation_id=reservation, usage=USAGE)
            return await super().evaluate(transcript=transcript, checklist=checklist)

    pipeline = GuardedSyntheticPipeline()
    app.state.evaluation_pipeline = pipeline
    client.portal.call(start_evaluation_worker, app)
    batch = client.post("/api/v1/evaluation-batches", json=batch_payload(client, 6)).json()
    finished = wait_batch(client, batch["id"])
    assert finished["completed"] == 6
    assert finished["failed"] == 0
    assert len(pipeline.calls) == 6
    assert guard.status()["committed_upper_usd"] == "0.000234"
    assert guard.status()["reserved_usd"] == "0.000000"
    with factory() as db:
        assert len(db.scalars(select(BudgetReservation)).all()) == 6


@pytest.mark.parametrize(
    ("cap", "price_version", "code"),
    [("0", PRICE_VERSION, "AI_BUDGET_DISABLED"), ("1", "", "AI_BUDGET_POLICY_UNSUPPORTED")],
)
def test_actual_provider_refusal_has_no_sdk_attempt_and_exports_not_run(
    setup, cap, price_version, code
):
    client, factory, app, _ = setup
    client.portal.call(stop_evaluation_worker, app)
    settings = configured(
        cap, OPENAI_API_KEY="synthetic-test-only", CQA_LLM_PRICE_VERSION=price_version
    )
    app.state.settings = settings
    client.portal.call(start_evaluation_worker, app)
    calls = []

    def forbidden(request):
        calls.append(1)
        raise AssertionError("Synthetic transport must not be reached")

    sdk = AsyncOpenAI(
        api_key="synthetic-test-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(forbidden)),
    )
    provider = OpenAIProvider(settings, client=sdk, budget_guard=app.state.budget_guard)
    app.state.evaluation_worker.pipeline = EvaluationPipeline(settings, provider=provider)
    try:
        batch = client.post("/api/v1/evaluation-batches", json=batch_payload(client, 1)).json()
        done = wait_batch(client, batch["id"])
        assert done["failed"] == 1
        row = client.get(f"/api/v1/evaluations/{done['items'][0]['evaluation_id']}").json()
        assert row["error"]["code"] == code
        assert row["provenance"]["usage"]["request_count"] == 0
        document = export(client, batch["id"]).json()
        assert document["model"]["name"] == "not_run"
        assert document["results"][0]["error"] == code
        assert not calls
        with factory() as db:
            assert db.scalars(select(BudgetReservation)).all() == []
    finally:
        client.portal.call(stop_evaluation_worker, app)
        client.portal.call(sdk.close)


def test_cancelled_mock_sdk_keeps_unknown_full_hold_and_actual_attempt(setup):
    client, _, app, _ = setup
    client.portal.call(stop_evaluation_worker, app)
    settings = configured(OPENAI_API_KEY="synthetic-test-only")
    app.state.settings = settings
    client.portal.call(start_evaluation_worker, app)
    reached = threading.Event()

    async def pending(request):
        reached.set()
        await asyncio.sleep(30)

    sdk = AsyncOpenAI(
        api_key="synthetic-test-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(pending)),
    )
    provider = OpenAIProvider(settings, client=sdk, budget_guard=app.state.budget_guard)
    app.state.evaluation_worker.pipeline = EvaluationPipeline(settings, provider=provider)
    try:
        created = client.post("/api/v1/evaluations", json=inputs(client)).json()
        assert reached.wait(5)
        client.portal.call(stop_evaluation_worker, app)
        failed = wait_for(client, created["id"], "failed")
        assert failed["error"]["code"] == "INTERRUPTED"
        assert failed["provenance"]["usage"]["request_count"] == 1
        assert failed["provenance"]["usage"]["total_tokens"] is None
        status = app.state.budget_guard.status()
        assert status["unknown_reservations"] == 1
        assert status["active_reservations"] == 0
        assert status["reserved_usd"] == "0.587400"
    finally:
        client.portal.call(sdk.close)


def test_single_batch_and_retry_share_lifetime_cost_and_reuse_successes(setup):
    client, factory, app, _ = setup
    client.portal.call(stop_evaluation_worker, app)
    app.state.settings = configured()
    guard = guard_for(setup)

    class MixedSyntheticPipeline(SyntheticPipeline):
        fail_next = True

        async def evaluate(self, *, transcript, checklist):
            reservation = await guard.reserve(
                context=current_context(), attempt=1, quote=quote(guard)
            )
            await asyncio.sleep(0.02)
            await guard.settle(reservation_id=reservation, usage=USAGE)
            if self.fail_next:
                self.fail_next = False
                raise EvaluationError("AI_REFUSED")
            return await super().evaluate(transcript=transcript, checklist=checklist)

    pipeline = MixedSyntheticPipeline()
    app.state.evaluation_pipeline = pipeline
    client.portal.call(start_evaluation_worker, app)
    batch = client.post("/api/v1/evaluation-batches", json=batch_payload(client, 2)).json()
    source = wait_batch(client, batch["id"])
    assert source["failed"] == source["completed"] == 1
    retry = client.post(f"/api/v1/evaluation-batches/{source['id']}/retry-failed").json()
    child = wait_batch(client, retry["id"])
    assert child["completed"] == child["total"] == 2
    source_ids = {item["evaluation_id"] for item in source["items"]}
    child_ids = {item["evaluation_id"] for item in child["items"]}
    assert len(source_ids & child_ids) == 1
    single = client.post("/api/v1/evaluations", json=inputs(client)).json()
    wait_for(client, single["id"])
    assert guard.status()["committed_upper_usd"] == "0.000156"
    with factory() as db:
        assert len(db.scalars(select(BudgetReservation)).all()) == 4
