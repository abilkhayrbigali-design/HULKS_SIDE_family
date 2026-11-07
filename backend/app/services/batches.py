"""Atomic batch creation and retry; worker remains the only evaluation executor."""

from uuid import uuid4

from sqlalchemy import select

from app.models.batches import EvaluationBatch, EvaluationBatchItem
from app.models.data import ChecklistVersion, Conversation
from app.models.evaluations import Evaluation
from app.services.errors import ServiceError, require
from app.services.evaluations import _serialize_writes


def members(session, batch_id):
    return session.scalars(
        select(Evaluation)
        .join(EvaluationBatchItem, EvaluationBatchItem.evaluation_id == Evaluation.id)
        .where(EvaluationBatchItem.batch_id == batch_id)
        .order_by(EvaluationBatchItem.position)
    ).all()


def snapshot(session, row):
    items = [
        {
            "conversation_id": item.conversation_id,
            "transcript_version_id": item.transcript_version_id,
            "evaluation_id": item.id,
            "status": item.status,
            "error_code": None if item.error is None else item.error["code"],
        }
        for item in members(session, row.id)
    ]
    counts = {
        status: sum(i["status"] == status for i in items)
        for status in ("queued", "running", "completed", "failed")
    }
    if counts["queued"] == len(items):
        status = "queued"
    elif counts["queued"] or counts["running"]:
        status = "running"
    else:
        status = "completed_with_errors" if counts["failed"] else "completed"
    return {
        **{
            key: getattr(row, key)
            for key in ("id", "request_id", "source_batch_id", "checklist_version_id", "created_at")
        },
        "status": status,
        "total": len(items),
        **counts,
        "items": items,
    }


def get(session, id_):
    return snapshot(session, require(session.get(EvaluationBatch, str(id_))))


def _save(session, *, request_id, checklist_id, snapshots, source_batch_id=None):
    row = EvaluationBatch(
        request_id=request_id,
        checklist_version_id=checklist_id,
        source_batch_id=source_batch_id,
    )
    session.add(row)
    session.flush()
    for position, (conversation_id, transcript_id) in enumerate(snapshots, 1):
        evaluation = Evaluation(
            conversation_id=conversation_id,
            transcript_version_id=transcript_id,
            checklist_version_id=checklist_id,
        )
        session.add(evaluation)
        session.flush()
        session.add(
            EvaluationBatchItem(batch_id=row.id, evaluation_id=evaluation.id, position=position)
        )
    session.flush()
    session.info["cqa_batch_saved"] = len(snapshots)
    return snapshot(session, row)


def create(session, payload):
    _serialize_writes(session)
    # A batch is a set; sorting makes idempotent requests independent of UI ordering.
    ids = sorted(str(id_) for id_ in payload.conversation_ids)
    existing = session.scalar(
        select(EvaluationBatch).where(EvaluationBatch.request_id == str(payload.request_id))
    )
    if existing is not None:
        same_ids = sorted(item.conversation_id for item in members(session, existing.id)) == ids
        if existing.checklist_version_id != str(payload.checklist_version_id) or not same_ids:
            raise ServiceError(409, "IDEMPOTENCY_CONFLICT", "ID запроса уже использован")
        return snapshot(session, existing)
    require(session.get(ChecklistVersion, str(payload.checklist_version_id)))
    conversations = session.scalars(select(Conversation).where(Conversation.id.in_(ids))).all()
    if len(conversations) != len(ids):
        raise ServiceError(404, "NOT_FOUND", "Диалог не найден")
    versions = {row.id: row.current_transcript_version_id for row in conversations}
    return _save(
        session,
        request_id=str(payload.request_id),
        checklist_id=str(payload.checklist_version_id),
        snapshots=[(id_, versions[id_]) for id_ in ids],
    )


def retry_failed(session, id_):
    _serialize_writes(session)
    source = require(session.get(EvaluationBatch, str(id_)))
    existing = session.scalar(
        select(EvaluationBatch).where(EvaluationBatch.source_batch_id == source.id)
    )
    if existing is not None:
        return snapshot(session, existing)
    items = members(session, source.id)
    if any(item.status in {"queued", "running"} for item in items):
        raise ServiceError(409, "BATCH_NOT_FINISHED", "Дождитесь завершения пакета")
    failed = [item for item in items if item.status == "failed"]
    if not failed:
        raise ServiceError(409, "BATCH_NO_FAILED_ITEMS", "В пакете нет ошибок для повтора")
    return _save(
        session,
        request_id=str(uuid4()),
        checklist_id=source.checklist_version_id,
        snapshots=[(item.conversation_id, item.transcript_version_id) for item in failed],
        source_batch_id=source.id,
    )
