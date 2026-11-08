"""Official submission export tests; all input and AI dependencies are synthetic."""

import asyncio
import logging
from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_batches_api import batch_payload, wait_batch
from test_evaluations_api import appeal, override
from test_evaluations_api import setup as evaluation_setup

from app.models.evaluations import Evaluation
from app.schemas.data import ImportRequest
from app.schemas.submissions import SubmissionDocument
from app.services import conversations, evaluations
from app.services.worker import stop_evaluation_worker

setup = evaluation_setup


def reference(client, ids=None):
    # This standalone synthetic reference spans all imported source records, not batch members.
    if ids is None:
        ids = sorted(
            {
                c["external_id"]
                for c in client.get("/api/v1/conversations", params={"limit": 100}).json()["items"]
            }
        )
    return {"expected_conversation_ids": ids, "expected_total_records": len(ids)}


def export(client, batch_id, team_name="Synthetic team", expected_ids=None):
    return client.post(
        "/api/v1/submission-exports",
        json={
            "batch_id": batch_id,
            "team_name": team_name,
            **reference(client, expected_ids),
        },
    )


@pytest.mark.parametrize(
    ("count", "expected", "missing", "extra"),
    [
        (1, ["PRIVATE_REFERENCE_ONLY"], 1, 1),
        (1, ["synthetic-evaluation", "PRIVATE_REFERENCE_ONLY"], 1, 0),
        (2, ["synthetic-evaluation"], 0, 1),
        (2, ["synthetic-evaluation", "synthetic-batch-0"], 0, 0),
    ],
)
def test_independent_scope_preflight_and_export_gate(
    setup, caplog, count, expected, missing, extra
):
    from sqlalchemy import text

    client, factory, app, pipeline = setup
    client.portal.call(stop_evaluation_worker, app)
    payload = batch_payload(client, count)
    batch = client.post("/api/v1/evaluation-batches", json=payload).json()
    calls_before = len(pipeline.calls)
    with factory() as db:
        before = [
            db.scalar(text(f"SELECT COUNT(*) FROM {table}"))
            for table in ("evaluations", "evaluation_batches", "evaluation_batch_items")
        ]
    caplog.set_level("INFO", logger="cqa")
    preflight = client.post(
        "/api/v1/submission-preflights",
        json={
            "batch_id": batch["id"],
            **reference(client, expected),
        },
    )
    assert preflight.status_code == 200
    matches = missing == extra == 0
    assert preflight.json() == {
        "expected_count": len(expected),
        "batch_count": count,
        "missing_count": missing,
        "extra_count": extra,
        "matches": matches,
    }
    result = export(client, batch["id"], expected_ids=expected)
    if matches:
        assert result.status_code == 200
        assert len(result.json()["results"]) == count
        assert all(row["error"] == "EVALUATION_PENDING" for row in result.json()["results"])
    else:
        assert result.status_code == 409
        assert result.json()["error"]["code"] == "SUBMISSION_SCOPE_MISMATCH"
        assert "PRIVATE_REFERENCE_ONLY" not in result.text + caplog.text
        assert "event=submission_export_completed" not in caplog.text
    with factory() as db:
        after = [
            db.scalar(text(f"SELECT COUNT(*) FROM {table}"))
            for table in ("evaluations", "evaluation_batches", "evaluation_batch_items")
        ]
    assert after == before
    assert len(pipeline.calls) == calls_before


@pytest.mark.parametrize(
    "patch",
    [
        {"expected_conversation_ids": []},
        {"expected_conversation_ids": ["duplicate", " duplicate "], "expected_total_records": 2},
        {"expected_conversation_ids": [1]},
        {"expected_conversation_ids": [" "]},
        {"expected_total_records": True},
        {"expected_total_records": "1"},
        {"expected_total_records": 0},
        {"expected_total_records": 2},
        {"expected_total_records": 1001},
    ],
)
def test_invalid_reference_rejected_without_export(setup, patch):
    client, _, app, _ = setup
    client.portal.call(stop_evaluation_worker, app)
    batch = client.post("/api/v1/evaluation-batches", json=batch_payload(client, 1)).json()
    body = {"batch_id": batch["id"], **reference(client), **patch}
    assert client.post("/api/v1/submission-preflights", json=body).status_code == 422
    assert (
        client.post(
            "/api/v1/submission-exports",
            json={
                **body,
                "team_name": "Synthetic team",
            },
        ).status_code
        == 422
    )


def test_legacy_export_and_reference_normalization_are_explicit(setup):
    client, _, app, _ = setup
    client.portal.call(stop_evaluation_worker, app)
    batch = client.post("/api/v1/evaluation-batches", json=batch_payload(client, 1)).json()
    assert (
        client.post(
            "/api/v1/submission-exports",
            json={
                "batch_id": batch["id"],
                "team_name": "Synthetic team",
            },
        ).status_code
        == 422
    )
    assert export(client, batch["id"], expected_ids=[" synthetic-evaluation "]).status_code == 200
    missing = client.post(
        "/api/v1/submission-preflights",
        json={
            "batch_id": "71000000-0000-4000-8000-000000000999",
            **reference(client),
        },
    )
    assert missing.status_code == 404
    assert export(client, batch["id"], expected_ids=["001"]).status_code == 409


def test_submission_official_mapping_na_ranges_flags_original_and_no_new_ai(setup, caplog):
    from app.evaluation.scoring import calculate_assessment
    from app.services.evaluations import RESULT_FIELDS

    client, _, app, pipeline = setup
    payload = batch_payload(client, 1)
    detail = client.get(f"/api/v1/conversations/{payload['conversation_ids'][0]}").json()
    client.post(
        "/api/v1/conversations/import",
        json={
            "records": [
                {
                    "conversation_id": detail["external_id"],
                    "language": "RU",
                    "channel": "agent chat",
                    "transcript": [
                        {
                            "timestamp": "00:01",
                            "speaker": "system",
                            "text": "PRIVATE_SYSTEM_MARKER",
                        },
                        {
                            "timestamp": "00:02",
                            "speaker": "client",
                            "text": "PRIVATE_CLIENT_MARKER",
                        },
                        {"timestamp": "00:03", "speaker": "bot", "text": "PRIVATE_BOT_MARKER"},
                        {
                            "timestamp": "00:04",
                            "speaker": "operator",
                            "text": "PRIVATE_OPERATOR_MARKER",
                        },
                    ],
                }
            ]
        },
    )
    original_evaluate = pipeline.evaluate

    async def richer_result(**kwargs):
        result = await original_evaluate(**kwargs)
        answers = [{key: c[key] for key in RESULT_FIELDS} for c in result.assessment["criteria"]]
        for answer in answers:
            if answer["criterion_id"] == "needs":
                answer.update(applicability="not_applicable", answer=None)
            elif answer["criterion_id"] == "management":
                answer.update(
                    answer=7,
                    evidence=[
                        {"kind": "range", "start_message_id": "m0001", "end_message_id": "m0004"},
                        {"kind": "message", "message_id": "m0003"},
                    ],
                )
            elif answer["criterion_id"] == "gross_errors":
                answer["answer"] = True
        result.assessment = calculate_assessment(
            criteria=kwargs["checklist"]["criteria"],
            results=answers,
            messages=kwargs["transcript"]["messages"],
        )
        result.provenance.update(
            model_requested="synthetic-requested", model_reported="synthetic-actual"
        )
        return result

    pipeline.evaluate = richer_result
    batch = client.post("/api/v1/evaluation-batches", json=payload).json()
    finished = wait_batch(client, batch["id"])
    evaluation_id = finished["items"][0]["evaluation_id"]
    original = client.get(f"/api/v1/evaluations/{evaluation_id}").json()
    assert original["original"]["total"] == 82.94
    caplog.set_level(logging.INFO, logger="cqa")
    app.state.evaluation_pipeline_injected = False
    response = export(client, batch["id"], "  Synthetic team  ")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="results.json"'
    document = response.json()
    SubmissionDocument.model_validate(document)
    assert set(document) == {"schema_version", "team_name", "model", "results"}
    assert document["schema_version"] == "1.0" and document["team_name"] == "Synthetic team"
    assert document["model"] == {"mode": "external_api", "name": "synthetic-actual"}
    row = document["results"][0]
    assert set(row) == {"conversation_id", "status", "criteria", "score"}
    assert row["conversation_id"] == detail["external_id"]
    assert row["status"] == "ok"
    assert row["score"] == {"final_score": 82.94, "critical_flag": True}
    by_id = {c["criterion_id"]: c for c in row["criteria"]}
    assert len(by_id) == 8
    assert by_id["discovery"]["value"] is None
    assert by_id["dialogue"]["value"] == 7
    assert by_id["dialogue"]["evidence_turns"] == [1, 2, 3, 4]
    assert by_id["critical"]["value"] is True
    assert all(
        set(c) == {"criterion_id", "value", "rationale", "evidence_turns"} for c in row["criteria"]
    )
    opened = appeal(client, evaluation_id).json()
    changed = override(client, opened["id"], evidence=[{"kind": "message", "message_id": "m0004"}])
    assert changed.status_code == 200
    assert changed.json()["evaluation"]["final"]["total"] != original["original"]["total"]
    assert export(client, batch["id"]).json() == document
    assert len(pipeline.calls) == 1
    assert all(
        marker not in caplog.text
        for marker in (
            "PRIVATE_SYSTEM_MARKER",
            "PRIVATE_CLIENT_MARKER",
            "PRIVATE_BOT_MARKER",
            "PRIVATE_OPERATOR_MARKER",
        )
    )
    assert "event=submission_export_completed records=1 failed=0" in caplog.text
    app.state.evaluation_pipeline_injected = True


def test_submission_preserves_pending_failed_review_and_success_rows(setup, caplog):
    client, factory, app, pipeline = setup
    client.portal.call(stop_evaluation_worker, app)
    payload = batch_payload(client, 4)
    batch = client.post("/api/v1/evaluation-batches", json=payload).json()
    pending, failed, review, success = batch["items"]
    with factory.begin() as db:
        failed_row = db.get(Evaluation, failed["evaluation_id"])
        failed_row.status = "running"
        db.flush()
        evaluations.fail(db, failed_row.id, "AI_TIMEOUT", "PRIVATE_FAILURE_MESSAGE")
    for item, requires_review, model in (
        (review, True, "synthetic-b"),
        (success, False, "synthetic-a"),
    ):
        with factory.begin() as db:
            evaluation = db.get(Evaluation, item["evaluation_id"])
            evaluation.status = "running"
            transcript, checklist = evaluations.load_inputs(db, evaluation)
        result = asyncio.run(pipeline.evaluate(transcript=transcript, checklist=checklist))
        result.review_required = requires_review
        result.provenance["model_requested"] = model
        with factory.begin() as db:
            evaluations.complete(db, item["evaluation_id"], result)
    calls_before = len(pipeline.calls)
    caplog.set_level(logging.INFO, logger="cqa")
    app.state.evaluation_pipeline_injected = False
    response = export(client, batch["id"], "PRIVATE_TEAM_NAME")
    assert response.status_code == 200
    rows = response.json()["results"]
    assert len(rows) == 4
    assert [r["status"] for r in rows] == ["error", "error", "error", "ok"]
    assert [r["error"] for r in rows[:3]] == [
        "EVALUATION_PENDING",
        "AI_TIMEOUT",
        "EVALUATION_REVIEW_REQUIRED",
    ]
    assert all(r["criteria"] == [] and r["score"] is None for r in rows[:3])
    assert len({r["conversation_id"] for r in rows}) == 4
    assert response.json()["model"]["name"] == "synthetic-a, synthetic-b"
    assert len(pipeline.calls) == calls_before
    assert "PRIVATE_FAILURE_MESSAGE" not in response.text + caplog.text
    assert "PRIVATE_TEAM_NAME" not in caplog.text
    assert "event=submission_export_completed records=4 failed=3" in caplog.text
    with factory() as db:
        assert db.get(Evaluation, pending["evaluation_id"]).status == "queued"
    app.state.evaluation_pipeline_injected = True


def test_submission_no_attempt_reports_not_run_and_never_requires_key(setup):
    client, _, app, pipeline = setup
    client.portal.call(stop_evaluation_worker, app)
    batch = client.post("/api/v1/evaluation-batches", json=batch_payload(client, 1)).json()
    app.state.evaluation_pipeline_injected = False
    response = export(client, batch["id"])
    assert response.status_code == 200
    assert response.json()["model"]["name"] == "not_run"
    assert response.json()["results"][0]["error"] == "EVALUATION_PENDING"
    assert not pipeline.calls
    app.state.evaluation_pipeline_injected = True


def test_submission_rejects_changed_rubric_but_accepts_cosmetic_names(setup, caplog):
    client, _, app, _ = setup
    client.portal.call(stop_evaluation_worker, app)
    payload = batch_payload(client, 1)
    checklist = client.get(f"/api/v1/checklist-versions/{payload['checklist_version_id']}").json()
    caplog.set_level(logging.INFO, logger="cqa")
    changed = deepcopy(checklist["criteria"])
    changed[0]["instruction"] = "PRIVATE_CHANGED_RUBRIC"
    version = client.post(
        f"/api/v1/checklists/{checklist['checklist_id']}/versions",
        json={"expected_version_number": 1, "criteria": changed},
    ).json()
    batch = client.post(
        "/api/v1/evaluation-batches", json={**payload, "checklist_version_id": version["id"]}
    ).json()
    rejected = export(client, batch["id"])
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "SUBMISSION_CHECKLIST_INCOMPATIBLE"
    assert "PRIVATE_CHANGED_RUBRIC" not in rejected.text + caplog.text
    assert "event=submission_export_completed" not in caplog.text
    cosmetic = deepcopy(checklist["criteria"])
    for criterion in cosmetic:
        criterion.update(name="Cosmetic name", section="Cosmetic section")
    cosmetic.reverse()
    version = client.post(
        f"/api/v1/checklists/{checklist['checklist_id']}/versions",
        json={"expected_version_number": 2, "criteria": cosmetic},
    ).json()
    batch = client.post(
        "/api/v1/evaluation-batches",
        json={
            **payload,
            "request_id": "9951d957-aacc-4214-b96e-6d209b25eff2",
            "checklist_version_id": version["id"],
        },
    ).json()
    assert export(client, batch["id"]).status_code == 200
    assert any(
        r.levelname == "WARNING" and "SUBMISSION_CHECKLIST_INCOMPATIBLE" in r.message
        for r in caplog.records
    )


def test_submission_rejects_duplicate_external_ids_from_distinct_groups(setup, caplog):
    client, factory, app, _ = setup
    client.portal.call(stop_evaluation_worker, app)
    payload = batch_payload(client, 1)
    detail = client.get(f"/api/v1/conversations/{payload['conversation_ids'][0]}").json()
    with factory.begin() as db:
        imported = conversations.import_records(
            db,
            ImportRequest(
                records=[
                    {
                        "conversation_id": detail["external_id"],
                        "language": "RU",
                        "channel": "agent chat",
                        "transcript": [
                            {"timestamp": "00:01", "speaker": "operator", "text": "Synthetic"}
                        ],
                    }
                ]
            ),
            source="dataset",
            group_id="synthetic-second-group",
        )
    payload["conversation_ids"].extend(imported["conversation_ids"])
    batch = client.post("/api/v1/evaluation-batches", json=payload).json()
    caplog.set_level(logging.INFO, logger="cqa")
    response = export(client, batch["id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SUBMISSION_DUPLICATE_CONVERSATION_ID"
    assert "event=submission_export_completed" not in caplog.text


@pytest.mark.parametrize("team_name", ["", " ", "a" * 201])
def test_submission_rejects_invalid_team_name(setup, team_name):
    client, _, app, _ = setup
    client.portal.call(stop_evaluation_worker, app)
    batch = client.post("/api/v1/evaluation-batches", json=batch_payload(client, 1)).json()
    assert export(client, batch["id"], team_name).status_code == 422


def test_submission_schema_rejects_invalid_official_values_and_flags(setup):
    client = setup[0]
    batch = client.post("/api/v1/evaluation-batches", json=batch_payload(client, 1)).json()
    wait_batch(client, batch["id"])
    document = export(client, batch["id"]).json()
    for criterion_id, value in (
        ("contact", 1),
        ("empathy", None),
        ("dialogue", True),
        ("consultation", 7),
    ):
        invalid = deepcopy(document)
        next(c for c in invalid["results"][0]["criteria"] if c["criterion_id"] == criterion_id)[
            "value"
        ] = value
        with pytest.raises(ValidationError):
            SubmissionDocument.model_validate(invalid)
    invalid = deepcopy(document)
    invalid["results"][0]["score"]["critical_flag"] = True
    with pytest.raises(ValidationError):
        SubmissionDocument.model_validate(invalid)


@pytest.mark.parametrize("corruption", ["score", "extra_criterion"])
def test_submission_corrupt_saved_result_is_a_safe_error_not_a_success(setup, caplog, corruption):
    client, _, _, pipeline = setup
    original_evaluate = pipeline.evaluate

    async def corrupt_result(**kwargs):
        result = await original_evaluate(**kwargs)
        if corruption == "score":
            result.assessment["total"] = 1
        else:
            extra = deepcopy(result.assessment["criteria"][0])
            extra["criterion_id"] = "synthetic_extra"
            result.assessment["criteria"].append(extra)
        return result

    pipeline.evaluate = corrupt_result
    batch = client.post("/api/v1/evaluation-batches", json=batch_payload(client, 1)).json()
    wait_batch(client, batch["id"])
    caplog.set_level(logging.INFO, logger="cqa")
    response = export(client, batch["id"])
    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["status"] == "error" and row["error"] == "SUBMISSION_INVALID_RESULT"
    assert row["score"] is None and row["criteria"] == []
    assert (
        "event=submission_result_rejected error=SUBMISSION_INVALID_RESULT records=1" in caplog.text
    )
    assert "event=submission_export_completed records=1 failed=1" in caplog.text


def test_retry_chain_export_preserves_full_scope_and_reuses_successful_evaluation(setup):
    from app.evaluation.errors import EvaluationError

    client, _, _, pipeline = setup
    payload = batch_payload(client, 2)
    failed_id = payload["conversation_ids"][0]
    should_fail = True
    original_evaluate = pipeline.evaluate

    async def selective_failure(**kwargs):
        result = await original_evaluate(**kwargs)
        if kwargs["transcript"]["conversation_id"] == failed_id and should_fail:
            raise EvaluationError("AI_TIMEOUT", provenance=result.provenance)
        return result

    pipeline.evaluate = selective_failure
    source = client.post("/api/v1/evaluation-batches", json=payload).json()
    source = wait_batch(client, source["id"])
    assert source["total"] == 2 and source["completed"] == source["failed"] == 1
    source_export = export(client, source["id"]).json()
    success_id = next(i["evaluation_id"] for i in source["items"] if i["status"] == "completed")
    child = client.post(f"/api/v1/evaluation-batches/{source['id']}/retry-failed").json()
    assert child["total"] == 2
    child = wait_batch(client, child["id"])
    assert child["failed"] == child["completed"] == 1
    should_fail = False
    grandchild = client.post(f"/api/v1/evaluation-batches/{child['id']}/retry-failed").json()
    grandchild = wait_batch(client, grandchild["id"])
    assert grandchild["total"] == grandchild["completed"] == 2
    assert success_id in {i["evaluation_id"] for i in grandchild["items"]}
    final = export(client, grandchild["id"]).json()
    assert len(final["results"]) == 2 and all(r["status"] == "ok" for r in final["results"])
    assert {r["conversation_id"] for r in final["results"]} == {
        r["conversation_id"] for r in source_export["results"]
    }
    assert export(client, source["id"]).json() == source_export
    assert client.get(f"/api/v1/evaluation-batches/{source['id']}").json() == source
    assert len(pipeline.calls) == 4  # Two initial attempts and one per failed-only retry.
