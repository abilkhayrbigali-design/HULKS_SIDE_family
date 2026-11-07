"""Official wire rules are distinct from internal checklist IDs and JSON types."""

from copy import deepcopy

import pytest
from test_contracts import fixture, validator


@pytest.mark.parametrize(
    ("criterion_id", "value"),
    [("contact", None), ("consultation", True), ("dialogue", False), ("critical", 0)],
)
def test_submission_rejects_incompatible_value_types(criterion_id, value):
    document = fixture("batches/submission.response.json")
    criterion = next(
        item for item in document["results"][0]["criteria"] if item["criterion_id"] == criterion_id
    )
    criterion["value"] = value
    assert not validator("SubmissionDocument").is_valid(document)


def test_submission_requires_all_eight_distinct_official_ids():
    document = fixture("batches/submission.response.json")
    criteria = document["results"][0]["criteria"]
    criteria[-1] = deepcopy(criteria[0])
    assert not validator("SubmissionDocument").is_valid(document)


def test_submission_error_cannot_include_a_success_score_or_criteria():
    document = fixture("batches/submission.response.json")
    document["results"][1]["score"] = {"final_score": 0, "critical_flag": False}
    assert not validator("SubmissionDocument").is_valid(document)


def test_submission_turns_use_one_based_positions_and_nested_score():
    document = fixture("batches/submission.response.json")
    document["results"][0]["criteria"][0]["evidence_turns"] = [0]
    assert not validator("SubmissionDocument").is_valid(document)
    document = fixture("batches/submission.response.json")
    document["results"][0]["final_score"] = document["results"][0].pop("score")["final_score"]
    assert not validator("SubmissionDocument").is_valid(document)


def test_batch_request_rejects_duplicate_conversations():
    request = fixture("batches/batch.create.json")
    request["conversation_ids"].append(request["conversation_ids"][0])
    assert not validator("EvaluationBatchCreate").is_valid(request)
