"""Offline export of saved AI predictions; human reference answers are never used."""

import json
from decimal import Decimal

from pydantic import Field, model_validator

from app.evaluation.benchmark import Predictions
from app.evaluation.schemas import ChecklistSnapshot, EvaluationSchema, TranscriptSnapshot
from app.evaluation.scoring import calculate_assessment
from app.schemas.data import ImportRequest, Text
from app.schemas.submissions import SubmissionDocument
from app.services.seed import initial_checklist

ID_MAP = {
    "contact": "contact",
    "needs": "discovery",
    "identification": "identification",
    "consultation": "consultation",
    "empathy": "empathy",
    "management": "dialogue",
    "closing": "closure",
    "gross_errors": "critical",
}


class SubmissionExportError(ValueError):
    """Only developer-defined safe codes cross the CLI error boundary."""


class SavedCase(EvaluationSchema):
    case_id: Text
    transcript: TranscriptSnapshot
    checklist: ChecklistSnapshot


class SavedSnapshots(EvaluationSchema):
    cases: list[SavedCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self):
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate snapshot case IDs")
        return self


def project_snapshots(document):
    """Accept frozen benchmark files, discarding annotations before validation/export."""
    return SavedSnapshots(
        cases=[
            {key: case[key] for key in ("case_id", "transcript", "checklist")}
            for case in document["cases"]
        ]
    )


def _content(channel, language, messages):
    return json.dumps(
        [channel, language, [(m.timestamp, m.speaker, m.text) for m in messages]],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _rubric(criteria):
    return {c.id: c.model_dump(exclude={"name", "section"}) for c in criteria}


def _records(records):
    original_ids = [
        r["conversation_id"] if isinstance(r, dict) else r.conversation_id for r in records
    ]
    parsed = ImportRequest(records=records).records
    if original_ids != [r.conversation_id for r in parsed]:
        raise SubmissionExportError("SUBMISSION_INVALID_SOURCE_ID")
    return parsed


def validate_submission(document, records):
    """Check exact dataset coverage, evidence bounds and Decimal scores offline."""
    document = SubmissionDocument.model_validate(document)
    records = _records(records)
    by_id = {r.conversation_id: r for r in records}
    if {row.conversation_id for row in document.results} != set(by_id):
        raise SubmissionExportError("SUBMISSION_COVERAGE_MISMATCH")
    reverse = {external: internal for internal, external in ID_MAP.items()}
    for row in document.results:
        if row.status == "error":
            continue
        record = by_id[row.conversation_id]
        messages = [
            {"id": f"m{i:04d}", "position": i, **m.model_dump()}
            for i, m in enumerate(record.transcript, 1)
        ]
        results = []
        for item in row.criteria:
            if any(turn > len(messages) for turn in item.evidence_turns):
                raise SubmissionExportError("SUBMISSION_INVALID_EVIDENCE")
            results.append(
                {
                    "criterion_id": reverse[item.criterion_id],
                    "applicability": "not_applicable" if item.value is None else "applicable",
                    "answer": item.value,
                    "explanation": item.rationale,
                    "evidence": [
                        {"kind": "message", "message_id": f"m{turn:04d}"}
                        for turn in item.evidence_turns
                    ],
                    "review_reasons": [],
                }
            )
        score = calculate_assessment(
            criteria=initial_checklist().criteria,
            results=results,
            messages=messages,
        )
        if Decimal(str(row.score.final_score)) != Decimal(str(score["total"])):
            raise SubmissionExportError("SUBMISSION_SCORE_MISMATCH")
    return document


def build_submission(*, records, runs, team_name):
    """Join complete immutable transcripts, verify snapshots, then export model answers."""
    records = _records(records)
    content = {_content(r.channel, r.language, r.transcript): r.conversation_id for r in records}
    if len(content) != len(records):
        raise SubmissionExportError("SUBMISSION_AMBIGUOUS_TRANSCRIPT")
    official = _rubric(initial_checklist().criteria)
    outcomes, models = {}, set()
    for snapshots, predictions in runs:
        snapshots = SavedSnapshots.model_validate(snapshots)
        predictions = Predictions.model_validate(predictions)
        cases = {case.case_id: case for case in snapshots.cases}
        if any(p.case_id not in cases for p in predictions.cases):
            raise SubmissionExportError("SUBMISSION_UNKNOWN_PREDICTION")
        predicted = {p.case_id: p for p in predictions.cases}
        for case in snapshots.cases:
            t = case.transcript
            external_id = content.get(_content(t.channel, t.language, t.messages))
            if external_id is None:
                raise SubmissionExportError("SUBMISSION_DATASET_MISMATCH")
            if external_id in outcomes:
                raise SubmissionExportError("SUBMISSION_DUPLICATE_PREDICTION")
            if _rubric(case.checklist.criteria) != official:
                raise SubmissionExportError("SUBMISSION_CHECKLIST_INCOMPATIBLE")
            prediction = predicted.get(case.case_id)
            row = {
                "conversation_id": external_id,
                "status": "error",
                "criteria": [],
                "score": None,
                "error": "EVALUATION_NOT_AVAILABLE",
            }
            if prediction is not None:
                if (prediction.transcript_version_id, prediction.checklist_version_id) != (
                    t.id,
                    case.checklist.id,
                ):
                    raise SubmissionExportError("SUBMISSION_SNAPSHOT_MISMATCH")
                result = prediction.result
                provenance = result or prediction.failure_provenance
                if provenance:
                    if provenance.provider != "openai":
                        raise SubmissionExportError("SUBMISSION_UNSUPPORTED_PROVIDER")
                    models.add(provenance.model_reported or provenance.model_requested)
                if result is None:
                    row["error"] = prediction.error_code
                else:
                    assessment = calculate_assessment(
                        criteria=case.checklist.criteria,
                        results=result.criterion_results,
                        messages=t.messages,
                    )
                    positions = {m.id: i for i, m in enumerate(t.messages, 1)}
                    criteria = []
                    for item in assessment["criteria"]:
                        turns = set()
                        for evidence in item["evidence"]:
                            if evidence["kind"] == "message":
                                turns.add(positions[evidence["message_id"]])
                            else:
                                start = positions[evidence["start_message_id"]]
                                end = positions[evidence["end_message_id"]]
                                turns.update(range(start, end + 1))
                        criteria.append(
                            {
                                "criterion_id": ID_MAP[item["criterion_id"]],
                                "value": item["answer"],
                                "rationale": item["explanation"],
                                "evidence_turns": sorted(turns),
                            }
                        )
                    row = {
                        "conversation_id": external_id,
                        "status": "ok",
                        "criteria": criteria,
                        "score": {
                            "final_score": assessment["total"],
                            "critical_flag": assessment["gross_error"],
                        },
                    }
            outcomes[external_id] = row
    if not models:
        raise SubmissionExportError("SUBMISSION_MODEL_UNRECORDED")
    rows = [
        outcomes.get(
            r.conversation_id,
            {
                "conversation_id": r.conversation_id,
                "status": "error",
                "criteria": [],
                "score": None,
                "error": "EVALUATION_NOT_AVAILABLE",
            },
        )
        for r in records
    ]
    return validate_submission(
        {
            "schema_version": "1.0",
            "team_name": team_name,
            "model": {"mode": "external_api", "name": ", ".join(sorted(models))},
            "results": rows,
        },
        records,
    )
