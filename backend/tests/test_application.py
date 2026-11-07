"""Exercise the assembled app with real migrations and synthetic HTTP payloads, offline."""

import json
import logging
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate
from sqlalchemy import inspect, text

from app.config import Settings
from app.main import build_engine, create_app

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "contracts/openapi.json").read_text())
FIXTURES = ROOT / "data/fixtures/synthetic"


def assert_contract(name, payload):
    schema = {"$ref": f"#/components/schemas/{name}", "components": CONTRACT["components"]}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)


def test_runtime_openapi_documents_contract_operations_and_examples(settings):
    runtime = create_app(settings).openapi()
    validate(runtime)
    assert set(runtime["paths"]) == set(CONTRACT["paths"])
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    examples = {}
    for example in manifest["fixtures"]:
        examples.setdefault(example["schema"], []).append(
            json.loads((FIXTURES / example["file"]).read_text())
        )
    for path, operations in CONTRACT["paths"].items():
        assert set(runtime["paths"][path]) == set(operations)
        for method, expected in operations.items():
            actual = runtime["paths"][path][method]
            assert set(expected["responses"]) <= set(actual["responses"])
            pairs = [
                (response, actual["responses"][status])
                for status, response in expected["responses"].items()
            ]
            if "requestBody" in expected:
                pairs.append((expected["requestBody"], actual["requestBody"]))
            for expected_body, actual_body in pairs:
                expected_schema = expected_body["content"]["application/json"]["schema"]
                actual_schema = actual_body["content"]["application/json"]["schema"]
                schema_name = expected_schema["$ref"].rsplit("/", 1)[1]
                validator = Draft202012Validator(
                    {**actual_schema, "components": runtime["components"]},
                    format_checker=FormatChecker(),
                )
                for example in examples.get(schema_name, []):
                    validator.validate(example)


def test_verbose_library_payload_logs_are_suppressed(caplog):
    settings = Settings(
        _env_file=None, CQA_DATABASE_URL="sqlite:///:memory:", CQA_LOG_LEVEL="DEBUG"
    )
    create_app(settings)
    with caplog.at_level(logging.DEBUG):
        for name in ("openai", "httpx", "httpcore", "sqlalchemy.engine", "sqlalchemy.pool"):
            logging.getLogger(name).warning("synthetic-private-library-payload")
    assert "synthetic-private-library-payload" not in caplog.text


def test_sdk_debug_environment_cannot_reenable_payload_logging():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import logging; import app.main; import openai; "
            "logging.getLogger('openai').warning('synthetic-private-sdk-marker'); "
            "assert logging.getLogger('openai').getEffectiveLevel() >= logging.CRITICAL",
        ],
        env={**os.environ, "OPENAI_LOG": "debug", "OPENAI_API_KEY": "", "CQA_DATASET_API_URL": ""},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0
    assert "synthetic-private-sdk-marker" not in result.stdout + result.stderr


def test_memory_worker_does_not_commit_a_request_transaction(settings):
    with TestClient(create_app(settings)) as client:
        engine = client.app.state.engine
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE atomicity_probe (value INTEGER)"))
        with client.app.state.session_factory() as db:
            db.execute(text("INSERT INTO atomicity_probe VALUES (1)"))
            # The idle worker polls during this transaction; its commit must be independent.
            time.sleep(0.6)
            db.rollback()
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM atomicity_probe")) == 0


def test_startup_migrates_and_seeds_one_checklist(settings, caplog):
    caplog.set_level(logging.INFO, logger="cqa")
    with TestClient(create_app(settings)) as client:
        assert {"conversations", "messages", "checklists", "checklist_versions"} <= set(
            inspect(client.app.state.engine).get_table_names()
        )
        listing = client.get("/api/v1/checklists").json()
        assert_contract("ChecklistSummaryPage", listing)
        assert listing["total"] == 1
        item = listing["items"][0]
        detail = client.get(f"/api/v1/checklists/{item['id']}").json()
        assert_contract("ChecklistDetail", detail)
        assert len(detail["current_version"]["criteria"]) == 8
        assert_contract("ChecklistVersion", detail["current_version"])
    for event in (
        "application_starting",
        "database_ready",
        "application_ready",
        "application_stopped",
    ):
        assert f"event={event}" in caplog.text


def test_assembled_import_persists_across_restarts(tmp_path):
    settings = Settings(_env_file=None, CQA_DATABASE_URL=f"sqlite:///{tmp_path}/app.sqlite3")
    payload = {
        "records": [
            {
                "conversation_id": "synthetic-application-001",
                "language": "RU",
                "channel": "agent chat",
                "audio_url": None,
                "transcript": [
                    {"timestamp": "00:01", "speaker": "client", "text": "Где моя справка?"},
                    {"timestamp": "00:02", "speaker": "operator", "text": "Здравствуйте! Я Алия."},
                ],
            }
        ]
    }
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/conversations/import", json=payload)
        assert response.status_code == 200
        assert_contract("ImportSummary", response.json())
        conversation_id = response.json()["conversation_ids"][0]
        original = client.get(f"/api/v1/conversations/{conversation_id}").json()
        assert_contract("ConversationDetail", original)
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/api/v1/checklists").json()["total"] == 1
        assert restarted.get(f"/api/v1/conversations/{conversation_id}").json() == original
        listing = restarted.get("/api/v1/conversations").json()
        assert_contract("ConversationSummaryPage", listing)


def test_startup_failure_has_safe_diagnostics(settings, caplog):
    caplog.set_level(logging.INFO, logger="cqa")
    with patch("app.main.migrate", side_effect=RuntimeError("synthetic-secret-startup")):
        with pytest.raises(RuntimeError) as error, TestClient(create_app(settings)):
            pytest.fail("Startup must fail before requests can be served")
    rendered = "".join(traceback.format_exception(error.value)) + caplog.text
    assert "synthetic-secret-startup" not in rendered
    assert "APPLICATION_STARTUP_FAILED" in caplog.text
    assert "event=application_ready" not in caplog.text
    assert "event=application_stopped" in caplog.text
    errors = [record for record in caplog.records if record.name == "cqa.errors"]
    assert len(errors) == 1
    assert errors[0].levelno == logging.ERROR


@pytest.mark.parametrize("failure_phase", ["start", "stop"])
def test_worker_lifecycle_failure_is_safe_and_disposes_engine(settings, caplog, failure_phase):
    engine = build_engine(settings)
    start, stop = AsyncMock(), AsyncMock()
    (start if failure_phase == "start" else stop).side_effect = RuntimeError(
        "synthetic-private-worker-failure"
    )
    caplog.set_level(logging.INFO, logger="cqa")
    with (
        patch("app.main.build_engine", return_value=engine),
        patch.object(engine, "dispose", wraps=engine.dispose) as dispose,
        patch("app.services.worker.start_evaluation_worker", start),
        patch("app.services.worker.stop_evaluation_worker", stop),
    ):
        with pytest.raises(RuntimeError) as error, TestClient(create_app(settings)):
            pass
    start.assert_awaited_once()
    stop.assert_awaited_once()
    dispose.assert_called_once()
    rendered = "".join(traceback.format_exception(error.value)) + caplog.text
    assert "synthetic-private-worker-failure" not in rendered
    expected_code = (
        "APPLICATION_STARTUP_FAILED" if failure_phase == "start" else "APPLICATION_SHUTDOWN_FAILED"
    )
    errors = [record for record in caplog.records if record.name == "cqa.errors"]
    assert len(errors) == 1
    assert expected_code in errors[0].getMessage()
    assert errors[0].levelno == logging.ERROR


def test_built_frontend_and_api_share_origin_without_exposing_paths(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Synthetic CQA shell</title>")
    (dist / "assets/app.js").write_text("window.synthetic = true;")
    (tmp_path / "private.txt").write_text("synthetic-private-marker")
    settings = Settings(
        _env_file=None, CQA_DATABASE_URL="sqlite:///:memory:", CQA_FRONTEND_DIST=dist
    )
    with TestClient(create_app(settings)) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert "Synthetic CQA shell" in index.text
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/health").json() == {"status": "ok"}
        wrong_method = client.post("/health")
        assert wrong_method.status_code == 405
        assert wrong_method.headers["allow"] == "GET"
        assert client.get("/api/v1/checklists").json()["total"] == 1
        for path in ("/api/v1/missing", "/assets/missing.js", "/%2E%2E/private.txt", "/.env"):
            response = client.get(path)
            assert response.status_code == 404
            assert_contract("Error", response.json())
            assert "synthetic-private-marker" not in response.text
