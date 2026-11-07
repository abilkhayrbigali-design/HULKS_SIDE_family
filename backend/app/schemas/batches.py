"""Public batch inputs and persisted state responses."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.data import Schema
from app.schemas.evaluations import Status
from app.schemas.responses import Count


class BatchCreate(Schema):
    request_id: UUID
    conversation_ids: Annotated[list[UUID], Field(min_length=1, max_length=1000)]
    checklist_version_id: UUID

    @model_validator(mode="after")
    def unique_conversations(self):
        if len(self.conversation_ids) != len(set(self.conversation_ids)):
            raise ValueError("Duplicate conversation IDs")
        return self


class BatchItem(Schema):
    conversation_id: UUID
    transcript_version_id: UUID
    evaluation_id: UUID
    status: Status
    error_code: str | None


class EvaluationBatch(Schema):
    id: UUID
    request_id: UUID
    source_batch_id: UUID | None
    checklist_version_id: UUID
    created_at: datetime
    status: Literal["queued", "running", "completed", "completed_with_errors"]
    total: Count
    queued: Count
    running: Count
    completed: Count
    failed: Count
    items: Annotated[list[BatchItem], Field(min_length=1, max_length=1000)]
