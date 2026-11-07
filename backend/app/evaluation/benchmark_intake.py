"""Offline intake of human-owned labels and saved evaluations against frozen snapshots."""

import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from app.evaluation.benchmark import HumanLabels, Predictions, compare_predictions
from app.evaluation.schemas import ChecklistSnapshot, CriterionResult, TranscriptSnapshot
from app.evaluation.scoring import calculate_assessment
from app.schemas.responses import Evaluation


class IntakeError(ValueError):
    """Developer-owned diagnostic; never contains an input value or filesystem path."""


def _require(condition, code):
    if not condition:
        raise IntakeError(code)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "BENCHMARK_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def frozen_cases(package: Path, split: str) -> tuple[str, dict]:
    """Read the existing package, checking the selected split without changing any file."""
    _require(split in {"tune", "holdout"}, "BENCHMARK_INVALID_SPLIT")
    manifest = read_json(package / "manifest.json")
    draft = read_json(package / "labels.draft.json")
    checklist = read_json(package / "checklist.snapshot.json")
    _require(
        manifest["draft_sha256"] == _digest(draft)
        and manifest["checklist_snapshot_sha256"] == _digest(checklist),
        "BENCHMARK_PACKAGE_CHANGED",
    )
    ChecklistSnapshot.model_validate(checklist)
    _require(
        draft["annotation_source"] == manifest["state"] == "pending_human"
        and draft["dataset_id"] == manifest["dataset_id"],
        "BENCHMARK_INVALID_PACKAGE",
    )
    cases = draft["cases"]
    by_id = {case["case_id"]: case for case in cases}
    _require(
        len(by_id) == len(cases) == manifest["cases"]
        and {case["case_id"]: case["split"] for case in cases} == manifest["split_assignments"]
        and dict(Counter(case["split"] for case in cases)) == manifest["split_counts"],
        "BENCHMARK_INVALID_PACKAGE",
    )
    conversations = set()
    for case in cases:
        transcript = TranscriptSnapshot.model_validate(case["transcript"])
        _require(
            _canonical(case["checklist"]) == _canonical(checklist)
            and case["split"] in {"tune", "holdout"}
            and transcript.conversation_id not in conversations,
            "BENCHMARK_INVALID_PACKAGE",
        )
        conversations.add(transcript.conversation_id)
    grouped = []
    for group in manifest["groups"]:
        members = group["cases"]
        _require(
            bool(members)
            and all(member in by_id for member in members)
            and len({by_id[member]["split"] for member in members}) == 1,
            "BENCHMARK_SPLIT_LEAKAGE",
        )
        grouped.extend(members)
    _require(
        len(grouped) == len(set(grouped)) and set(grouped) == set(by_id),
        "BENCHMARK_INVALID_PACKAGE",
    )
    selected = {key: case for key, case in by_id.items() if case["split"] == split}
    _require(bool(selected), "BENCHMARK_EMPTY_SPLIT")
    return draft["dataset_id"], selected


def merge_labels(package: Path, parts: dict[str, Path], *, split: str) -> HumanLabels:
    """Require every frozen case in this split, and every criterion, exactly once."""
    dataset_id, frozen = frozen_cases(package, split)
    _require(set(parts) == {"RU", "KZ", "EN"}, "BENCHMARK_INVALID_LANGUAGE_PARTS")
    merged = []
    for language, path in parts.items():
        part = read_json(path)
        _require(
            isinstance(part, dict)
            and set(part) == {"annotation_source", "dataset_id", "cases"}
            and part["annotation_source"] == "human"
            and part["dataset_id"] == dataset_id,
            "BENCHMARK_HUMAN_LABELS_REQUIRED",
        )
        cases = part["cases"]
        _require(isinstance(cases, list), "BENCHMARK_INVALID_LABELS")
        expected = {
            key for key, case in frozen.items() if case["transcript"]["language"] == language
        }
        ids = [case["case_id"] for case in cases]
        _require(
            len(ids) == len(set(ids)) and set(ids) == expected,
            "BENCHMARK_LABEL_COVERAGE_MISMATCH",
        )
        for case in cases:
            reference = frozen[case["case_id"]]
            _require(
                all(
                    _canonical(case[key]) == _canonical(reference[key])
                    for key in ("split", "transcript", "checklist")
                ),
                "BENCHMARK_SNAPSHOT_MISMATCH",
            )
        merged.extend(cases)
    labels = HumanLabels.model_validate(
        {"annotation_source": "human", "dataset_id": dataset_id, "cases": merged}
    )
    _require(
        all(case.annotator.casefold() != "pending_human" for case in labels.cases),
        "BENCHMARK_HUMAN_LABELS_REQUIRED",
    )
    # Reuse the benchmark's complete evidence/type/rubric validation, with no predictions.
    compare_predictions(labels, {"cases": []}, split=split)
    return labels


def saved_predictions(package: Path, source: Path, *, split: str) -> Predictions:
    """Convert terminal Evaluation resources; omitted cases remain missing in the benchmark."""
    _, frozen = frozen_cases(package, split)
    source_data = read_json(source)
    _require(
        isinstance(source_data, dict) and set(source_data) == {"cases"},
        "BENCHMARK_INVALID_EVALUATIONS",
    )
    _require(isinstance(source_data["cases"], list), "BENCHMARK_INVALID_EVALUATIONS")
    output = []
    for item in source_data["cases"]:
        _require(
            isinstance(item, dict) and set(item) == {"case_id", "evaluation"},
            "BENCHMARK_INVALID_EVALUATIONS",
        )
        _require(item["case_id"] in frozen, "BENCHMARK_UNKNOWN_CASE")
        reference = frozen[item["case_id"]]
        evaluation = Evaluation.model_validate(item["evaluation"])
        _require(
            str(evaluation.transcript_version_id) == reference["transcript"]["id"]
            and str(evaluation.checklist_version_id) == reference["checklist"]["id"]
            and str(evaluation.conversation_id) == reference["transcript"]["conversation_id"],
            "BENCHMARK_SNAPSHOT_MISMATCH",
        )
        _require(evaluation.status in {"completed", "failed"}, "BENCHMARK_NONTERMINAL_EVALUATION")
        provenance = (
            evaluation.provenance.model_dump(mode="json") if evaluation.provenance else None
        )
        result = None
        if evaluation.status == "completed":
            results = [
                row.model_dump(mode="json", include=set(CriterionResult.model_fields))
                for row in evaluation.original.criteria
            ]
            assessment = calculate_assessment(
                criteria=reference["checklist"]["criteria"],
                results=results,
                messages=reference["transcript"]["messages"],
            )
            _require(
                assessment == evaluation.original.model_dump(mode="json"),
                "BENCHMARK_INVALID_ORIGINAL",
            )
            result = {
                key: value
                for key, value in provenance.items()
                if key not in {"prompt_version", "estimated_cost_usd"}
            }
            result.update(criterion_results=results, review_reasons=evaluation.review_reasons)
        output.append(
            {
                "case_id": item["case_id"],
                "transcript_version_id": evaluation.transcript_version_id,
                "checklist_version_id": evaluation.checklist_version_id,
                "result": result,
                "error_code": evaluation.error.code if evaluation.error else None,
                "failure_provenance": provenance if evaluation.status == "failed" else None,
            }
        )
    return Predictions.model_validate({"cases": output})


def write_private_new(path: Path, document: dict):
    """Publish a complete 600 file atomically, refusing existing targets including symlinks."""
    raw = json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
    # No implicit directory creation: the caller explicitly chooses an existing private directory.
    fd, temporary = tempfile.mkstemp(prefix=".benchmark-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            raise IntakeError("BENCHMARK_OUTPUT_EXISTS") from None
    finally:
        os.unlink(temporary)
