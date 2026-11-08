"""Isolated browser acceptance harness. Synthetic AI only; never a production mode."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import httpx
import uvicorn
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings

# app.main creates its module-level ASGI app during import. Isolate this standalone
# test process BEFORE that import, including the otherwise implicit Settings().
setting_aliases = {
    field.alias.casefold() for field in Settings.model_fields.values() if field.alias
}
for name in tuple(os.environ):
    if name.casefold() in setting_aliases:
        os.environ.pop(name, None)
Settings.model_config["env_file"] = None

from app.evaluation.pipeline import EvaluationPipeline
from app.evaluation.prompts import INSTRUCTIONS
from app.evaluation.provider import OpenAIProvider
from app.main import create_app


class SyntheticProvider:
    """Run the real SDK adapter against an in-memory HTTP transport, with visible provenance."""

    def __init__(self, settings, report):
        self.calls = []
        self.report = report
        self.sdk = AsyncOpenAI(
            api_key="synthetic-offline-only",
            base_url="https://synthetic.invalid/v1",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.respond)),
        )
        self.adapter = OpenAIProvider(settings, client=self.sdk)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("[]")

    def respond(self, request):
        body = json.loads(request.content)
        assert body["instructions"] == INSTRUCTIONS
        assert "ONLY the operator" in body["instructions"]
        assert [item["role"] for item in body["input"]] == ["user"]
        data = json.loads(body["input"][0]["content"])
        checklist = data["checklist_snapshot"]
        transcript = data["untrusted_transcript_snapshot"]
        self.calls.append(data)
        # Test-only artifact contains our synthetic snapshots. Never emit it to logs/stdout.
        self.report.write_text(json.dumps(self.calls, ensure_ascii=False))
        results = []
        for criterion in checklist["criteria"]:
            na = criterion["id"] == "identification"
            answer = criterion["id"] != "contact"
            if criterion["type"] == "scale":
                answer = sorted(p["value"] for p in criterion["scale"])[-2]
            results.append(
                {
                    "criterion_id": criterion["id"],
                    "applicability": "not_applicable" if na else "applicable",
                    "answer": None if na else answer,
                    "explanation": "Синтетический ответ для проверки интеграции; не оценка модели.",
                    "evidence": [
                        {
                            "kind": "range",
                            "start_message_id": "m0001",
                            "end_message_id": transcript["messages"][-1]["id"],
                        }
                    ],
                    "review_reasons": [],
                }
            )
        return httpx.Response(
            200,
            json={
                "id": "resp_synthetic",
                "object": "response",
                "created_at": 1,
                "model": "synthetic-offline-only",
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
                                "text": json.dumps(
                                    {"criterion_results": results, "review_reasons": []}
                                ),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                # Deliberately fabricated test counters, never live usage or billing evidence.
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    async def evaluate(self, transcript, checklist, prompt_version):
        result = await self.adapter.evaluate(transcript, checklist, prompt_version)
        return result.model_copy(update={"provider": "synthetic"})

    async def aclose(self):
        await self.sdk.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8019)
    parser.add_argument(
        "--report", type=Path, default=ROOT / "artifacts/submission/calls.json"
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="cqa-offline-acceptance-") as temporary:
        settings = Settings(
            _env_file=None,
            CQA_DATABASE_URL=f"sqlite:///{temporary}/acceptance.sqlite3",
            CQA_FRONTEND_DIST=ROOT / "frontend/dist",
            OPENAI_API_KEY="synthetic-offline-only",
            OPENAI_MODEL="synthetic-offline-only",
            CQA_DATASET_API_URL="",
            CQA_LLM_MAX_RETRIES=0,
        )
        app = create_app(settings)
        app.state.evaluation_pipeline = EvaluationPipeline(
            settings, provider=SyntheticProvider(settings, args.report)
        )
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
