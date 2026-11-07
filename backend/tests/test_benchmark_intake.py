"""Own synthetic cases only: no human labels, real transcripts or measured model quality."""

import copy
import hashlib
import importlib.util
import json
import logging
import subprocess
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.evaluation.benchmark import compare_predictions
from app.evaluation.benchmark_intake import (
    IntakeError,
    frozen_cases,
    merge_labels,
    read_json,
    saved_predictions,
    write_private_new,
)
from app.evaluation.errors import EvaluationError
from app.evaluation.scoring import calculate_assessment

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data/fixtures/synthetic"


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def store(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False))


@pytest.fixture
def package(tmp_path):
    """A six-case frozen draft plus simulated human assertions, never actual GT."""
    directory = tmp_path / "annotation-v1"
    directory.mkdir()
    checklist = read_json(FIXTURES / "checklist-version.response.json")
    transcript = read_json(FIXTURES / "transcript.snapshot.json")
    provider = read_json(FIXTURES / "provider.response.json")
    cases = []
    parts = {}
    for split in ("tune", "holdout"):
        parts[split] = {}
        for language in ("RU", "KZ", "EN"):
            case_id = f"synthetic-{split}-{language}"
            case = {
                "case_id": case_id,
                "split": split,
                "annotator": "synthetic-human-assertion",
                "transcript": copy.deepcopy(transcript),
                "checklist": checklist,
                "criterion_results": copy.deepcopy(provider["criterion_results"]),
            }
            case["transcript"].update(
                id=str(uuid5(NAMESPACE_URL, case_id + "-transcript")),
                conversation_id=str(uuid5(NAMESPACE_URL, case_id)),
                language=language,
            )
            path = tmp_path / f"{split}-{language}.labels.json"
            store(path, {"annotation_source": "human", "dataset_id": "synthetic", "cases": [case]})
            parts[split][language] = path
            draft = copy.deepcopy(case)
            draft["annotator"] = ""
            for row in draft["criterion_results"]:
                row.update(applicability=None, answer=None, explanation="", evidence=[])
            cases.append(draft)
    draft = {"annotation_source": "pending_human", "dataset_id": "synthetic", "cases": cases}
    manifest = {
        "state": "pending_human",
        "dataset_id": "synthetic",
        "draft_sha256": digest(draft),
        "checklist_snapshot_sha256": digest(checklist),
        "cases": len(cases),
        "split_assignments": {case["case_id"]: case["split"] for case in cases},
        "split_counts": {"tune": 3, "holdout": 3},
        "groups": [{"cases": [case["case_id"]]} for case in cases],
    }
    store(directory / "manifest.json", manifest)
    store(directory / "labels.draft.json", draft)
    store(directory / "checklist.snapshot.json", checklist)
    return directory, parts


def cli_module():
    spec = importlib.util.spec_from_file_location(
        "benchmark_intake_cli", ROOT / "tools/prepare_benchmark.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def labels_args(directory, parts, output, split="tune"):
    return [
        "labels",
        "--package",
        str(directory),
        "--split",
        split,
        "--human-signoff",
        "--ru",
        str(parts[split]["RU"]),
        "--kz",
        str(parts[split]["KZ"]),
        "--en",
        str(parts[split]["EN"]),
        "--output",
        str(output),
    ]


def evaluation_input(package, tmp_path, status="completed"):
    directory, parts = package
    case = read_json(parts["tune"]["RU"])["cases"][0]
    evaluation = read_json(FIXTURES / f"evaluation.{status}.json")
    evaluation.update(
        conversation_id=case["transcript"]["conversation_id"],
        transcript_version_id=case["transcript"]["id"],
        checklist_version_id=case["checklist"]["id"],
    )
    if status == "completed":
        evaluation["original"] = calculate_assessment(
            criteria=case["checklist"]["criteria"],
            results=case["criterion_results"],
            messages=case["transcript"]["messages"],
        )
        evaluation["final"] = copy.deepcopy(evaluation["original"])
        evaluation["final"]["total"] = 0
        evaluation["revision"] = 1
    path = tmp_path / "saved-evaluations.json"
    source = {"cases": [{"case_id": case["case_id"], "evaluation": evaluation}]}
    store(path, source)
    return directory, path, source


@pytest.mark.parametrize("split", ["tune", "holdout"])
def test_merge_frozen_split_only_without_mutation(package, split):
    directory, parts = package
    before = {path: path.read_bytes() for path in directory.iterdir()}
    labels = merge_labels(directory, parts[split], split=split)
    assert len(labels.cases) == 3
    assert {case.split for case in labels.cases} == {split}
    assert {case.transcript.language for case in labels.cases} == {"RU", "KZ", "EN"}
    assert compare_predictions(labels, {"cases": []}, split=split)["overall"]["missing"] == 3
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize(
    "change",
    [
        "pending",
        "blank_annotator",
        "missing",
        "duplicate",
        "extra",
        "split",
        "text",
        "checklist",
        "evidence",
        "answer",
        "criterion",
    ],
)
def test_reject_incomplete_altered_or_invalid_labels(package, change):
    directory, parts = package
    path = parts["tune"]["RU"]
    part = read_json(path)
    case = part["cases"][0]
    if change == "pending":
        part["annotation_source"] = "pending_human"
    elif change == "blank_annotator":
        case["annotator"] = " "
    elif change == "missing":
        part["cases"] = []
    elif change == "duplicate":
        part["cases"].append(copy.deepcopy(case))
    elif change == "extra":
        case["case_id"] = "synthetic-unknown"
    elif change == "split":
        case["split"] = "holdout"
    elif change == "text":
        case["transcript"]["messages"][0]["text"] += " SYNTHETIC_PRIVATE_MARKER"
    elif change == "checklist":
        case["checklist"]["criteria"][0]["weight"] = float(
            case["checklist"]["criteria"][0]["weight"]
        )
    elif change == "evidence":
        case["criterion_results"][0]["evidence"] = [{"kind": "message", "message_id": "m9999"}]
    elif change == "answer":
        case["criterion_results"][0]["answer"] = 1
    else:
        case["criterion_results"].pop()
    store(path, part)
    with pytest.raises((ValueError, EvaluationError)):
        merge_labels(directory, parts["tune"], split="tune")


@pytest.mark.parametrize(
    "change", ["hash", "split", "group_leakage", "duplicate_group", "checklist"]
)
def test_reject_changed_package_or_split_leakage(package, change):
    directory, _ = package
    path = directory / "manifest.json"
    manifest = read_json(path)
    if change == "hash":
        manifest["draft_sha256"] = "0" * 64
    elif change == "split":
        manifest["split_assignments"][next(iter(manifest["split_assignments"]))] = "holdout"
    elif change == "group_leakage":
        manifest["groups"][0]["cases"].append(manifest["groups"][3]["cases"][0])
    elif change == "duplicate_group":
        manifest["groups"].append(copy.deepcopy(manifest["groups"][0]))
    else:
        checklist_path = directory / "checklist.snapshot.json"
        checklist = read_json(checklist_path)
        checklist["name"] = "changed"
        store(checklist_path, checklist)
    store(path, manifest)
    with pytest.raises(IntakeError):
        frozen_cases(directory, "tune")


def test_original_not_final_and_saved_archived_versions(package, tmp_path):
    directory, path, source = evaluation_input(package, tmp_path)
    before = path.read_bytes()
    predictions = saved_predictions(directory, path, split="tune")
    labels = merge_labels(directory, package[1]["tune"], split="tune")
    report = compare_predictions(labels, predictions, split="tune")
    assert report["overall"]["completed"] == 1
    assert report["overall"]["missing"] == 2
    assert report["overall"]["total_mae"] == 0
    saved = source["cases"][0]["evaluation"]
    assert saved["original"]["total"] != saved["final"]["total"]
    assert predictions.cases[0].result.usage.model_dump() == saved["provenance"]["usage"]
    assert path.read_bytes() == before


@pytest.mark.parametrize("known_provenance", [True, False])
def test_failed_predictions_preserve_known_or_unknown_usage(package, tmp_path, known_provenance):
    directory, path, source = evaluation_input(package, tmp_path, "failed")
    evaluation = source["cases"][0]["evaluation"]
    evaluation["error"]["message"] = "SYNTHETIC_PRIVATE_MARKER"
    if known_provenance:
        evaluation["provenance"] = read_json(FIXTURES / "evaluation.completed.json")["provenance"]
    else:
        evaluation["provenance"] = None
    store(path, source)
    predictions = saved_predictions(directory, path, split="tune")
    prediction = predictions.cases[0]
    assert prediction.result is None
    assert (prediction.failure_provenance is not None) == known_provenance
    assert "SYNTHETIC_PRIVATE_MARKER" not in predictions.model_dump_json()
    if known_provenance:
        assert prediction.failure_provenance.usage.model_dump() == evaluation["provenance"]["usage"]


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "snapshot",
        "conversation",
        "unknown",
        "original",
        "zero_attempts",
        "queued",
        "running",
    ],
)
def test_invalid_saved_evaluations_are_rejected(package, tmp_path, change):
    directory, path, source = evaluation_input(
        package, tmp_path, change if change in {"queued", "running"} else "completed"
    )
    item = source["cases"][0]
    evaluation = item["evaluation"]
    if change == "duplicate":
        source["cases"].append(copy.deepcopy(item))
    elif change == "snapshot":
        evaluation["transcript_version_id"] = str(uuid5(NAMESPACE_URL, "changed-version"))
    elif change == "conversation":
        evaluation["conversation_id"] = str(uuid5(NAMESPACE_URL, "changed-conversation"))
    elif change == "unknown":
        item["case_id"] = "unknown"
    elif change == "original":
        evaluation["original"]["total"] = 0
    elif change == "zero_attempts":
        evaluation["provenance"]["usage"]["request_count"] = 0
    store(path, source)
    with pytest.raises(ValueError):
        saved_predictions(directory, path, split="tune")


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / "input.json"
    path.write_text('{"cases": [], "cases": []}')
    with pytest.raises(IntakeError, match="BENCHMARK_DUPLICATE_JSON_KEY"):
        read_json(path)


def test_empty_language_part_requires_no_invented_cases(package):
    directory, parts = package
    draft_path = directory / "labels.draft.json"
    draft = read_json(draft_path)
    excluded = next(
        case["case_id"]
        for case in draft["cases"]
        if case["split"] == "tune" and case["transcript"]["language"] == "EN"
    )
    draft["cases"] = [case for case in draft["cases"] if case["case_id"] != excluded]
    manifest_path = directory / "manifest.json"
    manifest = read_json(manifest_path)
    manifest["draft_sha256"] = digest(draft)
    manifest["cases"] -= 1
    manifest["split_counts"]["tune"] -= 1
    del manifest["split_assignments"][excluded]
    manifest["groups"] = [group for group in manifest["groups"] if excluded not in group["cases"]]
    store(draft_path, draft)
    store(manifest_path, manifest)
    store(
        parts["tune"]["EN"], {"annotation_source": "human", "dataset_id": "synthetic", "cases": []}
    )
    labels = merge_labels(directory, parts["tune"], split="tune")
    assert len(labels.cases) == 2


def test_private_atomic_output_never_overwrites_or_follows_target_symlink(tmp_path):
    target = tmp_path / "new.json"
    write_private_new(target, {"private": "synthetic"})
    assert target.stat().st_mode & 0o777 == 0o600
    before = target.read_bytes()
    with pytest.raises(IntakeError, match="BENCHMARK_OUTPUT_EXISTS"):
        write_private_new(target, {"changed": True})
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(IntakeError, match="BENCHMARK_OUTPUT_EXISTS"):
        write_private_new(link, {"changed": True})
    assert target.read_bytes() == before
    assert not list(tmp_path.glob(".benchmark-*"))


def test_output_write_failure_leaves_no_partial_or_temporary_file(tmp_path, monkeypatch):
    def failed_link(*args, **kwargs):
        raise OSError("SYNTHETIC_PRIVATE_MARKER")

    monkeypatch.setattr("app.evaluation.benchmark_intake.os.link", failed_link)
    target = tmp_path / "output.json"
    with pytest.raises(OSError):
        write_private_new(target, {"synthetic": True})
    assert not target.exists()
    assert not list(tmp_path.glob(".benchmark-*"))


def test_cli_success_safe_failure_and_no_false_output(package, tmp_path, caplog, capsys):
    directory, parts = package
    cli = cli_module()
    output = tmp_path / "labels.json"
    caplog.set_level(logging.INFO, logger="cqa.benchmark")
    assert cli.main(labels_args(directory, parts, output)) == 0
    assert output.stat().st_mode & 0o777 == 0o600
    assert "event=benchmark_intake_completed records=3" in caplog.text
    caplog.clear()
    bad_part = parts["tune"]["RU"]
    bad_part.write_text("SYNTHETIC_PRIVATE_MARKER")
    failed_output = tmp_path / "SYNTHETIC_PRIVATE_MARKER.json"
    assert cli.main(labels_args(directory, parts, failed_output)) == 2
    assert not failed_output.exists()
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "error=BENCHMARK_INVALID_INPUT" in errors[0].message
    assert "SYNTHETIC_PRIVATE_MARKER" not in caplog.text + capsys.readouterr().out
    assert str(tmp_path) not in caplog.text


@pytest.mark.parametrize("reason", ["pending", "coverage", "existing"])
def test_cli_expected_refusals_have_safe_error_logs(package, tmp_path, caplog, reason):
    directory, parts = package
    output = tmp_path / "SYNTHETIC_PRIVATE_MARKER.json"
    if reason == "existing":
        output.write_text("unchanged")
        code = "BENCHMARK_OUTPUT_EXISTS"
    else:
        path = parts["tune"]["RU"]
        part = read_json(path)
        if reason == "pending":
            part["annotation_source"] = "pending_human"
            code = "BENCHMARK_HUMAN_LABELS_REQUIRED"
        else:
            part["cases"] = []
            code = "BENCHMARK_LABEL_COVERAGE_MISMATCH"
        store(path, part)
    with caplog.at_level(logging.INFO, logger="cqa.benchmark"):
        assert cli_module().main(labels_args(directory, parts, output)) == 2
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert f"error={code}" in errors[0].message
    assert "SYNTHETIC_PRIVATE_MARKER" not in caplog.text
    assert "benchmark_intake_completed" not in caplog.text
    assert output.read_text() == "unchanged" if reason == "existing" else not output.exists()


def test_cli_interrupt_is_safe_and_does_not_publish(package, tmp_path, monkeypatch, caplog):
    directory, parts = package
    cli = cli_module()

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "merge_labels", interrupted)
    output = tmp_path / "output.json"
    with caplog.at_level(logging.INFO, logger="cqa.benchmark"):
        assert cli.main(labels_args(directory, parts, output)) == 130
    assert "error=BENCHMARK_INTERRUPTED" in caplog.text
    assert not output.exists()


def test_predictions_cli_feeds_existing_benchmark_without_network(package, tmp_path):
    directory, source, _ = evaluation_input(package, tmp_path)
    predictions = tmp_path / "predictions.json"
    assert (
        cli_module().main(
            [
                "predictions",
                "--package",
                str(directory),
                "--split",
                "tune",
                "--evaluations",
                str(source),
                "--output",
                str(predictions),
            ]
        )
        == 0
    )
    labels = tmp_path / "labels.json"
    write_private_new(
        labels, merge_labels(directory, package[1]["tune"], split="tune").model_dump(mode="json")
    )
    process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/evaluate_dev.py"),
            "--labels",
            str(labels),
            "--predictions",
            str(predictions),
            "--split",
            "tune",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0
    report = json.loads(process.stdout)
    assert report["overall"]["cases"] == 3
    assert report["overall"]["completed"] == 1
    assert report["overall"]["missing"] == 2
    assert report["overall"]["total_mae"] == 0


def test_standalone_cli_from_another_cwd_and_safe_arguments(package, tmp_path):
    directory, parts = package
    command = [sys.executable, str(ROOT / "tools/prepare_benchmark.py")]
    result = subprocess.run(
        command + labels_args(directory, parts, tmp_path / "labels.json"),
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert "benchmark_intake_completed records=3" in result.stderr
    invalid = subprocess.run(
        command + ["--SYNTHETIC_PRIVATE_MARKER"], cwd=tmp_path, capture_output=True, text=True
    )
    assert invalid.returncode == 2
    assert "BENCHMARK_INVALID_ARGUMENTS" in invalid.stderr
    assert "SYNTHETIC_PRIVATE_MARKER" not in invalid.stderr
