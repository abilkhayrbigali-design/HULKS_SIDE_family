"""Temporary synthetic Git histories exercise redaction and retained-history risks."""

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "public_readiness", ROOT / "tools/check_public_readiness.py"
)
audit_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_module)


def git(root, *args):
    return subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Synthetic QA",
            "-c",
            "user.email=synthetic@example.invalid",
            *args,
        ],
        capture_output=True,
        check=True,
    )


def repository(tmp_path, ignores=True):
    git(tmp_path, "init", "--initial-branch=main")
    if ignores:
        (tmp_path / ".gitignore").write_text(".env\n.env.*\ndata/private/\nartifacts/\n*.sqlite3\n")
        (tmp_path / ".dockerignore").write_text(".env\ndata/private\nartifacts\n")
    (tmp_path / "README.md").write_text("Synthetic clean repository\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "synthetic initial")
    return tmp_path


def test_removed_signature_is_still_detected_in_reachable_history_without_echo(tmp_path, caplog):
    root = repository(tmp_path)
    marker = "synthetic-private-signature-marker"
    address = "https://" + "synthetic-host.company.local/workflow?sig=" + marker
    (root / "README.md").write_text(address)
    git(root, "add", ".")
    git(root, "commit", "-m", "synthetic historical risk")
    (root / "README.md").write_text("Synthetic clean current tree\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "synthetic current clean")
    caplog.set_level("INFO", logger="cqa.public_readiness")
    report = audit_module.audit(root)
    finding = next(row for row in report["findings"] if row["code"] == "SIGNED_URL_REVIEW")
    assert finding["in_index"] is False
    assert finding["containing_commit_count"] == 1
    assert report["status"] == "REVIEW_REQUIRED"
    assert marker not in json.dumps(report) + caplog.text
    assert address not in json.dumps(report) + caplog.text
    assert "event=public_readiness_completed" in caplog.text


def test_reserved_host_signatures_are_informational_but_keys_are_not_exempted():
    signature = ("https://" + "synthetic.invalid/?sig=synthetic-only").encode()
    assert audit_module.content_codes("backend/tests/test_example.py", signature) == {
        ("SYNTHETIC_HOST_SIGNED_URL", False)
    }
    key = ("sk-" + "x" * 32).encode()
    assert ("SECRET_SHAPED_LITERAL_REVIEW", True) in audit_module.content_codes(
        "tests/example.py", key
    )


def test_unsafe_paths_are_redacted_and_private_paths_need_no_content():
    assert audit_module.safe_path("reports/file?sig=synthetic-value") == "[REDACTED_PATH]"
    assert audit_module.private_path(".env")
    assert audit_module.private_path("data/private/local.json")
    assert audit_module.private_path("local.sqlite3")
    assert not audit_module.private_path(".env.example")


def test_ignore_gaps_and_unstaged_tracked_changes_block_a_clean_claim(tmp_path):
    root = repository(tmp_path, ignores=False)
    (root / "README.md").write_text("Synthetic uncommitted change\n")
    report = audit_module.audit(root)
    codes = {row["code"] for row in report["findings"] if row["blocking"]}
    assert {"GITIGNORE_GAP", "DOCKERIGNORE_REVIEW", "TRACKED_WORKTREE_CHANGE"} <= codes
    assert report["gitignore_probes_passed"] == 0


def test_empty_secret_template_does_not_consume_the_following_setting():
    body = (
        b"OPENAI_API_KEY=\nOPENAI_MODEL=gpt-6-luna\n"
        b"CQA_DATASET_API_URL=\nCQA_DEFAULT_GROUP_ID=DEV\n"
    )
    assert not audit_module.content_codes(".env.example", body)
    assert ("NONEMPTY_SECRET_TEMPLATE", True) in audit_module.content_codes(
        ".env.example", b"OPENAI_API_KEY=synthetic-nonempty-template\n"
    )
