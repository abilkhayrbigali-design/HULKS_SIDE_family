"""Offline batch regressions using real HTTP/SQLite/worker and an injected pipeline."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from test_evaluations_api import inputs, wait_for
from test_evaluations_api import setup as evaluation_setup

from app.models.batches import EvaluationBatch, EvaluationBatchItem
from app.models.evaluations import Evaluation
from app.services.worker import start_evaluation_worker, stop_evaluation_worker

setup = evaluation_setup


def batch_payload(client, count=2):
    one = inputs(client)
    if count == 1:
        ids = [one["conversation_id"]]
    else:
        imported = client.post(
            "/api/v1/conversations/import",
            json={
                "records": [
                    {
                        "conversation_id": f"synthetic-batch-{i}",
                        "language": "RU",
                        "channel": "agent chat",
                        "transcript": [
                            {"timestamp": "00:01", "speaker": "operator", "text": "Synthetic only"}
                        ],
                    }
                    for i in range(count - 1)
                ]
            },
        )
        assert imported.status_code == 200
        ids = [one["conversation_id"], *imported.json()["conversation_ids"]]
    return {
        "request_id": str(uuid4()),
        "conversation_ids": ids,
        "checklist_version_id": one["checklist_version_id"],
    }


def wait_batch(client, id_):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/evaluation-batches/{id_}")
        assert response.status_code == 200
        result = response.json()
        if result["status"] in {"completed", "completed_with_errors"}:
            return result
        time.sleep(0.02)
    pytest.fail("Batch did not finish")


def test_batch_worker_persistence_counts_and_idempotent_submit(setup, caplog):
    client, factory, app, pipeline = setup
    caplog.set_level(logging.INFO, logger="cqa")
    client.portal.call(stop_evaluation_worker, app)
    payload = batch_payload(client, 3)
    created = client.post("/api/v1/evaluation-batches", json=payload)
    assert created.status_code == 202
    batch = created.json()
    assert batch["status"] == "queued"
    assert batch["queued"] == batch["total"] == 3
    assert batch["running"] == batch["failed"] == batch["completed"] == 0
    repeated = client.post(
        "/api/v1/evaluation-batches",
        json={**payload, "conversation_ids": list(reversed(payload["conversation_ids"]))},
    )
    assert repeated.json() == batch
    assert caplog.text.count("event=evaluation_batch_saved records=3") == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Evaluation)) == 3
    pipeline.delay = 0.1
    client.portal.call(start_evaluation_worker, app)
    result = wait_batch(client, batch["id"])
    assert result["status"] == "completed"
    assert result["completed"] == result["total"] == 3
    assert result["queued"] == result["running"] == result["failed"] == 0
    assert pipeline.max_active <= 2 and len(pipeline.calls) == 3
    assert client.get("/api/v1/evaluation-batches?limit=1").json()["items"] == [result]


def test_batch_retry_only_failed_preserves_snapshots_and_source(setup):
    client, factory, app, pipeline = setup
    client.portal.call(stop_evaluation_worker, app)
    payload = batch_payload(client, 3)
    created = client.post("/api/v1/evaluation-batches", json=payload).json()
    # Complete one and leave two jobs running to simulate process interruption.
    first, *others = created["items"]
    with factory.begin() as db:
        for item in others:
            db.get(Evaluation, item["evaluation_id"]).status = "running"
    client.portal.call(start_evaluation_worker, app)
    source = wait_batch(client, created["id"])
    assert source["completed"] == 1 and source["failed"] == 2
    assert source["status"] == "completed_with_errors"
    client.portal.call(stop_evaluation_worker, app)
    for item in others:
        detail = client.get(f"/api/v1/conversations/{item['conversation_id']}").json()
        assert (
            client.post(
                "/api/v1/conversations/import",
                json={
                    "records": [
                        {
                            "conversation_id": detail["external_id"],
                            "language": "KZ",
                            "channel": "agent chat",
                            "transcript": [
                                {"timestamp": "00:02", "speaker": "client", "text": "Жаңа мәтін"}
                            ],
                        }
                    ]
                },
            ).status_code
            == 200
        )
    retry = client.post(f"/api/v1/evaluation-batches/{source['id']}/retry-failed")
    assert retry.status_code == 202
    child = retry.json()
    assert child["source_batch_id"] == source["id"]
    assert child["request_id"] != source["request_id"]
    assert child["queued"] == 2
    assert child["completed"] == 1 and child["total"] == source["total"] == 3
    assert {i["transcript_version_id"] for i in child["items"]} == {
        i["transcript_version_id"] for i in source["items"]
    }
    assert child["items"][0]["evaluation_id"] == first["evaluation_id"]
    assert {i["evaluation_id"] for i in child["items"][1:]}.isdisjoint(
        i["evaluation_id"] for i in others
    )
    assert client.post(f"/api/v1/evaluation-batches/{source['id']}/retry-failed").json() == child
    assert client.get(f"/api/v1/evaluation-batches/{source['id']}").json() == source
    client.portal.call(start_evaluation_worker, app)
    assert wait_batch(client, child["id"])["completed"] == 3
    assert len(pipeline.calls) == 3
    assert all(t["language"] == "RU" for t, _ in pipeline.calls)
    assert client.get(f"/api/v1/evaluation-batches/{source['id']}").json() == source


def test_batch_validation_missing_id_and_no_key_leave_no_jobs(setup, caplog):
    client, factory, app, pipeline = setup
    payload = batch_payload(client)
    caplog.set_level(logging.DEBUG)
    for patch in (
        {"conversation_ids": []},
        {"conversation_ids": payload["conversation_ids"] * 2},
        {"conversation_ids": [str(uuid4()) for _ in range(1001)]},
        {"request_id": "private-marker-invalid"},
    ):
        response = client.post("/api/v1/evaluation-batches", json={**payload, **patch})
        assert response.status_code == 422
        assert "private-marker-invalid" not in response.text
    for patch in (
        {"conversation_ids": [payload["conversation_ids"][0], str(uuid4())]},
        {"checklist_version_id": str(uuid4())},
    ):
        response = client.post("/api/v1/evaluation-batches", json={**payload, **patch})
        assert response.status_code == 404
    app.state.evaluation_pipeline_injected = False
    assert client.post("/api/v1/evaluation-batches", json=payload).status_code == 503
    app.state.evaluation_pipeline_injected = True
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Evaluation)) == 0
        assert db.scalar(select(func.count()).select_from(EvaluationBatch)) == 0
    assert pipeline.calls == []
    assert "private-marker" not in caplog.text


def test_batch_concurrent_duplicate_create_and_retry_do_not_duplicate_jobs(setup):
    client, factory, app, _ = setup
    client.portal.call(stop_evaluation_worker, app)
    payload = batch_payload(client)
    with ThreadPoolExecutor(2) as pool:
        responses = list(
            pool.map(lambda _: client.post("/api/v1/evaluation-batches", json=payload), range(2))
        )
    assert [r.status_code for r in responses] == [202, 202]
    batch = responses[0].json()
    assert responses[1].json() == batch
    with factory.begin() as db:
        for item in batch["items"]:
            db.get(Evaluation, item["evaluation_id"]).status = "running"
    client.portal.call(start_evaluation_worker, app)
    source = wait_batch(client, batch["id"])
    assert source["failed"] == 2
    client.portal.call(stop_evaluation_worker, app)
    with ThreadPoolExecutor(2) as pool:
        retries = list(
            pool.map(
                lambda _: client.post(f"/api/v1/evaluation-batches/{source['id']}/retry-failed"),
                range(2),
            )
        )
    assert [r.status_code for r in retries] == [202, 202]
    assert retries[0].json() == retries[1].json()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Evaluation)) == 4
        assert db.scalar(select(func.count()).select_from(EvaluationBatch)) == 2


def test_batch_conflicts_are_explicit_and_history_is_immutable(setup):
    client, factory, app, _ = setup
    client.portal.call(stop_evaluation_worker, app)
    payload = batch_payload(client)
    batch = client.post("/api/v1/evaluation-batches", json=payload).json()
    conflict = client.post(
        "/api/v1/evaluation-batches",
        json={**payload, "conversation_ids": payload["conversation_ids"][:1]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    retry = client.post(f"/api/v1/evaluation-batches/{batch['id']}/retry-failed")
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "BATCH_NOT_FINISHED"
    for table, column in (
        ("evaluation_batches", "request_id"),
        ("evaluation_batch_items", "position"),
    ):
        for operation in (
            f"UPDATE {table} SET {column}='changed'",
            f"DELETE FROM {table}",
        ):
            with pytest.raises(IntegrityError), factory.begin() as db:
                db.execute(text(operation))
    client.portal.call(start_evaluation_worker, app)
    wait_batch(client, batch["id"])
    retry = client.post(f"/api/v1/evaluation-batches/{batch['id']}/retry-failed")
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "BATCH_NO_FAILED_ITEMS"


def test_batch_commit_failure_rolls_back_all_and_has_no_success_log(setup, caplog):
    client, factory, app, pipeline = setup
    client.portal.call(stop_evaluation_worker, app)
    payload = batch_payload(client)
    caplog.set_level(logging.INFO, logger="cqa")

    def fail_commit(db):
        if db.info.get("cqa_batch_saved"):
            raise OperationalError("private-batch-sql", {}, RuntimeError("private-batch-key"))

    event.listen(factory, "before_commit", fail_commit)
    try:
        response = client.post("/api/v1/evaluation-batches", json=payload)
    finally:
        event.remove(factory, "before_commit", fail_commit)
    assert response.status_code == 503
    with factory() as db:
        for model in (Evaluation, EvaluationBatch, EvaluationBatchItem):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    assert "event=evaluation_batch_saved" not in caplog.text
    assert "private-batch" not in response.text + caplog.text
    assert any(r.levelname == "ERROR" for r in caplog.records)
    assert not pipeline.calls


def test_batch_stop_is_persisted_and_does_not_rerun_interrupted(setup, caplog):
    client, _, app, pipeline = setup
    pipeline.delay = 10
    payload = batch_payload(client, 1)
    caplog.set_level(logging.INFO, logger="cqa")
    created = client.post("/api/v1/evaluation-batches", json=payload).json()
    wait_for(client, created["items"][0]["evaluation_id"], "running")
    client.portal.call(stop_evaluation_worker, app)
    result = wait_batch(client, created["id"])
    assert result["failed"] == 1
    assert result["items"][0]["error_code"] == "INTERRUPTED"
    client.portal.call(start_evaluation_worker, app)
    assert client.get(f"/api/v1/evaluation-batches/{created['id']}").json() == result
    assert len(pipeline.calls) == 1
    assert "event=evaluation_failed status=failed error=INTERRUPTED" in caplog.text


def test_batch_accepts_1000_items_without_exceeding_worker_budget(setup):
    client, factory, app, pipeline = setup
    client.portal.call(stop_evaluation_worker, app)
    payload = batch_payload(client, 1000)
    response = client.post("/api/v1/evaluation-batches", json=payload)
    assert response.status_code == 202
    assert response.json()["total"] == response.json()["queued"] == 1000
    assert len(response.json()["items"]) == 1000
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Evaluation)) == 1000
    assert not pipeline.calls


def test_batch_reimport_and_new_checklist_version_cannot_change_frozen_inputs(setup):
    client, _, app, pipeline = setup
    client.portal.call(stop_evaluation_worker, app)
    payload = batch_payload(client, 1)
    batch = client.post("/api/v1/evaluation-batches", json=payload).json()
    detail = client.get(f"/api/v1/conversations/{payload['conversation_ids'][0]}").json()
    client.post(
        "/api/v1/conversations/import",
        json={
            "records": [
                {
                    "conversation_id": detail["external_id"],
                    "language": "EN",
                    "channel": "agent chat",
                    "transcript": [
                        {"timestamp": "00:09", "speaker": "operator", "text": "New version"}
                    ],
                }
            ]
        },
    )
    checklist = client.get(f"/api/v1/checklist-versions/{payload['checklist_version_id']}").json()
    checklist["criteria"][0]["id"] = "new_contact"
    version = client.post(
        f"/api/v1/checklists/{checklist['checklist_id']}/versions",
        json={"expected_version_number": 1, "criteria": checklist["criteria"]},
    )
    assert version.status_code == 201
    assert client.post("/api/v1/evaluation-batches", json=payload).json() == batch
    client.portal.call(start_evaluation_worker, app)
    wait_batch(client, batch["id"])
    assert pipeline.calls[0][0]["language"] == "RU"
    assert pipeline.calls[0][0]["id"] == batch["items"][0]["transcript_version_id"]
    assert pipeline.calls[0][1]["id"] == payload["checklist_version_id"]
    assert pipeline.calls[0][1]["criteria"][0]["id"] == "contact"


def test_retry_failed_no_key_and_commit_failure_preserve_source(setup, caplog):
    client, factory, app, pipeline = setup
    pipeline.failure = RuntimeError("PRIVATE_PIPELINE_FAILURE")
    source = client.post("/api/v1/evaluation-batches", json=batch_payload(client, 1)).json()
    source = wait_batch(client, source["id"])
    assert source["failed"] == 1
    caplog.set_level(logging.INFO, logger="cqa")
    caplog.clear()
    app.state.evaluation_pipeline_injected = False
    response = client.post(f"/api/v1/evaluation-batches/{source['id']}/retry-failed")
    assert response.status_code == 503
    app.state.evaluation_pipeline_injected = True

    def fail_commit(db):
        if db.info.get("cqa_batch_saved"):
            raise OperationalError("PRIVATE_RETRY_SQL", {}, RuntimeError("PRIVATE_RETRY_KEY"))

    event.listen(factory, "before_commit", fail_commit)
    try:
        response = client.post(f"/api/v1/evaluation-batches/{source['id']}/retry-failed")
    finally:
        event.remove(factory, "before_commit", fail_commit)
    assert response.status_code == 503
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(EvaluationBatch)) == 1
        assert db.scalar(select(func.count()).select_from(Evaluation)) == 1
    assert client.get(f"/api/v1/evaluation-batches/{source['id']}").json() == source
    assert "event=evaluation_batch_saved" not in caplog.text
    assert "PRIVATE_RETRY" not in response.text + caplog.text
