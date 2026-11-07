"""Short DB transactions for snapshots, terminal results and appeal history."""

import logging
from copy import deepcopy

from sqlalchemy import select, text, update

from app.models.data import ChecklistVersion, Conversation, now
from app.models.evaluations import Appeal, AppealDecision, CriterionResult, Evaluation
from app.services import checklists, conversations
from app.services.errors import ServiceError, require

logger = logging.getLogger("cqa.evaluation")
RESULT_FIELDS = (
    "criterion_id",
    "applicability",
    "answer",
    "explanation",
    "evidence",
    "review_reasons",
)
EVALUATION_FIELDS = (
    "id",
    "conversation_id",
    "transcript_version_id",
    "checklist_version_id",
    "status",
    "revision",
    "created_at",
    "completed_at",
    "original",
    "final",
    "review_required",
    "review_reasons",
    "provenance",
    "error",
)


def snapshot(row):
    return {key: deepcopy(getattr(row, key)) for key in EVALUATION_FIELDS}


def create(session, payload):
    conversation = require(session.get(Conversation, str(payload.conversation_id)))
    require(session.get(ChecklistVersion, str(payload.checklist_version_id)))
    row = Evaluation(
        conversation_id=conversation.id,
        transcript_version_id=conversation.current_transcript_version_id,
        checklist_version_id=str(payload.checklist_version_id),
    )
    session.add(row)
    session.flush()
    session.info["cqa_evaluation_queued"] = session.info.get("cqa_evaluation_queued", 0) + 1
    return snapshot(row)


def get(session, id_):
    return snapshot(require(session.get(Evaluation, str(id_))))


def load_inputs(session, row):
    conversation = conversations.detail(session, row.conversation_id, row.transcript_version_id)
    transcript = {
        "id": row.transcript_version_id,
        "conversation_id": row.conversation_id,
        **{key: conversation[key] for key in ("language", "channel", "messages")},
    }
    return transcript, checklists.get_version(session, row.checklist_version_id)


def claim(session):
    row = session.scalar(
        select(Evaluation)
        .where(Evaluation.status == "queued")
        .order_by(Evaluation.created_at, Evaluation.id)
        .limit(1)
    )
    if row is None:
        return None
    changed = session.execute(
        update(Evaluation)
        .where(Evaluation.id == row.id, Evaluation.status == "queued")
        .values(status="running")
    )
    if changed.rowcount != 1:
        return None
    transcript, checklist = load_inputs(session, row)
    return row.id, transcript, checklist


def complete(session, id_, result):
    row = require(session.get(Evaluation, id_))
    if row.status != "running":
        raise ServiceError(409, "STATE_CONFLICT", "Состояние оценки изменилось")
    row.status, row.completed_at = "completed", now()
    row.original = deepcopy(result.assessment)
    row.final = deepcopy(result.assessment)
    row.provenance = deepcopy(result.provenance)
    row.review_required = result.review_required
    row.review_reasons = list(result.review_reasons)
    for criterion in result.assessment["criteria"]:
        session.add(
            CriterionResult(
                evaluation_id=id_,
                criterion_id=criterion["criterion_id"],
                result={key: deepcopy(criterion[key]) for key in RESULT_FIELDS},
            )
        )
    session.flush()


def fail(session, id_, code, message, provenance=None):
    # A terminal result is never overwritten, including by a shutdown racing completion.
    session.execute(
        update(Evaluation)
        .where(Evaluation.id == id_, Evaluation.status == "running")
        .values(
            status="failed",
            completed_at=now(),
            error={"code": code, "message": message, "details": []},
            provenance=provenance,
        )
    )


def recover(session):
    changed = session.execute(
        update(Evaluation)
        .where(Evaluation.status == "running")
        .values(
            status="failed",
            completed_at=now(),
            error={
                "code": "INTERRUPTED",
                "message": "Оценка прервана. Создайте новый запуск.",
                "details": [],
            },
        )
    )
    return changed.rowcount


def _serialize_writes(session):
    if session.bind.dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))


def _criterion(assessment, id_):
    return next((c for c in assessment["criteria"] if c["criterion_id"] == id_), None)


def appeal_snapshot(session, row):
    evaluation = require(session.get(Evaluation, row.evaluation_id))
    decision = session.scalar(select(AppealDecision).where(AppealDecision.appeal_id == row.id))
    return {
        **{
            key: getattr(row, key)
            for key in (
                "id",
                "evaluation_id",
                "criterion_id",
                "comment",
                "status",
                "base_revision",
                "created_at",
            )
        },
        "current_revision": evaluation.revision,
        "original": deepcopy(_criterion(evaluation.original, row.criterion_id)),
        "current": deepcopy(_criterion(evaluation.final, row.criterion_id)),
        "decision": None
        if decision is None
        else {
            key: deepcopy(getattr(decision, key))
            for key in (
                "id",
                "appeal_id",
                "action",
                "reason",
                "expected_revision",
                "created_at",
                "result",
            )
        },
    }


def get_appeal(session, id_):
    return appeal_snapshot(session, require(session.get(Appeal, str(id_))))


def create_appeal(session, id_, payload):
    _serialize_writes(session)
    evaluation = require(session.get(Evaluation, str(id_)))
    if evaluation.status != "completed":
        raise ServiceError(409, "EVALUATION_NOT_COMPLETED", "Оценка ещё не завершена")
    if _criterion(evaluation.original, payload.criterion_id) is None:
        raise ServiceError(422, "INVALID_CRITERION", "Критерий отсутствует в оценке")
    existing = session.scalar(
        select(Appeal.id).where(
            Appeal.evaluation_id == evaluation.id,
            Appeal.criterion_id == payload.criterion_id,
            Appeal.status == "open",
        )
    )
    if existing:
        logger.warning("event=appeal_open_conflict error=APPEAL_ALREADY_OPEN")
        raise ServiceError(409, "APPEAL_ALREADY_OPEN", "По критерию уже открыта апелляция")
    row = Appeal(
        evaluation_id=evaluation.id,
        criterion_id=payload.criterion_id,
        comment=payload.comment,
        base_revision=evaluation.revision,
    )
    session.add(row)
    session.flush()
    session.info["cqa_appeal_created"] = 1
    return appeal_snapshot(session, row)


def decide(session, id_, payload):
    # Serialize short decisions before reading revision or current result.
    _serialize_writes(session)
    appeal = require(session.get(Appeal, str(id_)))
    evaluation = require(session.get(Evaluation, appeal.evaluation_id))
    if appeal.status != "open" or evaluation.revision != payload.expected_revision:
        logger.warning("event=appeal_decision_conflict error=REVISION_CONFLICT")
        raise ServiceError(409, "REVISION_CONFLICT", "Решение или оценка уже изменились")
    accepted = {
        key: deepcopy(_criterion(evaluation.final, appeal.criterion_id)[key])
        for key in RESULT_FIELDS
    }
    if payload.action == "override":
        accepted.update(
            applicability=payload.applicability,
            answer=payload.answer,
            evidence=[e.model_dump() for e in payload.evidence],
            explanation=payload.reason,
            review_reasons=[],
        )
    inputs, checklist = load_inputs(session, evaluation)
    results = [
        {key: deepcopy(item[key]) for key in RESULT_FIELDS} for item in evaluation.final["criteria"]
    ]
    results = [
        accepted if item["criterion_id"] == appeal.criterion_id else item for item in results
    ]
    from app.evaluation.errors import EvaluationError
    from app.evaluation.scoring import calculate_assessment

    try:
        final = calculate_assessment(
            criteria=checklist["criteria"],
            results=results,
            messages=inputs["messages"],
        )
    except EvaluationError:
        raise ServiceError(
            422, "INVALID_DECISION", "Ответ или доказательства не соответствуют версии"
        ) from None
    decision = AppealDecision(
        appeal_id=appeal.id,
        action=payload.action,
        reason=payload.reason,
        expected_revision=payload.expected_revision,
        result=accepted,
    )
    session.add(decision)
    appeal.status = "resolved"
    evaluation.final = final
    evaluation.revision += 1
    # Run-level warnings describe the original AI operation and remain auditable.
    # Criterion warnings on final are recomputed by the shared scoring function.
    session.flush()
    session.info["cqa_appeal_decided"] = 1
    return {"appeal": appeal_snapshot(session, appeal), "evaluation": snapshot(evaluation)}
