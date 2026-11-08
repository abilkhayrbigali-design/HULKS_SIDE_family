"""Organizer Appendix Results 1.0, separate from the application's API contract."""

from typing import Annotated, Literal, get_args

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.evaluation.schemas import EvaluationSchema
from app.schemas.data import Number, Text

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


class SubmissionCriterion(EvaluationSchema):
    criterion_id: CriterionID
    value: StrictBool | Number | None
    rationale: Text
    evidence_turns: Annotated[list[Annotated[StrictInt, Field(ge=1)]], Field(min_length=1)]

    @model_validator(mode="after")
    def valid_answer(self):
        value = self.value
        if value is None:
            valid = self.criterion_id in {"discovery", "identification", "consultation", "closure"}
        elif self.criterion_id in {"consultation", "dialogue"}:
            choices = {0, 5, 10, 15, 20} if self.criterion_id == "consultation" else {0, 4, 7, 10}
            valid = type(value) in {int, float} and value in choices
        else:
            valid = type(value) is bool
        if not valid or len(set(self.evidence_turns)) != len(self.evidence_turns):
            raise ValueError("Invalid submission criterion")
        return self


class SubmissionScore(EvaluationSchema):
    final_score: Annotated[Number, Field(le=100)]
    critical_flag: StrictBool


class SubmissionSuccess(EvaluationSchema):
    conversation_id: Annotated[str, Field(min_length=1)]
    status: Literal["ok"]
    criteria: Annotated[list[SubmissionCriterion], Field(min_length=8, max_length=8)]
    score: SubmissionScore

    @model_validator(mode="after")
    def complete_criteria(self):
        if {row.criterion_id for row in self.criteria} != CRITERION_IDS:
            raise ValueError("All eight organizer criteria are required exactly once")
        critical = next(row.value for row in self.criteria if row.criterion_id == "critical")
        if critical is not self.score.critical_flag:
            raise ValueError("Critical flag mismatch")
        return self


class SubmissionError(EvaluationSchema):
    conversation_id: Annotated[str, Field(min_length=1)]
    status: Literal["error"]
    criteria: Annotated[list[SubmissionCriterion], Field(max_length=0)]
    score: None
    error: Text


class SubmissionModel(EvaluationSchema):
    mode: Literal["local", "external_api", "hybrid"]
    name: Text


class SubmissionDocument(EvaluationSchema):
    schema_version: Literal["1.0"]
    team_name: Text
    model: SubmissionModel
    results: Annotated[
        list[Annotated[SubmissionSuccess | SubmissionError, Field(discriminator="status")]],
        Field(min_length=1),
    ]

    @model_validator(mode="after")
    def unique_results(self):
        ids = [row.conversation_id for row in self.results]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate conversation IDs")
        return self
