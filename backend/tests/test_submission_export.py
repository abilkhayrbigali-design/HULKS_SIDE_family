"""Synthetic export cases only; no human labels, organizer data or external calls."""

import copy
import importlib.util
import json
import logging
from pathlib import Path
from uuid import uuid4

import pytest

from app.evaluation.errors import EvaluationError
from app.evaluation.submission import (
    ID_MAP,
    SubmissionExportError,
    build_submission,
    project_snapshots,
    validate_submission,
)
from app.services.seed import initial_checklist

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "export_submission_cli", ROOT / "tools/export_submission.py"
)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
PRIVATE = "SYNTHETIC_PRIVATE_TRANSCRIPT"


@pytest.fixture
def source():
    messages = [
        {"timestamp": f"00:0{i}", "speaker": role, "text": f"{PRIVATE} {i}"}
        for i, role in enumerate(["client", "bot", "operator", "system"], 1)
    ]
    record = {
        "conversation_id": "synthetic-original-id",
        "language": "RU",
        "channel": "agent chat",
        "transcript": messages,
        "audio_url": None,
    }
    case = {
        "case_id": "synthetic-case",
        "transcript": {
            "id": str(uuid4()),
            "conversation_id": str(uuid4()),
            "language": "RU",
            "channel": "agent chat",
            "messages": [
                {"id": f"m{i * 10:04d}", "position": i * 10, **m} for i, m in enumerate(messages, 1)
            ],
        },
        "checklist": {
            "id": str(uuid4()),
            "checklist_id": str(uuid4()),
            "version_number": 1,
            "created_at": "2026-11-08T00:00:00Z",
            **initial_checklist().model_dump(),
        },
    }
    answers = []
    changes = {
        "contact": False,
        "identification": None,
        "consultation": 15,
        "management": 7,
        "gross_errors": True,
    }
    for item in initial_checklist().criteria:
        value = changes.get(item.id, True)
        answers.append(
            {
                "criterion_id": item.id,
                "applicability": "not_applicable" if value is None else "applicable",
                "answer": value,
                "explanation": "Синтетическое обоснование модели.",
                "evidence": [
                    {"kind": "range", "start_message_id": "m0010", "end_message_id": "m0040"},
                    {"kind": "message", "message_id": "m0030"},
                ],
                "review_reasons": ["Синтетическая неопределённость."],
            }
        )
    prediction = {
        "case_id": case["case_id"],
        "transcript_version_id": case["transcript"]["id"],
        "checklist_version_id": case["checklist"]["id"],
        "error_code": None,
        "failure_provenance": None,
        "result": {
            "criterion_results": answers,
            "review_reasons": [],
            "provider": "openai",
            "model_requested": "gpt-6-luna",
            "model_reported": "gpt-6-luna",
            "usage": {"request_count": 1},
            "duration_ms": 10,
        },
    }
    return [record], {"cases": [case]}, {"cases": [prediction]}


def export(source):
    records, snapshots, predictions = source
    return build_submission(records=records, runs=[(snapshots, predictions)], team_name="Synthetic")


def test_official_codes_score_and_original_turns_without_mutating_sources(source):
    before = copy.deepcopy(source)
    document = export(source)
    row = document.results[0]
    assert row.conversation_id == "synthetic-original-id"
    assert row.status == "ok"  # Model uncertainty is not a processing failure.
    assert row.score.final_score == 75.63
    assert row.score.critical_flag is True
    assert {c.criterion_id for c in row.criteria} == set(ID_MAP.values())
    assert all(c.evidence_turns == [1, 2, 3, 4] for c in row.criteria)
    assert next(c for c in row.criteria if c.criterion_id == "identification").value is None
    assert source == before
    serialized = document.model_dump_json()
    assert PRIVATE not in serialized
    assert "transcript" not in serialized and "usage" not in serialized
    assert "review_reasons" not in serialized and "audio_url" not in serialized


def test_human_reference_answers_are_discarded(source):
    records, snapshots, predictions = source
    snapshots["annotation_source"] = "human"
    snapshots["cases"][0].update(
        criterion_results="HUMAN_REFERENCE_SECRET", annotator="PRIVATE_PERSON"
    )
    projected = project_snapshots(snapshots)
    document = build_submission(
        records=records, runs=[(projected, predictions)], team_name="Synthetic"
    )
    assert document.results[0].score.final_score == 75.63
    assert "HUMAN_REFERENCE_SECRET" not in document.model_dump_json()
    assert "PRIVATE_PERSON" not in document.model_dump_json()


def test_appendix_example_rounds_to_85_38(source):
    rows = source[2]["cases"][0]["result"]["criterion_results"]
    by_id = {row["criterion_id"]: row for row in rows}
    by_id["contact"]["answer"] = True
    by_id["needs"].update(applicability="not_applicable", answer=None)
    by_id["gross_errors"]["answer"] = False
    row = export(source).results[0]
    assert row.score.final_score == 85.38
    assert row.score.critical_flag is False


def test_missing_result_is_explicit_error_and_preserves_full_dataset_order(source):
    records = source[0]
    other = copy.deepcopy(records[0])
    other["conversation_id"] = "synthetic-missing"
    other["transcript"][0]["text"] += " another"
    records.insert(0, other)
    document = export(source)
    assert [row.conversation_id for row in document.results] == [
        "synthetic-missing",
        "synthetic-original-id",
    ]
    assert document.results[0].status == "error"
    assert document.results[0].error == "EVALUATION_NOT_AVAILABLE"
    assert document.results[0].criteria == [] and document.results[0].score is None


def test_failed_prediction_uses_only_safe_code_and_recorded_model(source):
    prediction = source[2]["cases"][0]
    prediction.update(
        result=None,
        error_code="AI_TIMEOUT",
        failure_provenance={
            "provider": "openai",
            "model_requested": "gpt-6-luna",
            "model_reported": None,
            "prompt_version": "synthetic",
            "duration_ms": 10,
            "usage": {"request_count": 1},
            "estimated_cost_usd": None,
        },
    )
    document = export(source)
    assert document.model.name == "gpt-6-luna"
    assert document.results[0].error == "AI_TIMEOUT"
    prediction["error_code"] = "PRIVATE_UNTRUSTED_ERROR"
    with pytest.raises(ValueError):
        export(source)


@pytest.mark.parametrize(
    "change",
    [
        "snapshot",
        "transcript",
        "rubric",
        "unknown",
        "duplicate",
        "provider",
        "evidence",
        "scale",
    ],
)
def test_incompatible_saved_data_is_rejected(source, change):
    records, snapshots, predictions = source
    case, prediction = snapshots["cases"][0], predictions["cases"][0]
    if change == "snapshot":
        prediction["transcript_version_id"] = str(uuid4())
    elif change == "transcript":
        case["transcript"]["messages"][0]["text"] += " changed"
    elif change == "rubric":
        case["checklist"]["criteria"][0]["weight"] = 20
    elif change == "unknown":
        prediction["case_id"] = "unknown"
    elif change == "duplicate":
        predictions["cases"].append(copy.deepcopy(prediction))
    elif change == "provider":
        prediction["result"]["provider"] = "synthetic-not-real-provider"
    elif change == "evidence":
        prediction["result"]["criterion_results"][0]["evidence"][0]["end_message_id"] = "m9999"
    elif change == "scale":
        prediction["result"]["criterion_results"][3]["answer"] = True
    with pytest.raises((ValueError, EvaluationError)):
        export(source)


def test_ambiguous_transcripts_and_overlapping_runs_are_rejected(source):
    records, snapshots, predictions = source
    with pytest.raises(SubmissionExportError, match="DUPLICATE_PREDICTION"):
        build_submission(
            records=records, runs=[(snapshots, predictions)] * 2, team_name="Synthetic"
        )
    another = copy.deepcopy(records[0])
    another["conversation_id"] = "different-id-same-content"
    records.append(another)
    with pytest.raises(SubmissionExportError, match="AMBIGUOUS_TRANSCRIPT"):
        export(source)


def test_source_ids_are_not_silently_normalized(source):
    source[0][0]["conversation_id"] = " synthetic-original-id "
    with pytest.raises(SubmissionExportError, match="INVALID_SOURCE_ID"):
        export(source)


@pytest.mark.parametrize(
    "change", ["total", "turn", "flag", "duplicate", "binary", "na", "coverage", "id_padding"]
)
def test_final_file_validation_checks_arithmetic_coverage_types_and_evidence(source, change):
    document = export(source).model_dump()
    row = document["results"][0]
    if change == "total":
        row["score"]["final_score"] = 75.62
    elif change == "turn":
        row["criteria"][0]["evidence_turns"] = [5]
    elif change == "flag":
        row["score"]["critical_flag"] = False
    elif change == "duplicate":
        row["criteria"][-1] = copy.deepcopy(row["criteria"][0])
    elif change == "binary":
        row["criteria"][0]["value"] = 1
    elif change == "na":
        row["criteria"][0]["value"] = None
    elif change == "coverage":
        row["conversation_id"] = "unrelated"
    elif change == "id_padding":
        row["conversation_id"] = " synthetic-original-id "
    with pytest.raises((ValueError, EvaluationError)):
        validate_submission(document, source[0])


def cli_inputs(source, tmp_path):
    records, snapshots, predictions = source
    records = copy.deepcopy(records)
    for i in range(1, 65):
        record = copy.deepcopy(records[0])
        record["conversation_id"] = f"synthetic-extra-{i}"
        record["transcript"][0]["text"] += f" extra-{i}"
        records.append(record)
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            {
                "isSuccess": True,
                "error": "",
                "data": {
                    "dataset_group_id": "DEV",
                    "total_records": 65,
                    "records": records,
                },
            }
        )
    )
    run = tmp_path / "run"
    run.mkdir()
    (run / "labels.frozen.json").write_text(json.dumps(snapshots))
    (run / "predictions.json").write_text(json.dumps(predictions))
    output = tmp_path / "results.json"
    args = ["--dataset", str(dataset), "--kind", "dev"]
    return args, run, output


def test_cli_export_and_check_are_offline_and_log_only_safe_summaries(
    source, tmp_path, caplog, capsys, monkeypatch
):
    import openai

    def forbidden(*args, **kwargs):
        raise AssertionError("No SDK client may be constructed")

    monkeypatch.setattr(openai, "AsyncOpenAI", forbidden)
    monkeypatch.setattr(openai, "OpenAI", forbidden)
    caplog.set_level(logging.INFO)
    args, run, output = cli_inputs(source, tmp_path)
    assert (
        cli.main(
            [
                *args,
                "--output",
                str(output),
                "--run-directory",
                str(run),
                "--team-name",
                "Synthetic",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {
        "status": "completed",
        "records": 65,
        "ok": 1,
        "errors": 64,
    }
    assert cli.main([*args, "--check", str(output)]) == 0
    assert "event=submission_export_started" in caplog.text
    assert "event=submission_export_completed records=65 errors=64" in caplog.text
    assert PRIVATE not in caplog.text and str(tmp_path) not in caplog.text
    assert cli.main([*args, "--kind", "prod", "--check", str(output)]) == 2
    assert "SUBMISSION_DATASET_SIZE_MISMATCH" in caplog.text


def test_cli_invalid_input_keeps_previous_output_and_hides_payload(
    source, tmp_path, caplog, capsys
):
    caplog.set_level(logging.INFO)
    args, run, output = cli_inputs(source, tmp_path)
    output.write_text("previous-output")
    (run / "predictions.json").write_text(
        '{"PRIVATE_API_KEY":"https://example.invalid/?sig=SECRET"'
    )
    assert (
        cli.main(
            [
                *args,
                "--output",
                str(output),
                "--run-directory",
                str(run),
                "--team-name",
                "Synthetic",
            ]
        )
        == 2
    )
    assert output.read_text() == "previous-output"
    assert capsys.readouterr().out == ""
    assert "event=submission_export_failed error=SUBMISSION_INVALID_INPUT" in caplog.text
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    assert "PRIVATE_API_KEY" not in caplog.text and "sig=" not in caplog.text
    assert "SECRET" not in caplog.text and str(tmp_path) not in caplog.text


def test_cli_filesystem_failure_is_safe_and_retains_previous_output(
    source, tmp_path, caplog, monkeypatch
):
    args, run, output = cli_inputs(source, tmp_path)
    output.write_text("previous-output")

    def fail(*args):
        raise OSError("PRIVATE_FILESYSTEM_SECRET")

    monkeypatch.setattr(cli.os, "replace", fail)
    assert (
        cli.main(
            [
                *args,
                "--output",
                str(output),
                "--run-directory",
                str(run),
                "--team-name",
                "Synthetic",
            ]
        )
        == 2
    )
    assert output.read_text() == "previous-output"
    assert not list(tmp_path.glob(".submission-*"))
    assert "PRIVATE_FILESYSTEM_SECRET" not in caplog.text


def test_cli_cannot_overwrite_its_immutable_sources(source, tmp_path, caplog):
    args, run, output = cli_inputs(source, tmp_path)
    for path in [Path(args[1]), run / "predictions.json", run / "labels.frozen.json"]:
        before = path.read_bytes()
        assert (
            cli.main(
                [
                    *args,
                    "--output",
                    str(path),
                    "--run-directory",
                    str(run),
                    "--team-name",
                    "Synthetic",
                ]
            )
            == 2
        )
        assert path.read_bytes() == before
    assert not output.exists()
    assert "SUBMISSION_OUTPUT_IS_SOURCE" in caplog.text
