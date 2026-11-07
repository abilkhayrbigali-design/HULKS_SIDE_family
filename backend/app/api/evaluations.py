"""Evaluation and appeal HTTP routes; startup lifecycle is owned by integration."""

from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.routes.data import DB, Limit, Offset, page
from app.models.evaluations import Appeal, Evaluation
from app.schemas.evaluations import (
    AppealCreate,
    AppealStatus,
    DecisionCreate,
    EvaluationCreate,
    Status,
)
from app.services import evaluations
from app.services.errors import ServiceError

router = APIRouter(prefix="/api/v1")


@router.post("/evaluations", status_code=202)
def create_evaluation(payload: EvaluationCreate, request: Request, db: DB):
    # Injection is available only to Python tests, never through a product setting/HTTP flag.
    if not getattr(request.app.state, "evaluation_pipeline_injected", False):
        settings = request.app.state.settings
        if not settings.openai_api_key.get_secret_value().strip():
            raise ServiceError(
                503, "AI_NOT_CONFIGURED", "Добавьте OPENAI_API_KEY для запуска AI-оценки"
            )
    return evaluations.create(db, payload)


@router.get("/evaluations")
def list_evaluations(
    db: DB,
    conversation_id: UUID | None = None,
    status: Status | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    statement = select(Evaluation)
    if conversation_id is not None:
        statement = statement.where(Evaluation.conversation_id == str(conversation_id))
    if status is not None:
        statement = statement.where(Evaluation.status == status)
    return page(
        db,
        statement.order_by(Evaluation.created_at.desc(), Evaluation.id),
        limit,
        offset,
        evaluations.snapshot,
    )


@router.get("/evaluations/{id}")
def get_evaluation(id: UUID, db: DB):
    return evaluations.get(db, id)


@router.post("/evaluations/{id}/appeals", status_code=201)
def create_appeal(id: UUID, payload: AppealCreate, db: DB):
    return evaluations.create_appeal(db, id, payload)


@router.get("/appeals")
def list_appeals(
    db: DB,
    status: AppealStatus | None = None,
    evaluation_id: UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    statement = select(Appeal)
    if status is not None:
        statement = statement.where(Appeal.status == status)
    if evaluation_id is not None:
        statement = statement.where(Appeal.evaluation_id == str(evaluation_id))
    return page(
        db,
        statement.order_by(Appeal.created_at.desc(), Appeal.id),
        limit,
        offset,
        lambda row: evaluations.appeal_snapshot(db, row),
    )


@router.get("/appeals/{id}")
def get_appeal(id: UUID, db: DB):
    return evaluations.get_appeal(db, id)


@router.post("/appeals/{id}/decisions")
def decide_appeal(id: UUID, payload: DecisionCreate, db: DB):
    return evaluations.decide(db, id, payload)


def install_evaluation_api(app):
    app.include_router(router)
