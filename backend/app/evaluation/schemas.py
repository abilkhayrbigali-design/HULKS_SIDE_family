"""Strict snapshots/results at the SQL-free evaluation boundary."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from app.schemas.data import CriteriaInput, Number, Text


class EvaluationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


MessageID = Annotated[str, StringConstraints(pattern=r"^m[0-9]{4,}$")]


class Message(EvaluationSchema):
    id: MessageID
    position: Annotated[StrictInt, Field(ge=1)]
    timestamp: str
    speaker: Literal["client", "operator", "bot", "system"]
    text: Annotated[str, Field(min_length=1)]


class TranscriptSnapshot(EvaluationSchema):
    id: UUID
    conversation_id: UUID
    language: Literal["RU", "KZ", "EN"]
    channel: Literal["agent chat", "voice call"]
    messages: Annotated[list[Message], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_ordered_messages(self):
        ids = [item.id for item in self.messages]
        positions = [item.position for item in self.messages]
        if len(set(ids)) != len(ids) or positions != sorted(set(positions)):
            raise ValueError("Messages require unique IDs and increasing positions")
        return self


class ChecklistSnapshot(CriteriaInput):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    id: UUID
    checklist_id: UUID
    name: Text
    version_number: Annotated[StrictInt, Field(ge=1)]
    created_at: str


class MessageEvidence(EvaluationSchema):
    kind: Literal["message"]
    message_id: MessageID


class RangeEvidence(EvaluationSchema):
    kind: Literal["range"]
    start_message_id: MessageID
    end_message_id: MessageID


Evidence = Annotated[MessageEvidence | RangeEvidence, Field(discriminator="kind")]


class CriterionResult(EvaluationSchema):
    criterion_id: Text
    applicability: Literal["applicable", "not_applicable"]
    answer: StrictBool | Number | None
    explanation: Text
    evidence: Annotated[list[Evidence], Field(min_length=1)]
    review_reasons: list[Text]


class ModelResult(EvaluationSchema):
    criterion_results: Annotated[list[CriterionResult], Field(min_length=1)]
    review_reasons: list[Text]


class Usage(EvaluationSchema):
    request_count: Annotated[StrictInt, Field(ge=0)]
    input_tokens: Annotated[StrictInt, Field(ge=0)] | None = None
    output_tokens: Annotated[StrictInt, Field(ge=0)] | None = None
    total_tokens: Annotated[StrictInt, Field(ge=0)] | None = None
    cached_input_tokens: Annotated[StrictInt, Field(ge=0)] | None = None
    reasoning_output_tokens: Annotated[StrictInt, Field(ge=0)] | None = None


class ProviderResult(ModelResult):
    provider: Text
    model_requested: Text
    model_reported: Text | None
    usage: Usage
    duration_ms: Annotated[StrictInt, Field(ge=0)]
