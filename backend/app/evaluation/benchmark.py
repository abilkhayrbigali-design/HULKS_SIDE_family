"""Offline comparison against externally supplied human annotations; never calls a model."""

from collections import defaultdict
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictInt, model_validator

from app.evaluation.errors import MESSAGES, EvaluationError
from app.evaluation.schemas import (
    ChecklistSnapshot,
    CriterionResult,
    EvaluationSchema,
    ProviderResult,
    TranscriptSnapshot,
    Usage,
)
from app.evaluation.scoring import calculate_assessment
from app.schemas.data import Number, Text


class LabelCase(EvaluationSchema):
    case_id: Text
    split: Literal["tune", "holdout"]
    annotator: Text
    transcript: TranscriptSnapshot
    checklist: ChecklistSnapshot
    criterion_results: list[CriterionResult]


class HumanLabels(EvaluationSchema):
    annotation_source: Literal["human"]
    dataset_id: Text
    cases: Annotated[list[LabelCase], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_cases_and_no_split_leakage(self):
        ids = [case.case_id for case in self.cases]
        conversations = [case.transcript.conversation_id for case in self.cases]
        if len(set(ids)) != len(ids) or len(set(conversations)) != len(conversations):
            raise ValueError("Case IDs and conversations must be unique across annotation splits")
        # A benchmark compares a frozen rubric; edited rubrics use a separate report.
        first = self.cases[0].checklist.model_dump(mode="json")
        if any(case.checklist.model_dump(mode="json") != first for case in self.cases):
            raise ValueError("All annotations must use one immutable checklist snapshot")
        return self


class FailureProvenance(EvaluationSchema):
    provider: Text
    model_requested: Text
    model_reported: Text | None
    prompt_version: Text
    duration_ms: Annotated[StrictInt, Field(ge=0)]
    usage: Usage
    estimated_cost_usd: Number | None


class PredictionCase(EvaluationSchema):
    case_id: Text
    transcript_version_id: UUID
    checklist_version_id: UUID
    result: ProviderResult | None
    error_code: Text | None
    failure_provenance: FailureProvenance | None

    @model_validator(mode="after")
    def valid_outcome(self):
        if self.result is not None:
            if self.result.usage.request_count < 1:
                raise ValueError("Completed prediction requires at least one recorded attempt")
            if self.error_code is not None or self.failure_provenance is not None:
                raise ValueError("Successful prediction cannot contain a failure")
        elif self.error_code not in {*MESSAGES, "INTERRUPTED", "EVALUATION_INTERNAL_ERROR"}:
            raise ValueError("Failed prediction requires a safe evaluation error code")
        return self


class Predictions(EvaluationSchema):
    cases: list[PredictionCase]

    @model_validator(mode="after")
    def unique_cases(self):
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate prediction IDs")
        return self


def _mean(values):
    return float(sum(values, Decimal(0)) / len(values)) if values else None


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _confusion():
    return {"true_positive": 0, "false_positive": 0, "false_negative": 0, "true_negative": 0}


def _observe(confusion, truth: bool, predicted: bool | None):
    if predicted is None:
        # Missing predictions count against recall; they do not manufacture true negatives.
        if truth:
            confusion["false_negative"] += 1
        return
    key = ("true_" if predicted == truth else "false_") + ("positive" if predicted else "negative")
    confusion[key] += 1


def _finish_confusion(confusion):
    return {
        **confusion,
        "precision": _ratio(
            confusion["true_positive"], confusion["true_positive"] + confusion["false_positive"]
        ),
        "recall": _ratio(
            confusion["true_positive"], confusion["true_positive"] + confusion["false_negative"]
        ),
    }


def _aggregate(cases, predictions) -> dict:
    exact = 0
    count = 0
    completed = 0
    failed = 0
    missing = 0
    total_errors = []
    null_mismatches = 0
    both_null = 0
    criteria = {}
    na = _confusion()
    flags = _confusion()
    usage_rows = []
    durations = []
    costs = []
    for case in cases:
        predicted = predictions.get(case.case_id)
        expected = calculate_assessment(
            criteria=case.checklist.criteria,
            results=case.criterion_results,
            messages=case.transcript.messages,
        )
        actual = None
        if predicted is None:
            missing += 1
        elif predicted.result is None:
            failed += 1
            if predicted.failure_provenance:
                provenance = predicted.failure_provenance
                usage_rows.append(provenance.usage)
                durations.append(Decimal(provenance.duration_ms))
                costs.append(provenance.estimated_cost_usd)
            else:
                usage_rows.append(None)
                costs.append(None)
        else:
            completed += 1
            actual = calculate_assessment(
                criteria=case.checklist.criteria,
                results=predicted.result.criterion_results,
                messages=case.transcript.messages,
            )
            usage_rows.append(predicted.result.usage)
            durations.append(Decimal(predicted.result.duration_ms))
            costs.append(None)  # ProviderResult has no confirmed pricing metadata.
        actual_rows = {item["criterion_id"]: item for item in actual["criteria"]} if actual else {}
        truths = {item.criterion_id: item for item in case.criterion_results}
        for definition in case.checklist.criteria:
            truth = truths[definition.id]
            value = actual_rows.get(definition.id)
            metric = criteria.setdefault(
                definition.id, {"count": 0, "exact": 0, "missing": 0, "normalized_errors": []}
            )
            count += 1
            metric["count"] += 1
            if value is None:
                metric["missing"] += 1
            else:
                matched = value["applicability"] == truth.applicability and (
                    type(value["answer"]) is type(truth.answer)
                    and value["answer"] == truth.answer
                    or type(value["answer"]) in {int, float}
                    and type(truth.answer) in {int, float}
                    and Decimal(str(value["answer"])) == Decimal(str(truth.answer))
                )
                exact += int(matched)
                metric["exact"] += int(matched)
                if (
                    definition.type == "scale"
                    and truth.applicability == "applicable"
                    and value["applicability"] == "applicable"
                ):
                    maximum = max(Decimal(str(step.value)) for step in definition.scale)
                    metric["normalized_errors"].append(
                        abs(Decimal(str(value["answer"])) - Decimal(str(truth.answer))) / maximum
                    )
            _observe(
                na,
                truth.applicability == "not_applicable",
                value["applicability"] == "not_applicable" if value else None,
            )
            if definition.type == "flag":
                _observe(flags, truth.answer, value["answer"] if value else None)
        if actual:
            expected_total, actual_total = expected["total"], actual["total"]
            if expected_total is None or actual_total is None:
                both_null += int(expected_total is None and actual_total is None)
                null_mismatches += int((expected_total is None) != (actual_total is None))
            else:
                total_errors.append(abs(Decimal(str(expected_total)) - Decimal(str(actual_total))))
    token_fields = [
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "reasoning_output_tokens",
    ]
    usage = {
        "request_count_known": sum(item.request_count for item in usage_rows if item),
        "unrecorded_usage_cases": sum(item is None for item in usage_rows),
    }
    for field in token_fields:
        values = [getattr(item, field) if item else None for item in usage_rows]
        usage[field] = (
            sum(values) if values and all(value is not None for value in values) else None
        )
    return {
        "cases": len(cases),
        "completed": completed,
        "failed": failed,
        "missing": missing,
        "coverage": _ratio(completed, len(cases)),
        "criterion_exact_accuracy": _ratio(exact, count),
        "criterion_count": count,
        "total_mae": _mean(total_errors),
        "total_numeric_pairs": len(total_errors),
        "total_both_null": both_null,
        "total_null_mismatches": null_mismatches,
        "na": _finish_confusion(na),
        "flags": _finish_confusion(flags),
        "criteria": {
            id_: {
                "count": metric["count"],
                "missing": metric["missing"],
                "exact_accuracy": _ratio(metric["exact"], metric["count"]),
                "scale_normalized_mae": _mean(metric["normalized_errors"]),
                "scale_numeric_pairs": len(metric["normalized_errors"]),
            }
            for id_, metric in sorted(criteria.items())
        },
        "usage": usage,
        "mean_duration_ms": _mean(durations),
        "duration_cases": len(durations),
        "estimated_cost_usd": float(sum(Decimal(str(value)) for value in costs))
        if costs and all(value is not None for value in costs)
        else None,
    }


def compare_predictions(labels: HumanLabels | dict, predictions: Predictions | dict, *, split: str):
    """Validate all inputs before selecting a split; unknown/duplicate cases are rejected."""
    labels = HumanLabels.model_validate(labels)
    predictions = Predictions.model_validate(predictions)
    if split not in {"tune", "holdout"}:
        raise ValueError("An explicit annotation split is required")
    known = {case.case_id: case for case in labels.cases}
    predicted = {case.case_id: case for case in predictions.cases}
    for case in labels.cases:
        calculate_assessment(
            criteria=case.checklist.criteria,
            results=case.criterion_results,
            messages=case.transcript.messages,
        )
    for item in predictions.cases:
        case = known.get(item.case_id)
        if case is None or (item.transcript_version_id, item.checklist_version_id) != (
            case.transcript.id,
            case.checklist.id,
        ):
            raise EvaluationError("AI_INVALID_SNAPSHOT")
        if item.result:
            calculate_assessment(
                criteria=case.checklist.criteria,
                results=item.result.criterion_results,
                messages=case.transcript.messages,
            )
    selected = [case for case in labels.cases if case.split == split]
    if not selected:
        raise ValueError("The selected annotation split is empty")
    groups = defaultdict(list)
    channels = defaultdict(list)
    for case in selected:
        groups[case.transcript.language].append(case)
        channels[case.transcript.channel].append(case)
    return {
        "report_version": "1",
        "annotation_source": "external_human_asserted",
        "split": split,
        "official_ground_truth": False,
        "overall": _aggregate(selected, predicted),
        "languages": {
            language: _aggregate(cases, predicted) for language, cases in sorted(groups.items())
        },
        "channels": {
            channel: _aggregate(cases, predicted) for channel, cases in sorted(channels.items())
        },
    }
