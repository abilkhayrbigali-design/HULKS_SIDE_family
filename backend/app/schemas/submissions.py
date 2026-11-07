"""Strict organizer Appendix Results 1.0, independent of internal API payloads."""

from typing import Annotated, Literal, get_args
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, StringConstraints, model_validator

from app.schemas.data import Number, Schema, Text

CriterionID = Literal[
    "contact",
    "discovery",
    "identification",
    "consultation",
    "empathy",
    "dialogue",
    "closure",
    "critical",
]
CRITERION_IDS = set(get_args(CriterionID))


class SubmissionExportRequest(Schema):
    batch_id: UUID
    team_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


class SubmissionCriterion(Schema):
    criterion_id: CriterionID
    value: StrictBool | Number | None
    rationale: Text
    evidence_turns: Annotated[list[Annotated[StrictInt, Field(ge=1)]], Field(min_length=1)]

    @model_validator(mode="after")
    def valid_value(self):
        id_, value = self.criterion_id, self.value
        if value is None:
            valid = id_ in {"discovery", "identification", "consultation", "closure"}
        elif id_ in {"consultation", "dialogue"}:
            choices = {0, 5, 10, 15, 20} if id_ == "consultation" else {0, 4, 7, 10}
            valid = type(value) in {int, float} and value in choices
        else:
            valid = type(value) is bool
        if not valid or len(set(self.evidence_turns)) != len(self.evidence_turns):
            raise ValueError("Invalid submission criterion")
        return self


class SubmissionScore(Schema):
    final_score: Annotated[Number, Field(le=100)]
    critical_flag: StrictBool


class SubmissionSuccess(Schema):
    conversation_id: Text
    status: Literal["ok"]
    criteria: Annotated[list[SubmissionCriterion], Field(min_length=8, max_length=8)]
    score: SubmissionScore

    @model_validator(mode="after")
    def complete_criteria(self):
        if {item.criterion_id for item in self.criteria} != CRITERION_IDS:
            raise ValueError("Submission requires all eight criteria")
        critical = next(item.value for item in self.criteria if item.criterion_id == "critical")
        if critical is not self.score.critical_flag:
            raise ValueError("Critical flag mismatch")
        return self


class SubmissionError(Schema):
    conversation_id: Text
    status: Literal["error"]
    criteria: Annotated[list[SubmissionCriterion], Field(max_length=0)]
    score: None
    error: Text


class SubmissionModel(Schema):
    mode: Literal["external_api"]
    name: Text


class SubmissionDocument(Schema):
    schema_version: Literal["1.0"]
    team_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    model: SubmissionModel
    results: Annotated[
        list[Annotated[SubmissionSuccess | SubmissionError, Field(discriminator="status")]],
        Field(min_length=1, max_length=1000),
    ]

    @model_validator(mode="after")
    def unique_results(self):
        ids = [item.conversation_id for item in self.results]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate submission conversation IDs")
        return self
