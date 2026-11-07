"""Synthetic scoring cases, not expert labels or model accuracy evidence."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.evaluation.errors import EvaluationError
from app.evaluation.scoring import calculate_assessment
from app.services.seed import initial_checklist

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data/fixtures/synthetic"
MESSAGES = json.loads((FIXTURES / "transcript.snapshot.json").read_text())["messages"]


def answers(criteria):
    return [
        {
            "criterion_id": item.id,
            "applicability": "applicable",
            "answer": False
            if item.type == "flag"
            else max(s.value for s in item.scale)
            if item.type == "scale"
            else True,
            "explanation": "Синтетическое арифметическое ожидание.",
            "evidence": [{"kind": "range", "start_message_id": "m0001", "end_message_id": "m0004"}],
            "review_reasons": [],
        }
        for item in criteria
    ]


@pytest.mark.parametrize(
    "changes, expected, gross",
    [
        ({}, 100, False),
        ({"contact": False}, 90, False),
        ({"management": 7}, 95.5, False),
        ({"identification": None}, 100, False),
        ({"identification": None, "contact": False}, 87.5, False),
        ({"gross_errors": True}, 100, True),
    ],
)
def test_documented_scoring_cases(changes, expected, gross):
    criteria = initial_checklist().criteria
    results = answers(criteria)
    for result in results:
        if result["criterion_id"] in changes:
            result["answer"] = changes[result["criterion_id"]]
            if result["answer"] is None:
                result["applicability"] = "not_applicable"
    original = copy.deepcopy(results)
    assessment = calculate_assessment(criteria=criteria, results=results, messages=MESSAGES)
    assert assessment["total"] == expected
    assert assessment["gross_error"] is gross
    assert results == original


def test_contract_fixture_and_sections():
    checklist = json.loads((FIXTURES / "checklist-version.response.json").read_text())
    results = json.loads((FIXTURES / "provider.response.json").read_text())["criterion_results"]
    assessment = calculate_assessment(
        criteria=checklist["criteria"], results=results, messages=MESSAGES
    )
    expected = json.loads((FIXTURES / "evaluation.completed.json").read_text())["original"]
    assert assessment == expected
    schema = json.loads((ROOT / "contracts/openapi.json").read_text())
    Draft202012Validator({"$ref": "#/components/schemas/Assessment", **schema}).validate(assessment)


def test_no_applicable_weight_and_true_zero():
    criteria = initial_checklist().criteria[:1]
    criteria[0] = criteria[0].model_copy(update={"allow_na": True, "na_rule": "Нет оператора"})
    results = answers(criteria)
    results[0].update(applicability="not_applicable", answer=None)
    assessment = calculate_assessment(criteria=criteria, results=results, messages=MESSAGES)
    assert assessment["total"] is None
    assert assessment["no_applicable_reason"]
    assert assessment["sections"][0]["total"] is None
    assert assessment["criteria"][0]["effective_weight"] == 0
    results[0].update(applicability="applicable", answer=False)
    assert calculate_assessment(criteria=criteria, results=results, messages=MESSAGES)["total"] == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda x: x.pop(),
        lambda x: x.append(copy.deepcopy(x[0])),
        lambda x: x[0].update(criterion_id="invented"),
        lambda x: x[0].update(answer=1),
        lambda x: x[0].update(answer=None),
        lambda x: x[0].update(applicability="not_applicable", answer=None),
        lambda x: x[3].update(answer=True),
        lambda x: x[3].update(answer=17),
        lambda x: x[3].update(answer=float("nan")),
        lambda x: x[0].update(evidence=[]),
        lambda x: x[0].update(explanation="  "),
        lambda x: x[0].update(evidence=[{"kind": "message", "message_id": "m9999"}]),
        lambda x: x[0].update(
            evidence=[{"kind": "range", "start_message_id": "m0004", "end_message_id": "m0001"}]
        ),
    ],
)
def test_invalid_model_semantics_are_rejected(mutate):
    criteria = initial_checklist().criteria
    results = answers(criteria)
    mutate(results)
    with pytest.raises(EvaluationError) as error:
        calculate_assessment(criteria=criteria, results=results, messages=MESSAGES)
    assert error.value.code == "AI_INVALID_RESPONSE"


def test_decimal_rounding_and_no_average_of_sections():
    criteria = [
        {
            "id": "a",
            "name": "a",
            "instruction": "a",
            "type": "scale",
            "weight": 19999,
            "allow_na": False,
            "na_rule": None,
            "scale": [
                {"value": 0, "description": "0"},
                {"value": 1, "description": "1"},
                {"value": 20000, "description": "max"},
            ],
            "section": "one",
        },
    ]
    results = [
        {
            "criterion_id": "a",
            "applicability": "applicable",
            "answer": 1,
            "explanation": "synthetic half-up",
            "review_reasons": [],
            "evidence": [{"kind": "message", "message_id": "m0002"}],
        }
    ]
    assert (
        calculate_assessment(criteria=criteria, results=results, messages=MESSAGES)["total"] == 0.01
    )
    criteria.append({**criteria[0], "id": "b", "weight": 1, "section": "two"})
    results.append({**results[0], "criterion_id": "b", "answer": 20000})
    result = calculate_assessment(criteria=criteria, results=results, messages=MESSAGES)
    assert result["total"] == 0.01  # Weighted: 0.00999975, not average(0.005, 100).
    assert [s["total"] for s in result["sections"]] == [0.01, 100]


def test_system_confirmation_is_valid_context_evidence():
    criteria = initial_checklist().criteria[:1]
    results = answers(criteria)
    messages = [{**MESSAGES[0], "speaker": "system"}]
    results[0]["evidence"] = [{"kind": "message", "message_id": "m0001"}]
    assert (
        calculate_assessment(criteria=criteria, results=results, messages=messages)["total"] == 100
    )
