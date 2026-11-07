from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.models.data import Checklist, Conversation, TranscriptVersion
from app.schemas import responses
from app.schemas.data import (
    Channel,
    ChecklistCreate,
    ChecklistUpdate,
    DatasetImport,
    ImportRequest,
    Language,
)
from app.services import checklists, conversations, datasets

router = APIRouter(prefix="/api/v1")


def session(request: Request):
    with request.app.state.session_factory() as db:
        with db.begin():
            yield db


DB = Annotated[object, Depends(session, scope="function")]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def page(db, statement, limit, offset, convert):
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    return dict(
        items=[convert(row) for row in db.scalars(statement.limit(limit).offset(offset))],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/checklists", response_model=responses.Page[responses.ChecklistSummary])
def list_checklists(db: DB, limit: Limit = 50, offset: Offset = 0):
    return page(db, select(Checklist).order_by(Checklist.id), limit, offset, checklists.metadata)


@router.post("/checklists", status_code=201, response_model=responses.ChecklistVersion)
def create_checklist(payload: ChecklistCreate, db: DB):
    return checklists.create(db, payload)


@router.get("/checklists/{id}", response_model=responses.ChecklistDetail)
def get_checklist(id: str, db: DB):
    return checklists.detail(db, id)


@router.get("/checklist-versions/{id}", response_model=responses.ChecklistVersion)
def get_version(id: str, db: DB):
    return checklists.get_version(db, id)


@router.post(
    "/checklists/{id}/versions",
    status_code=201,
    response_model=responses.ChecklistVersion,
)
def create_version(id: str, payload: ChecklistUpdate, db: DB):
    return checklists.add_version(db, id, payload)


@router.post("/conversations/import", response_model=responses.ImportSummary)
def import_upload(payload: ImportRequest, db: DB):
    return conversations.import_records(db, payload)


@router.post("/datasets/import", response_model=responses.ImportSummary)
def import_dataset(payload: DatasetImport, request: Request):
    # Fetch and validate before opening any DB transaction.
    records = datasets.fetch_records(
        request.app.state.dataset_url,
        payload.group_id,
        getattr(request.app.state, "dataset_transport", None),
    )
    with request.app.state.session_factory.begin() as db:
        return conversations.import_records(
            db, records, source="dataset", group_id=payload.group_id
        )


@router.get("/conversations", response_model=responses.Page[responses.ConversationSummary])
def list_conversations(
    db: DB,
    language: Language | None = None,
    channel: Channel | None = None,
    group_id: str | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    statement = select(Conversation).join(
        TranscriptVersion,
        Conversation.current_transcript_version_id == TranscriptVersion.id,
    )
    for value, column in (
        (language, TranscriptVersion.language),
        (channel, TranscriptVersion.channel),
        (group_id, Conversation.group_id),
    ):
        if value is not None:
            statement = statement.where(column == value)
    return page(
        db,
        statement.order_by(Conversation.id),
        limit,
        offset,
        lambda row: conversations.summary(db, row),
    )


@router.get("/conversations/{id}", response_model=responses.ConversationDetail)
def get_conversation(id: str, db: DB, transcript_version_id: str | None = None):
    return conversations.detail(db, id, transcript_version_id)
