"""Offline full-app smoke against a fresh SQLite DB; never sends an upstream request."""

import argparse
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


class SmokeFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise SmokeFailure(code)


def exercise(client, *, api_only):
    health = client.get("/health")
    require(
        health.status_code == 200 and health.json() == {"status": "ok"}, "HEALTH_FAILED"
    )
    if not api_only:
        page = client.get("/")
        require(
            page.status_code == 200 and "<html" in page.text.lower(), "FRONTEND_FAILED"
        )
        asset_paths = re.findall(r'(?:src|href)="(/assets/[^"<>]+)"', page.text)
        require(bool(asset_paths), "FRONTEND_ASSETS_MISSING")
        for path in asset_paths:
            require(client.get(path).status_code == 200, "FRONTEND_ASSET_FAILED")
    checklists = client.get("/api/v1/checklists")
    require(checklists.status_code == 200, "CHECKLIST_LIST_FAILED")
    require(checklists.json()["total"] >= 1, "CHECKLIST_SEED_FAILED")
    version = checklists.json()["items"][0]["latest_version_id"]
    response = client.post(
        "/api/v1/conversations/import",
        json={
            "records": [
                {
                    "conversation_id": f"synthetic-smoke-{uuid4()}",
                    "language": "RU",
                    "channel": "agent chat",
                    "audio_url": None,
                    "transcript": [
                        {
                            "timestamp": "00:01",
                            "speaker": "client",
                            "text": "Где справка?",
                        },
                        {
                            "timestamp": "00:02",
                            "speaker": "operator",
                            "text": "Здравствуйте! Я Алия.",
                        },
                    ],
                }
            ]
        },
    )
    require(
        response.status_code == 200 and response.json()["created"] == 1, "IMPORT_FAILED"
    )
    conversation = response.json()["conversation_ids"][0]
    detail = client.get(f"/api/v1/conversations/{conversation}")
    require(
        detail.status_code == 200 and len(detail.json()["messages"]) == 2,
        "DETAIL_FAILED",
    )
    evaluation = client.post(
        "/api/v1/evaluations",
        json={"conversation_id": conversation, "checklist_version_id": version},
    )
    require(
        evaluation.status_code == 503
        and evaluation.json()["error"]["code"] == "AI_NOT_CONFIGURED",
        "AI_GUARD_FAILED",
    )
    history = client.get(
        "/api/v1/evaluations", params={"conversation_id": conversation}
    )
    require(
        history.status_code == 200 and history.json()["total"] == 0,
        "AI_GUARD_CREATED_RUN",
    )
    missing = client.get("/api/v1/missing")
    require(missing.status_code == 404, "API_404_FAILED")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-only", action="store_true")
    arguments = parser.parse_args(argv)
    process = None
    try:
        if not arguments.api_only:
            require(
                (ROOT / "frontend/dist/index.html").is_file(), "FRONTEND_BUILD_MISSING"
            )
        with tempfile.TemporaryDirectory(prefix="cqa-smoke-") as directory:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            environment = {
                **os.environ,
                "OPENAI_API_KEY": "",
                "CQA_DATASET_API_URL": "",
                "CQA_DATABASE_URL": f"sqlite:///{directory}/smoke.sqlite3",
                "CQA_FRONTEND_DIST": str(ROOT / "frontend/dist"),
            }
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--workers",
                    "1",
                    "--no-access-log",
                ],
                cwd=ROOT,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                deadline = time.monotonic() + 30
                while True:
                    require(process.poll() is None, "SERVER_EXITED")
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.RequestError:
                        pass
                    require(time.monotonic() < deadline, "SERVER_START_TIMEOUT")
                    time.sleep(0.1)
                exercise(client, api_only=arguments.api_only)
    except SmokeFailure as exc:
        print(f"event=smoke_failed error={exc.code}", file=sys.stderr)
        return 1
    except (httpx.HTTPError, OSError, ValueError, KeyError, IndexError, TypeError):
        print("event=smoke_failed error=SMOKE_INTERNAL_ERROR", file=sys.stderr)
        return 1
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    print("event=smoke_completed status=completed upstream_requests=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
