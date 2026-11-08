"""The test-only harness must be isolated even before its factory is called."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_harness_import_never_reads_dotenv_or_inherits_application_settings(tmp_path):
    trap = tmp_path / ".env"
    trap.write_text("CQA_EVALUATION_CONCURRENCY=synthetic-invalid-setting\n")
    script = """
import os, runpy, sys
from pathlib import Path
from unittest.mock import patch
from app.config import Settings
Settings.model_config['env_file'] = Path(sys.argv[1])
with patch('pydantic_settings.sources.providers.dotenv.DotEnvSettingsSource._read_env_file',
           side_effect=AssertionError('DOTENV_READ_FORBIDDEN')):
    runpy.run_path(sys.argv[2], run_name='offline_acceptance_import_probe')
assert Settings.model_config['env_file'] is None
assert 'CQA_EVALUATION_CONCURRENCY' not in os.environ
assert 'OPENAI_API_KEY' not in os.environ
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(trap), str(ROOT / "tools/offline_acceptance_server.py")],
        cwd=ROOT / "backend",
        env={
            **os.environ,
            "OPENAI_API_KEY": "synthetic-environment-must-be-ignored",
            "CQA_EVALUATION_CONCURRENCY": "synthetic-invalid-setting",
        },
        capture_output=True,
        timeout=15,
        check=False,
    )
    # Do not display inherited settings, captured output or dotenv contents on failure.
    if result.returncode:
        pytest.fail("Offline harness import isolation failed", pytrace=False)
    leaked = b"synthetic-environment-must-be-ignored" in result.stdout + result.stderr
    assert not leaked
