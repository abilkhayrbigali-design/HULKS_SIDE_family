"""Validated public response models shared by runtime OpenAPI and HTTP routes."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.schemas.data import Channel, CriteriaInput, Language, Number, Schema, Text
from app.schemas.evaluations import Evidence, MessageID, Status

Count = Annotated[StrictInt, Field(ge=0)]
Score = Annotated[Number, Field(le=100)]


class Page[T](Schema):
    items: list[T]
    total: Count
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    offset: Count


class ImportSummary(Schema):
    group_id: Text
    received: Count
    created: Count
    new_versions: Count
    unchanged: Count
    conversation_ids: list[UUID]


class ChecklistSummary(Schema):
    id: UUID
    name: Text
    latest_version_id: UUID
    latest_version_number: Annotated[StrictInt, Field(ge=1)]


class ChecklistVersion(CriteriaInput):
    id: UUID
    checklist_id: UUID
    name: Text
    version_number: Annotated[StrictInt, Field(ge=1)]
    created_at: datetime


class ChecklistDetail(Schema):
    id: UUID
    name: Text
    current_version: ChecklistVersion
    versions: Annotated[list[ChecklistVersion], Field(min_length=1)]


class Message(Schema):
    id: MessageID
    position: Annotated[StrictInt, Field(ge=1)]
    timestamp: Annotated[str, Field(min_length=1, pattern=r"\S")]
    speaker: Literal["client", "operator", "bot", "system"]
    text: Annotated[str, Field(min_length=1, pattern=r"\S")]


class LatestEvaluation(Schema):
    id: UUID
    status: Status
    original_total: Score | None
    final_total: Score | None
    created_at: datetime


class ConversationSummary(Schema):
    id: UUID
    external_id: Text
    source: Literal["dataset", "upload"]
    group_id: Text
    language: Language
    channel: Channel
    current_transcript_version_id: UUID
    message_count: Annotated[StrictInt, Field(ge=1)]
    latest_evaluation: LatestEvaluation | None


class ConversationDetail(ConversationSummary):
    transcript_version_id: UUID
    audio_url: str | None
    messages: Annotated[list[Message], Field(min_length=1)]


class ProviderCriterionResult(Schema):
    criterion_id: Text
    applicability: Literal["applicable", "not_applicable"]
    answer: StrictBool | Number | None
    explanation: Text
    evidence: Annotated[list[Evidence], Field(min_length=1)]
    review_reasons: list[Text]


class CriterionAssessment(ProviderCriterionResult):
    weight: Number
    base_points: Number
    effective_weight: Number
    effective_points: Number
    review_required: StrictBool


class SectionAssessment(Schema):
    name: Text | None
    base_points: Number
    applicable_weight: Number
    total: Score | None


class Assessment(Schema):
    total: Score | None
    no_applicable_reason: Text | None
    gross_error: StrictBool | None
    criteria: Annotated[list[CriterionAssessment], Field(min_length=1)]
    sections: list[SectionAssessment]


class Usage(Schema):
    request_count: Count
    input_tokens: Count | None
    output_tokens: Count | None
    total_tokens: Count | None
    cached_input_tokens: Count | None
    reasoning_output_tokens: Count | None


class Provenance(Schema):
    provider: Text
    model_requested: Text
    model_reported: Text | None
    prompt_version: Text
    duration_ms: Count
    usage: Usage
    estimated_cost_usd: Number | None


class ErrorDetail(Schema):
    loc: list[str | int]
    type: Text


class ErrorBody(Schema):
    code: Text
    message: Text
    details: list[ErrorDetail]


class ErrorResponse(Schema):
    error: ErrorBody


class Evaluation(Schema):
    id: UUID
    conversation_id: UUID
    transcript_version_id: UUID
    checklist_version_id: UUID
    status: Status
    revision: Count
    created_at: datetime
    completed_at: datetime | None
    original: Assessment | None
    final: Assessment | None
    review_required: StrictBool
    review_reasons: list[Text]
    provenance: Provenance | None
    error: ErrorBody | None

    @model_validator(mode="after")
    def validate_state(self):
        if self.status == "completed":
            required = (self.original, self.final, self.provenance, self.completed_at)
            if any(v is None for v in required):
                raise ValueError("Completed evaluation requires result and provenance")
        elif self.original is not None or self.final is not None or self.revision != 0:
            raise ValueError("Unfinished evaluation cannot have a result")
        if (self.status == "failed") != (self.error is not None):
            raise ValueError("Failure requires an error")
        if (self.status in {"completed", "failed"}) != (self.completed_at is not None):
            raise ValueError("Only terminal evaluation has completed_at")
        return self


class AppealDecision(Schema):
    id: UUID
    appeal_id: UUID
    action: Literal["confirm", "override"]
    reason: Text
    expected_revision: Count
    created_at: datetime
    result: ProviderCriterionResult


class Appeal(Schema):
    id: UUID
    evaluation_id: UUID
    criterion_id: Text
    comment: Text
    status: Literal["open", "resolved"]
    base_revision: Count
    current_revision: Count
    created_at: datetime
    decision: AppealDecision | None
    original: CriterionAssessment
    current: CriterionAssessment


class DecisionResponse(Schema):
    appeal: Appeal
    evaluation: Evaluation
