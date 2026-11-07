"""Assembled batch/worker/export responses match the shared submission contract offline."""

import time
from uuid import uuid4

from fastapi.testclient import TestClient
from test_contracts import validator

from app.config import Settings
from app.evaluation.errors import EvaluationError
from app.evaluation.pipeline import PipelineResult
from app.evaluation.scoring import calculate_assessment
from app.main import create_app


class SyntheticPipeline:
    def __init__(self):
        self.failure_used = False

    async def evaluate(self, *, transcript, checklist):
        if transcript["messages"][0]["text"] == "synthetic-failure" and not self.failure_used:
            self.failure_used = True
            raise EvaluationError("AI_TIMEOUT")
        results = [
            {
                "criterion_id": criterion["id"],
                "applicability": "applicable",
                "answer": (
                    max(step["value"] for step in criterion["scale"])
                    if criterion["type"] == "scale"
                    else criterion["type"] == "binary"
                ),
                "explanation": "Собственный синтетический ответ для проверки контракта.",
                "evidence": [{"kind": "message", "message_id": transcript["messages"][0]["id"]}],
                "review_reasons": [],
            }
            for criterion in checklist["criteria"]
        ]
        return PipelineResult(
            assessment=calculate_assessment(
                criteria=checklist["criteria"], results=results, messages=transcript["messages"]
            ),
            provenance={
                "provider": "synthetic",
                "model_requested": "synthetic-provider",
                "model_reported": "synthetic-provider",
                "prompt_version": "synthetic-v1",
                "duration_ms": 1,
                "usage": {
                    "request_count": 1,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "total_tokens": 2,
                    "cached_input_tokens": 0,
                    "reasoning_output_tokens": 0,
                },
                "estimated_cost_usd": None,
            },
            review_required=False,
            review_reasons=[],
        )


def test_batch_worker_export_and_reload_match_canonical_contract(tmp_path):
    settings = Settings(_env_file=None, CQA_DATABASE_URL=f"sqlite:///{tmp_path}/contract.sqlite3")
    app = create_app(settings)
    app.state.evaluation_pipeline = SyntheticPipeline()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/import",
            json={
                "records": [
                    {
                        "conversation_id": f"synthetic-contract-{index}",
                        "language": "RU",
                        "channel": "agent chat",
                        "audio_url": None,
                        "transcript": [
                            {
                                "timestamp": "00:01",
                                "speaker": "operator",
                                "text": text,
                            }
                        ],
                    }
                    for index, text in enumerate(("synthetic-success", "synthetic-failure"))
                ]
            },
        )
        assert response.status_code == 200
        version = client.get("/api/v1/checklists").json()["items"][0]["latest_version_id"]
        request = {
            "request_id": str(uuid4()),
            "conversation_ids": response.json()["conversation_ids"],
            "checklist_version_id": version,
        }
        response = client.post("/api/v1/evaluation-batches", json=request)
        assert response.status_code == 202
        batch_id = response.json()["id"]
        validator("EvaluationBatch").validate(response.json())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            batch = client.get(f"/api/v1/evaluation-batches/{batch_id}").json()
            validator("EvaluationBatch").validate(batch)
            if batch["status"] == "completed_with_errors":
                break
            time.sleep(0.02)
        assert (batch["total"], batch["completed"], batch["failed"]) == (2, 1, 1)
        validator("EvaluationBatchPage").validate(client.get("/api/v1/evaluation-batches").json())
        export_request = {"batch_id": batch_id, "team_name": "Synthetic CQA team"}
        response = client.post("/api/v1/submission-exports", json=export_request)
        assert response.status_code == 200
        document = response.json()
        validator("SubmissionDocument").validate(document)
        assert {row["conversation_id"] for row in document["results"]} == {
            "synthetic-contract-0",
            "synthetic-contract-1",
        }
        assert sorted(row["status"] for row in document["results"]) == ["error", "ok"]
        response = client.post(f"/api/v1/evaluation-batches/{batch_id}/retry-failed")
        assert response.status_code == 202
        child_id = response.json()["id"]
        assert response.json()["total"] == 2
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            child = client.get(f"/api/v1/evaluation-batches/{child_id}").json()
            validator("EvaluationBatch").validate(child)
            if child["status"] == "completed":
                break
            time.sleep(0.02)
        assert child["completed"] == 2
        child_request = {**export_request, "batch_id": child_id}
        child_document = client.post("/api/v1/submission-exports", json=child_request).json()
        validator("SubmissionDocument").validate(child_document)
        assert len(child_document["results"]) == 2
        assert all(item["status"] == "ok" for item in child_document["results"])
        assert client.post("/api/v1/submission-exports", json=export_request).json() == document
    with TestClient(create_app(settings)) as client:
        validator("EvaluationBatch").validate(
            client.get(f"/api/v1/evaluation-batches/{batch_id}").json()
        )
        assert client.post("/api/v1/submission-exports", json=export_request).json() == document
        assert (
            client.post("/api/v1/submission-exports", json=child_request).json() == child_document
        )
