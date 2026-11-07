"""Persisted batch HTTP operations over the regular evaluation worker."""

from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.routes.data import DB, Limit, Offset, page
from app.models.batches import EvaluationBatch
from app.schemas.batches import BatchCreate
from app.schemas.batches import EvaluationBatch as BatchResponse
from app.schemas.responses import Page
from app.services import batches
from app.services.errors import ServiceError

router = APIRouter(prefix="/api/v1")


def require_ai(request):
    # Test injection is Python-only, never a user-selectable mock success mode.
    if not getattr(request.app.state, "evaluation_pipeline_injected", False):
        if not request.app.state.settings.openai_api_key.get_secret_value().strip():
            raise ServiceError(
                503, "AI_NOT_CONFIGURED", "Добавьте OPENAI_API_KEY для запуска AI-оценки"
            )


@router.post("/evaluation-batches", status_code=202, response_model=BatchResponse)
def create_batch(payload: BatchCreate, request: Request, db: DB):
    require_ai(request)
    return batches.create(db, payload)


@router.get("/evaluation-batches", response_model=Page[BatchResponse])
def list_batches(db: DB, limit: Limit = 50, offset: Offset = 0):
    return page(
        db,
        select(EvaluationBatch).order_by(EvaluationBatch.created_at.desc(), EvaluationBatch.id),
        limit,
        offset,
        lambda row: batches.snapshot(db, row),
    )


@router.get("/evaluation-batches/{id}", response_model=BatchResponse)
def get_batch(id: UUID, db: DB):
    return batches.get(db, id)


@router.post("/evaluation-batches/{id}/retry-failed", status_code=202, response_model=BatchResponse)
def retry_batch(id: UUID, request: Request, db: DB):
    require_ai(request)
    return batches.retry_failed(db, id)

