"""Export immutable initial results without invoking AI or exposing raw failures."""

import logging

from sqlalchemy import select

from app.evaluation.errors import MESSAGES, EvaluationError
from app.evaluation.scoring import calculate_assessment
from app.models.batches import EvaluationBatch
from app.models.data import ChecklistVersion, Conversation, Message
from app.schemas.submissions import SubmissionDocument, SubmissionError, SubmissionSuccess
from app.services import batches
from app.services.errors import ServiceError, require
from app.services.evaluations import RESULT_FIELDS
from app.services.seed import initial_checklist

logger = logging.getLogger("cqa.submissions")
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
SAFE_FAILURES = {*MESSAGES, "INTERRUPTED", "EVALUATION_INTERNAL_ERROR"}


def _semantic(criteria):
    return {
        item["id"]: {key: value for key, value in item.items() if key not in {"name", "section"}}
        for item in criteria
    }


def _error(external_id, code):
    return SubmissionError(
        conversation_id=external_id, status="error", criteria=[], score=None, error=code
    )


def _success(session, evaluation, external_id, checklist):
    original = evaluation.original
    messages = [
        {key: getattr(message, key) for key in ("id", "position", "timestamp", "speaker", "text")}
        for message in session.scalars(
            select(Message)
            .where(Message.transcript_version_id == evaluation.transcript_version_id)
            .order_by(Message.position)
        )
    ]
    # Reuse the single scorer to validate old/corrupt persisted answers and evidence.
    recalculated = calculate_assessment(
        criteria=checklist.criteria,
        results=[{key: item[key] for key in RESULT_FIELDS} for item in original["criteria"]],
        messages=messages,
    )
    if (recalculated["total"], recalculated["gross_error"]) != (
        original["total"],
        original["gross_error"],
    ):
        raise ValueError("Invalid saved score")
    by_id = {item["criterion_id"]: item for item in recalculated["criteria"]}
    positions = {message["id"]: message["position"] for message in messages}
    criteria = []
    for id_, submission_id in ID_MAP.items():
        criterion = by_id[id_]
        turns = set()
        for evidence in criterion["evidence"]:
            if evidence["kind"] == "message":
                turns.add(positions[evidence["message_id"]])
            else:
                start = positions[evidence["start_message_id"]]
                end = positions[evidence["end_message_id"]]
                turns.update(
                    position for position in positions.values() if start <= position <= end
                )
        criteria.append(
            {
                "criterion_id": submission_id,
                "value": criterion["answer"],
                "rationale": criterion["explanation"],
                "evidence_turns": sorted(turns),
            }
        )
    return SubmissionSuccess(
        conversation_id=external_id,
        status="ok",
        criteria=criteria,
        score={"final_score": original["total"], "critical_flag": original["gross_error"]},
    )


def _inputs(session, batch_id):
    batch = require(session.get(EvaluationBatch, str(batch_id)))
    evaluations = batches.members(session, batch.id)
    external_ids = dict(
        session.execute(
            select(Conversation.id, Conversation.external_id).where(
                Conversation.id.in_([item.conversation_id for item in evaluations])
            )
        ).all()
    )
    return batch, evaluations, external_ids


def _coverage(payload, evaluations, external_ids):
    expected = set(payload.expected_conversation_ids)
    actual = set(external_ids.values())
    return {
        "expected_count": len(expected),
        "batch_count": len(evaluations),
        "missing_count": len(expected - actual),
        "extra_count": len(actual - expected),
        "matches": expected == actual and len(actual) == len(evaluations),
    }


def preflight(session, payload):
    _, evaluations, external_ids = _inputs(session, payload.batch_id)
    return _coverage(payload, evaluations, external_ids)


def create(session, payload):
    batch, evaluations, external_ids = _inputs(session, payload.batch_id)
    if len(set(external_ids.values())) != len(evaluations):
        logger.warning(
            "event=submission_export_rejected error=SUBMISSION_DUPLICATE_CONVERSATION_ID"
        )
        raise ServiceError(
            409,
            "SUBMISSION_DUPLICATE_CONVERSATION_ID",
            "Пакет содержит повторяющиеся исходные ID из разных наборов",
        )
    coverage = _coverage(payload, evaluations, external_ids)
    if not coverage["matches"]:
        logger.warning(
            "event=submission_export_rejected error=SUBMISSION_SCOPE_MISMATCH "
            "records=%d missing=%d extra=%d",
            coverage["batch_count"],
            coverage["missing_count"],
            coverage["extra_count"],
        )
        raise ServiceError(
            409,
            "SUBMISSION_SCOPE_MISMATCH",
            f"Состав не совпадает: отсутствует {coverage['missing_count']}, "
            f"лишних {coverage['extra_count']}",
        )
    checklist = require(session.get(ChecklistVersion, batch.checklist_version_id))
    if _semantic(checklist.criteria) != _semantic(initial_checklist().model_dump()["criteria"]):
        logger.warning("event=submission_export_rejected error=SUBMISSION_CHECKLIST_INCOMPATIBLE")
        raise ServiceError(
            409,
            "SUBMISSION_CHECKLIST_INCOMPATIBLE",
            "Для сдачи требуется исходный чек-лист организаторов",
        )
    results, models = [], set()
    invalid = 0
    for evaluation in evaluations:
        if (
            evaluation.provenance
            and evaluation.provenance.get("usage", {}).get("request_count", 0) > 0
        ):
            models.add(
                evaluation.provenance.get("model_reported")
                or evaluation.provenance["model_requested"]
            )
        external_id = external_ids[evaluation.conversation_id]
        if evaluation.status in {"queued", "running"}:
            row = _error(external_id, "EVALUATION_PENDING")
        elif evaluation.status == "failed":
            code = evaluation.error["code"]
            row = _error(external_id, code if code in SAFE_FAILURES else "EVALUATION_FAILED")
        elif evaluation.review_required:
            row = _error(external_id, "EVALUATION_REVIEW_REQUIRED")
        else:
            try:
                row = _success(session, evaluation, external_id, checklist)
            except (KeyError, TypeError, ValueError, EvaluationError):
                # Corrupt/old stored data cannot silently produce a valid-looking submission.
                row = _error(external_id, "SUBMISSION_INVALID_RESULT")
                invalid += 1
        results.append(row)
    if invalid:
        logger.warning(
            "event=submission_result_rejected error=SUBMISSION_INVALID_RESULT records=%d", invalid
        )
    result = SubmissionDocument(
        schema_version="1.0",
        team_name=payload.team_name,
        model={"mode": "external_api", "name": ", ".join(sorted(models)) if models else "not_run"},
        results=results,
    )
    session.info["cqa_submission_exported"] = (
        len(results),
        sum(item.status == "error" for item in results),
    )
    return result
