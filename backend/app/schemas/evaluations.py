"""Strict HTTP inputs; semantic answers are checked against saved snapshots."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.schemas.data import Number, Schema, Text

Status = Literal["queued", "running", "completed", "failed"]
AppealStatus = Literal["open", "resolved"]
MessageID = Annotated[str, Field(pattern=r"^m[0-9]{4,}$")]


class EvaluationCreate(Schema):
    conversation_id: UUID
    checklist_version_id: UUID


class AppealCreate(Schema):
    criterion_id: Text
    comment: Text


class MessageEvidence(Schema):
    kind: Literal["message"]
    message_id: MessageID


class RangeEvidence(Schema):
    kind: Literal["range"]
    start_message_id: MessageID
    end_message_id: MessageID


Evidence = Annotated[MessageEvidence | RangeEvidence, Field(discriminator="kind")]


class ConfirmDecision(Schema):
    action: Literal["confirm"]
    reason: Text
    expected_revision: Annotated[StrictInt, Field(ge=0)]


class OverrideDecision(Schema):
    action: Literal["override"]
    reason: Text
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    applicability: Literal["applicable", "not_applicable"]
    answer: StrictBool | Number | None
    evidence: Annotated[list[Evidence], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_applicability(self):
        if (self.applicability == "not_applicable") != (self.answer is None):
            raise ValueError("N/A requires null; applicable requires an answer")
        return self


DecisionCreate = Annotated[ConfirmDecision | OverrideDecision, Field(discriminator="action")]
