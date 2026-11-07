"""Real SQLite/HTTP/worker tests; injected AI is explicitly synthetic test code."""

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.api.evaluations import install_evaluation_api
from app.api.install import install_data_api
from app.config import Settings
from app.db.migrate import migrate
from app.db.session import make_engine, session_factory
from app.models.evaluations import Evaluation
from app.schemas.evaluations import EvaluationCreate
from app.services import evaluations
from app.services.seed import seed
from app.services.worker import start_evaluation_worker, stop_evaluation_worker


class SyntheticPipeline:
    """Deterministic injected dependency, never selectable in the product."""

    def __init__(self):
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.failure = None
        self.delay = 0
        self.on_evaluate = None

    async def evaluate(self, *, transcript, checklist):
        from app.evaluation.scoring import calculate_assessment

        self.calls.append((deepcopy(transcript), deepcopy(checklist)))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.on_evaluate is not None:
                self.on_evaluate()
            await asyncio.sleep(self.delay)
            if self.failure is not None:
                raise self.failure
            results = [
                dict(
                    criterion_id=c["id"],
                    applicability="applicable",
                    answer=(
                        max(s["value"] for s in c["scale"])
                        if c["type"] == "scale"
                        else c["type"] == "binary"
                    ),
                    explanation="Synthetic test assessment",
                    evidence=[
                        {
                            "kind": "message",
                            "message_id": transcript["messages"][-1]["id"],
                        }
                    ],
                    review_reasons=[],
                )
                for c in checklist["criteria"]
            ]
            results[0]["answer"] = False
            return SimpleNamespace(
                assessment=calculate_assessment(
                    criteria=checklist["criteria"], results=results, messages=transcript["messages"]
                ),
                provenance={
                    "provider": "synthetic-test-only",
                    "model_requested": "synthetic-test-only",
                    "model_reported": None,
                    "prompt_version": "synthetic-v1",
                    "duration_ms": 1,
                    "usage": {
                        "request_count": 0,
                        "input_tokens": None,
                        "output_tokens": None,
                        "total_tokens": None,
                        "cached_input_tokens": None,
                        "reasoning_output_tokens": None,
                    },
                    "estimated_cost_usd": None,
                },
                review_required=False,
                review_reasons=[],
            )
        finally:
            self.active -= 1


@pytest.fixture
def setup(tmp_path):
    url = f"sqlite:///{tmp_path}/evaluations.sqlite3"
    migrate(url)
    engine = make_engine(url)
    factory = session_factory(engine)
    with factory.begin() as db:
        seed(db)
    pipeline = SyntheticPipeline()

    @asynccontextmanager
    async def lifespan(app):
        await start_evaluation_worker(app)
        yield
        await stop_evaluation_worker(app)
        await stop_evaluation_worker(app)

    app = FastAPI(lifespan=lifespan)
    app.state.settings = Settings(_env_file=None, CQA_DATABASE_URL=url)
    app.state.evaluation_pipeline = pipeline
    install_data_api(app, factory)
    install_evaluation_api(app)
    with TestClient(app) as client:
        yield client, factory, app, pipeline
    engine.dispose()


def inputs(client):
    conversation = client.post(
        "/api/v1/conversations/import",
        json={
            "records": [
                {
                    "conversation_id": "synthetic-evaluation",
                    "language": "RU",
                    "channel": "agent chat",
                    "audio_url": None,
                    "transcript": [
                        {
                            "timestamp": "00:01",
                            "speaker": "client",
                            "text": "Как получить справку?",
                        },
                        {
                            "timestamp": "00:02",
                            "speaker": "operator",
                            "text": "Здравствуйте, я Алия.",
                        },
                    ],
                }
            ]
        },
    ).json()["conversation_ids"][0]
    checklist = client.get("/api/v1/checklists").json()["items"][0]
    return {"conversation_id": conversation, "checklist_version_id": checklist["latest_version_id"]}


def wait_for(client, id_, status="completed"):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/evaluations/{id_}")
        assert response.status_code == 200
        value = response.json()
        if value["status"] == status:
            return value
        if value["status"] == "failed" and status != "failed":
            pytest.fail(f"Unexpected safe error code: {value['error']['code']}")
        time.sleep(0.02)
    pytest.fail("Evaluation did not reach expected state")


def completed(client):
    response = client.post("/api/v1/evaluations", json=inputs(client))
    assert response.status_code == 202
    return wait_for(client, response.json()["id"])


def appeal(client, evaluation_id, criterion="contact"):
    return client.post(
        f"/api/v1/evaluations/{evaluation_id}/appeals",
        json={
            "criterion_id": criterion,
            "comment": "Проверьте ответ оператора",
        },
    )


def override(client, appeal_id, revision=0, **patch):
    payload = {
        "action": "override",
        "reason": "Оператор представился и поздоровался",
        "expected_revision": revision,
        "applicability": "applicable",
        "answer": True,
        "evidence": [{"kind": "message", "message_id": "m0002"}],
    }
    payload.update(patch)
    return client.post(f"/api/v1/appeals/{appeal_id}/decisions", json=payload)


def test_worker_completed_and_history_after_override(setup):
    client, _, _, pipeline = setup
    result = completed(client)
    assert result["original"]["total"] == result["final"]["total"] == 90
    assert result["revision"] == 0
    assert len(pipeline.calls) == 1
    transcript, checklist = pipeline.calls[0]
    assert transcript["id"] == result["transcript_version_id"]
    assert checklist["id"] == result["checklist_version_id"]
    opened = appeal(client, result["id"])
    assert opened.status_code == 201
    appeal_id = opened.json()["id"]
    assert appeal(client, result["id"]).status_code == 409
    assert client.get(f"/api/v1/appeals/{appeal_id}").json()["status"] == "open"
    changed = override(client, appeal_id)
    assert changed.status_code == 200
    final = changed.json()["evaluation"]
    assert final["original"] == result["original"]
    assert final["final"]["total"] == 100
    assert final["revision"] == 1
    assert changed.json()["appeal"]["decision"]["result"]["answer"] is True
    assert len(pipeline.calls) == 1
    assert override(client, appeal_id, revision=1).status_code == 409
    next_appeal = appeal(client, result["id"]).json()
    assert next_appeal["base_revision"] == 1
    confirm = client.post(
        f"/api/v1/appeals/{next_appeal['id']}/decisions",
        json={
            "action": "confirm",
            "reason": "Подтверждено по реплике",
            "expected_revision": 1,
        },
    )
    assert confirm.status_code == 200
    assert confirm.json()["appeal"]["decision"]["result"]["answer"] is True
    assert confirm.json()["evaluation"]["revision"] == 2
    assert confirm.json()["evaluation"]["original"] == result["original"]
    listing = client.get("/api/v1/appeals", params={"evaluation_id": result["id"]}).json()
    assert listing["total"] == 2
    assert all(a["status"] == "resolved" for a in listing["items"])
    conversation = client.get(f"/api/v1/conversations/{result['conversation_id']}").json()
    assert conversation["latest_evaluation"]["original_total"] == 90
    assert conversation["latest_evaluation"]["final_total"] == 100


def test_no_key_is_explicit_and_creates_no_fake_result(setup):
    client, _, app, pipeline = setup
    payload = inputs(client)
    app.state.evaluation_pipeline_injected = False
    response = client.post("/api/v1/evaluations", json=payload)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_NOT_CONFIGURED"
    assert client.get("/api/v1/evaluations").json()["total"] == 0
    assert not pipeline.calls
    app.state.evaluation_pipeline_injected = True


@pytest.mark.parametrize(
    "patch",
    [
        {"answer": 1},
        {"answer": "true"},
        {"answer": None},
        {"applicability": "not_applicable", "answer": None},
        {"evidence": [{"kind": "message", "message_id": "m9999"}]},
        {"evidence": [{"kind": "range", "start_message_id": "m0002", "end_message_id": "m0001"}]},
        {"evidence": []},
        {"reason": " "},
        {"expected_revision": True},
    ],
)
def test_invalid_decision_is_atomic(setup, patch):
    client = setup[0]
    result = completed(client)
    opened = appeal(client, result["id"]).json()
    response = override(client, opened["id"], **patch)
    assert response.status_code == 422
    assert client.get(f"/api/v1/evaluations/{result['id']}").json() == result
    assert client.get(f"/api/v1/appeals/{opened['id']}").json()["status"] == "open"


def test_concurrent_decisions_and_open_appeal_races(setup):
    client = setup[0]
    result = completed(client)
    with ThreadPoolExecutor(2) as pool:
        opened = list(pool.map(lambda _: appeal(client, result["id"]), range(2)))
    assert sorted(r.status_code for r in opened) == [201, 409]
    contact = next(r.json()["id"] for r in opened if r.status_code == 201)
    other = appeal(client, result["id"], "empathy").json()["id"]
    with ThreadPoolExecutor(2) as pool:
        decided = list(pool.map(lambda id_: override(client, id_), [contact, other]))
    assert sorted(r.status_code for r in decided) == [200, 409]
    assert client.get(f"/api/v1/evaluations/{result['id']}").json()["revision"] == 1
    assert client.get("/api/v1/appeals", params={"status": "open"}).json()["total"] == 1


def test_worker_failure_and_shutdown_are_persisted_safely(setup, caplog):
    client, _, _, pipeline = setup
    caplog.set_level(logging.DEBUG)
    pipeline.failure = RuntimeError("synthetic-secret-prompt-and-token")
    payload = inputs(client)
    result = client.post("/api/v1/evaluations", json=payload).json()
    failed = wait_for(client, result["id"], "failed")
    assert failed["error"]["code"] == "EVALUATION_INTERNAL_ERROR"
    assert failed["original"] is None and failed["final"] is None
    assert failed["revision"] == 0 and failed["completed_at"]
    assert "synthetic-secret" not in caplog.text
    assert "event=evaluation_failed status=failed error=EVALUATION_INTERNAL_ERROR" in caplog.text
    assert sum(r.name == "cqa.errors" for r in caplog.records) == 1
    pipeline.failure = None
    pipeline.delay = 10
    interrupted = client.post("/api/v1/evaluations", json=payload).json()
    wait_for(client, interrupted["id"], "running")
    client.portal.call(stop_evaluation_worker, setup[2])
    assert wait_for(client, interrupted["id"], "failed")["error"]["code"] == "INTERRUPTED"


def test_restart_recovers_queued_and_marks_running_interrupted(setup):
    client, factory, app, pipeline = setup
    payload = inputs(client)
    client.portal.call(stop_evaluation_worker, app)
    with factory.begin() as db:
        queued = evaluations.create(db, EvaluationCreate(**payload))
        running = evaluations.create(db, EvaluationCreate(**payload))
        db.get(Evaluation, running["id"]).status = "running"
    client.portal.call(start_evaluation_worker, app)
    assert wait_for(client, queued["id"])["status"] == "completed"
    assert wait_for(client, running["id"], "failed")["error"]["code"] == "INTERRUPTED"
    assert len(pipeline.calls) == 1


def test_worker_bounded_concurrency_and_snapshot_versions(setup, monkeypatch):
    client, factory, app, pipeline = setup
    client.portal.call(stop_evaluation_worker, app)
    payload = inputs(client)
    sessions = []
    original = evaluations.load_inputs

    def track(db, row):
        sessions.append(db)
        return original(db, row)

    monkeypatch.setattr(evaluations, "load_inputs", track)
    pipeline.on_evaluate = lambda: all_sessions_closed(sessions)
    with factory.begin() as db:
        queued = [evaluations.create(db, EvaluationCreate(**payload)) for _ in range(4)]
    detail = client.get(f"/api/v1/conversations/{payload['conversation_id']}").json()
    changed = {
        "conversation_id": detail["external_id"],
        "language": "KZ",
        "channel": "agent chat",
        "audio_url": None,
        "transcript": [
            {"timestamp": "00:01", "speaker": "operator", "text": "Сәлеметсіз бе!"},
        ],
    }
    client.post("/api/v1/conversations/import", json={"records": [changed]})
    checklist = client.get(f"/api/v1/checklist-versions/{payload['checklist_version_id']}").json()
    checklist["criteria"][0]["id"] = "edited_contact"
    client.post(
        f"/api/v1/checklists/{checklist['checklist_id']}/versions",
        json={
            "expected_version_number": 1,
            "criteria": checklist["criteria"],
        },
    )
    pipeline.delay = 0.1
    client.portal.call(start_evaluation_worker, app)
    for row in queued:
        wait_for(client, row["id"])
    assert pipeline.max_active == 2
    assert all(not s.in_transaction() for s in sessions)
    assert all(
        t["language"] == "RU" and c["criteria"][0]["id"] == "contact" for t, c in pipeline.calls
    )
    latest = client.get(f"/api/v1/checklists/{checklist['checklist_id']}").json()["current_version"]
    new_run = client.post(
        "/api/v1/evaluations",
        json={
            **payload,
            "checklist_version_id": latest["id"],
        },
    ).json()
    wait_for(client, new_run["id"])
    assert pipeline.calls[-1][0]["language"] == "KZ"
    assert pipeline.calls[-1][1]["criteria"][0]["id"] == "edited_contact"


def all_sessions_closed(sessions):
    assert sessions
    assert all(not db.in_transaction() for db in sessions)


def test_paid_failure_preserves_known_provenance(setup, caplog):
    from app.evaluation.errors import EvaluationError

    client, _, _, pipeline = setup
    provenance = {
        "provider": "synthetic-test-only",
        "model_requested": "synthetic-test-only",
        "model_reported": None,
        "prompt_version": "synthetic-v1",
        "duration_ms": 12,
        "usage": {
            "request_count": 2,
            "input_tokens": 10,
            "output_tokens": None,
            "total_tokens": None,
            "cached_input_tokens": None,
            "reasoning_output_tokens": None,
        },
        "estimated_cost_usd": None,
    }
    pipeline.failure = EvaluationError("AI_TIMEOUT", provenance=provenance)
    result = client.post("/api/v1/evaluations", json=inputs(client)).json()
    failed = wait_for(client, result["id"], "failed")
    assert failed["provenance"] == provenance
    assert failed["error"]["code"] == "AI_TIMEOUT"
    assert any(r.name == "cqa.worker" and r.levelname == "ERROR" for r in caplog.records)


def test_graceful_stop_preserves_paid_usage_during_provider_retry(setup):
    from app.evaluation.pipeline import EvaluationPipeline
    from app.evaluation.provider import OpenAIProvider
    from openai import AsyncOpenAI

    client, _, app, _ = setup
    retry_reached = threading.Event()
    calls = []

    def respond(request):
        calls.append(1)
        return httpx.Response(
            200,
            json={
                "id": "resp_synthetic",
                "object": "response",
                "created_at": 1,
                "model": "gpt-6-luna",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_synthetic",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"invalid": "synthetic-test-payload"}),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "input_tokens_details": {"cached_tokens": 30},
                    "output_tokens_details": {"reasoning_tokens": 5},
                },
            },
        )

    async def pause_retry(_):
        retry_reached.set()
        await asyncio.sleep(30)

    settings = Settings(_env_file=None, OPENAI_API_KEY="synthetic-test-only")
    sdk = AsyncOpenAI(
        api_key="synthetic-test-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    provider = OpenAIProvider(settings, client=sdk, sleep=pause_retry)
    app.state.evaluation_worker.pipeline = EvaluationPipeline(settings, provider=provider)
    try:
        created = client.post("/api/v1/evaluations", json=inputs(client)).json()
        assert retry_reached.wait(5)
        client.portal.call(stop_evaluation_worker, app)
        failed = wait_for(client, created["id"], "failed")
        assert failed["error"]["code"] == "INTERRUPTED"
        assert failed["provenance"]["usage"]["request_count"] == 1
        assert failed["provenance"]["usage"]["input_tokens"] == 100
        assert failed["provenance"]["usage"]["total_tokens"] == 120
        assert failed["original"] is None
        assert len(calls) == 1
    finally:
        client.portal.call(sdk.close)


def test_decision_commit_failure_rolls_back_and_never_logs_success(setup, caplog):
    client, factory, _, _ = setup
    result = completed(client)
    opened = appeal(client, result["id"]).json()
    caplog.clear()
    caplog.set_level("INFO", logger="cqa")

    def fail_commit(db):
        if db.info.get("cqa_appeal_decided"):
            raise OperationalError("synthetic-private-sql", {}, RuntimeError("synthetic-private"))

    event.listen(factory, "before_commit", fail_commit)
    try:
        response = override(client, opened["id"])
    finally:
        event.remove(factory, "before_commit", fail_commit)
    assert response.status_code == 503
    assert client.get(f"/api/v1/evaluations/{result['id']}").json() == result
    assert client.get(f"/api/v1/appeals/{opened['id']}").json()["status"] == "open"
    assert "appeal_decision_saved" not in caplog.text
    assert "synthetic-private" not in response.text + caplog.text


def test_history_and_snapshot_columns_are_immutable_in_sql(setup):
    client, factory, _, _ = setup
    result = completed(client)
    opened = appeal(client, result["id"]).json()
    assert override(client, opened["id"]).status_code == 200
    for sql in (
        "UPDATE evaluations SET original='{}'",
        "UPDATE evaluations SET transcript_version_id='changed'",
        "UPDATE evaluations SET status='queued'",
        "UPDATE criterion_results SET result='{}'",
        "DELETE FROM criterion_results",
        "UPDATE appeal_decisions SET reason='changed'",
        "DELETE FROM appeal_decisions",
        "UPDATE appeals SET comment='changed'",
    ):
        with pytest.raises(IntegrityError), factory.begin() as db:
            db.execute(text(sql))
    assert (
        client.get(f"/api/v1/evaluations/{result['id']}").json()["original"] == result["original"]
    )


def test_filters_pagination_and_invalid_transitions(setup):
    client = setup[0]
    result = completed(client)
    params = {"conversation_id": result["conversation_id"], "status": "completed", "limit": 1}
    assert client.get("/api/v1/evaluations", params=params).json()["total"] == 1
    assert client.get("/api/v1/evaluations", params={"status": "failed"}).json()["total"] == 0
    assert client.get("/api/v1/evaluations?limit=0").status_code == 422
    assert client.get("/api/v1/evaluations?status=unknown").status_code == 422
    assert appeal(client, result["id"], "unknown").status_code == 422
    assert client.get("/api/v1/evaluations/invalid-id").status_code == 422
    assert client.get("/api/v1/appeals?offset=-1").status_code == 422
    with setup[1]() as db:
        assert db.scalar(select(Evaluation.status)) == "completed"
