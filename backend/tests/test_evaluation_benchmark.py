"""Synthetic vectors test benchmark arithmetic, never claim human-labelled model accuracy."""

import copy
import importlib.util
import json
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.benchmark import compare_predictions
from app.evaluation.errors import EvaluationError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data/fixtures/synthetic"


def documents():
    transcript = json.loads((FIXTURES / "transcript.snapshot.json").read_text())
    checklist = json.loads((FIXTURES / "checklist-version.response.json").read_text())
    provider = json.loads((FIXTURES / "provider.response.json").read_text())
    case = {
        "case_id": "synthetic-1",
        "split": "tune",
        "annotator": "synthetic-test-protocol",
        "transcript": transcript,
        "checklist": checklist,
        "criterion_results": copy.deepcopy(provider["criterion_results"]),
    }
    labels = {
        "annotation_source": "human",
        "dataset_id": "synthetic-protocol-test",
        "cases": [case],
    }
    predictions = {
        "cases": [
            {
                "case_id": case["case_id"],
                "transcript_version_id": transcript["id"],
                "checklist_version_id": checklist["id"],
                "result": provider,
                "error_code": None,
                "failure_provenance": None,
            }
        ]
    }
    return labels, predictions


def test_exact_metrics_and_null_undefined_precision():
    labels, predictions = documents()
    report = compare_predictions(labels, predictions, split="tune")
    overall = report["overall"]
    assert overall["cases"] == overall["completed"] == 1
    assert overall["criterion_exact_accuracy"] == overall["coverage"] == 1
    assert overall["total_mae"] == 0
    assert overall["na"]["recall"] == overall["na"]["precision"] == 1
    assert overall["flags"]["true_negative"] == 1
    assert overall["flags"]["precision"] is None
    assert overall["estimated_cost_usd"] is None
    assert report["official_ground_truth"] is False
    assert "synthetic-1" not in json.dumps(report)
    assert "Где найти справку" not in json.dumps(report, ensure_ascii=False)


def test_mixed_scale_na_and_flags_with_human_rows_in_any_order():
    labels, predictions = documents()
    labels["cases"][0]["criterion_results"].reverse()
    results = predictions["cases"][0]["result"]["criterion_results"]
    results[1]["answer"] = 10
    results[2].update(applicability="applicable", answer=False)
    results[3]["answer"] = True
    overall = compare_predictions(labels, predictions, split="tune")["overall"]
    assert overall["criterion_exact_accuracy"] == 0.25
    assert overall["criteria"]["navigation_custom"]["scale_normalized_mae"] == 0.5
    assert overall["na"]["false_negative"] == 1
    assert overall["flags"]["false_positive"] == 1
    assert overall["total_mae"] == 13.33


def test_failure_and_missing_do_not_improve_accuracy_or_fabricate_usage():
    labels, predictions = documents()
    labels["cases"][0]["criterion_results"][3]["answer"] = True
    predictions["cases"][0].update(result=None, error_code="AI_REFUSED")
    overall = compare_predictions(labels, predictions, split="tune")["overall"]
    assert overall["criterion_exact_accuracy"] == 0
    assert overall["failed"] == 1
    assert overall["coverage"] == 0
    assert overall["flags"]["false_negative"] == 1
    assert overall["na"]["false_negative"] == 1
    assert overall["total_mae"] is None
    assert overall["usage"]["unrecorded_usage_cases"] == 1
    assert overall["usage"]["total_tokens"] is None
    missing = compare_predictions(labels, {"cases": []}, split="tune")["overall"]
    assert missing["missing"] == 1
    assert missing["criterion_exact_accuracy"] == 0
    assert missing["criteria"]["greeting_custom"]["missing"] == 1


@pytest.mark.parametrize("failed", [False, True])
def test_missing_prediction_keeps_split_usage_partially_unknown(failed):
    labels, predictions = documents()
    missing = copy.deepcopy(labels["cases"][0])
    missing["case_id"] = "synthetic-missing"
    missing["transcript"].update(
        id="00000000-0000-4000-8000-000000000030",
        conversation_id="00000000-0000-4000-8000-000000000031",
    )
    labels["cases"].append(missing)
    usage = {
        "request_count": 1,
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "cached_input_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    prediction = predictions["cases"][0]
    prediction["result"]["usage"] = usage
    if failed:
        prediction.update(
            result=None,
            error_code="AI_INCOMPLETE",
            failure_provenance={
                "provider": "openai",
                "model_requested": "gpt-6-luna",
                "model_reported": "gpt-6-luna",
                "prompt_version": "synthetic",
                "duration_ms": 3000,
                "usage": usage,
                "estimated_cost_usd": 0.01,
            },
        )
    report = compare_predictions(labels, predictions, split="tune")
    for aggregate in (
        report["overall"],
        report["languages"]["RU"],
        report["channels"]["agent chat"],
    ):
        assert aggregate["cases"] == 2
        assert aggregate["missing"] == 1
        assert aggregate["usage"]["request_count_known"] == 1
        assert aggregate["usage"]["unrecorded_usage_cases"] == 1
        assert all(aggregate["usage"][field] is None for field in usage if field != "request_count")
        assert aggregate["estimated_cost_usd"] is None


def test_explicit_holdout_split_and_no_conversation_leakage():
    labels, predictions = documents()
    holdout = copy.deepcopy(labels["cases"][0])
    holdout["case_id"] = "synthetic-holdout"
    holdout["split"] = "holdout"
    holdout["transcript"].update(
        id="00000000-0000-4000-8000-000000000030",
        conversation_id="00000000-0000-4000-8000-000000000031",
        language="KZ",
        channel="voice call",
    )
    labels["cases"].append(holdout)
    report = compare_predictions(labels, predictions, split="holdout")
    assert report["overall"]["cases"] == 1
    assert report["overall"]["missing"] == 1
    assert set(report["languages"]) == {"KZ"}
    assert set(report["channels"]) == {"voice call"}
    labels["cases"][1]["transcript"]["conversation_id"] = labels["cases"][0]["transcript"][
        "conversation_id"
    ]
    with pytest.raises(ValidationError):
        compare_predictions(labels, predictions, split="holdout")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda labels, pred: pred["cases"].append(copy.deepcopy(pred["cases"][0])),
        lambda labels, pred: pred["cases"][0].update(case_id="unknown"),
        lambda labels, pred: pred["cases"][0].update(
            transcript_version_id="00000000-0000-4000-8000-000000000099"
        ),
        lambda labels, pred: pred["cases"][0]["result"]["criterion_results"][0].update(answer=1),
        lambda labels, pred: labels.update(annotation_source="ai"),
    ],
)
def test_invalid_inputs_are_rejected(mutate):
    labels, predictions = documents()
    mutate(labels, predictions)
    with pytest.raises((ValueError, EvaluationError)):
        compare_predictions(labels, predictions, split="tune")


def test_failed_paid_attempts_are_included_in_usage_and_latency():
    labels, predictions = documents()
    predictions["cases"][0].update(
        result=None,
        error_code="AI_INCOMPLETE",
        failure_provenance={
            "provider": "openai",
            "model_requested": "gpt-6-luna",
            "model_reported": "gpt-6-luna",
            "prompt_version": "synthetic",
            "duration_ms": 3000,
            "usage": {
                "request_count": 3,
                "input_tokens": 900,
                "output_tokens": 100,
                "total_tokens": 1000,
                "cached_input_tokens": 400,
                "reasoning_output_tokens": 80,
            },
            "estimated_cost_usd": None,
        },
    )
    overall = compare_predictions(labels, predictions, split="tune")["overall"]
    assert overall["usage"]["request_count_known"] == 3
    assert overall["usage"]["total_tokens"] == 1000
    assert overall["mean_duration_ms"] == 3000


def test_cli_produces_json_and_safe_failure_without_printing_private_input(
    tmp_path, capsys, caplog
):
    spec = importlib.util.spec_from_file_location("evaluate_dev", ROOT / "tools/evaluate_dev.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    labels, predictions = documents()
    label_path, prediction_path = tmp_path / "labels.json", tmp_path / "predictions.json"
    label_path.write_text(json.dumps(labels))
    prediction_path.write_text(json.dumps(predictions))
    args = ["--labels", str(label_path), "--predictions", str(prediction_path), "--split", "tune"]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["overall"]["completed"] == 1
    label_path.write_text("SYNTHETIC_PRIVATE_SENTINEL { invalid")
    with caplog.at_level(logging.ERROR, logger="cqa.benchmark"):
        assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "SYNTHETIC_PRIVATE_SENTINEL" not in captured.err + caplog.text
    assert "BENCHMARK_INVALID_INPUT" in caplog.text


@pytest.mark.parametrize("code", ["INTERRUPTED", "EVALUATION_INTERNAL_ERROR"])
def test_worker_owned_safe_failure_codes_are_comparable(code):
    labels, predictions = documents()
    predictions["cases"][0].update(result=None, error_code=code)
    report = compare_predictions(labels, predictions, split="tune")
    assert report["overall"]["failed"] == 1
    assert report["overall"]["criterion_exact_accuracy"] == 0


def test_completed_prediction_without_recorded_attempt_is_rejected():
    labels, predictions = documents()
    predictions["cases"][0]["result"]["usage"]["request_count"] = 0
    with pytest.raises(ValidationError):
        compare_predictions(labels, predictions, split="tune")
