import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate

from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data/fixtures/synthetic"
CONTRACT = json.loads((ROOT / "contracts/openapi.json").read_text())
MANIFEST_PATHS = sorted(FIXTURES.rglob("manifest.json"))
EXAMPLES = [
    {
        **example,
        "file": str((path.parent / example["file"]).relative_to(FIXTURES)),
    }
    for path in MANIFEST_PATHS
    for example in json.loads(path.read_text())["fixtures"]
]


def validator(name):
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": f"#/components/schemas/{name}",
        "components": CONTRACT["components"],
    }
    return Draft202012Validator(schema, format_checker=FormatChecker())


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_contract_schemas_are_valid():
    validate(CONTRACT)
    for schema in CONTRACT["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)
    standalone = json.loads((ROOT / "contracts/provider-result.schema.json").read_text())
    Draft202012Validator.check_schema(standalone)
    Draft202012Validator(standalone).validate(fixture("provider.response.json"))


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda entry: entry["file"])
def test_synthetic_wire_examples_match_contract(example):
    validator(example["schema"]).validate(fixture(example["file"]))


def test_all_json_examples_are_registered_and_explicitly_synthetic():
    assert all(json.loads(path.read_text())["synthetic"] is True for path in MANIFEST_PATHS)
    assert len(EXAMPLES) == len({item["file"] for item in EXAMPLES})
    assert {str(path.relative_to(FIXTURES)) for path in FIXTURES.rglob("*.json")} == {
        *(str(path.relative_to(FIXTURES)) for path in MANIFEST_PATHS),
        *(item["file"] for item in EXAMPLES),
    }
    assert {item["language"] for item in fixture("import.request.json")["records"]} == {
        "RU",
        "KZ",
        "EN",
    }


def test_workspace_fixtures_preserve_archive_context_and_immutable_decisions():
    from app.evaluation.scoring import calculate_assessment
    from app.services.evaluations import RESULT_FIELDS

    archived = fixture("workspace/conversation.archived.json")
    current = fixture("workspace/conversation.current.json")
    before = fixture("workspace/evaluation.archived.json")
    latest = fixture("workspace/evaluation.current.json")
    assert archived["id"] == current["id"] == before["conversation_id"]
    assert len(archived["messages"]) == len(current["messages"]) == 120
    assert {m["speaker"] for m in archived["messages"]} == {
        "operator",
        "client",
        "bot",
        "system",
    }
    assert archived["transcript_version_id"] == before["transcript_version_id"]
    assert archived["current_transcript_version_id"] == current["transcript_version_id"]
    assert archived["transcript_version_id"] != current["transcript_version_id"]
    assert archived["messages"][13]["text"] != current["messages"][13]["text"]
    assert current["latest_evaluation"]["id"] == latest["id"]
    for evaluation, conversation, filename, count in (
        (before, archived, "checklist.v1.json", 12),
        (latest, current, "checklist.v2.json", 13),
    ):
        checklist = fixture(f"workspace/{filename}")
        assert evaluation["checklist_version_id"] == checklist["id"]
        assert len(checklist["criteria"]) == count
        for name in ("original", "final"):
            assessment = evaluation[name]
            assert (
                calculate_assessment(
                    criteria=checklist["criteria"],
                    results=[
                        {key: row[key] for key in RESULT_FIELDS} for row in assessment["criteria"]
                    ],
                    messages=conversation["messages"],
                )
                == assessment
            )
    assert before["original"]["total"] == 65.22
    assert before["final"]["total"] == 69.57
    assert latest["original"]["total"] == latest["final"]["total"] == 100
    assert before["final"]["gross_error"] is True
    assert latest["final"]["gross_error"] is False
    for evaluation in (before, latest):
        assert (
            next(
                c
                for c in evaluation["final"]["criteria"]
                if c["criterion_id"] == "supervisor_offer"
            )["answer"]
            is True
        )
    appeals = fixture("workspace/appeals.page.json")["items"]
    confirmed = next(a for a in appeals if a["decision"]["action"] == "confirm")
    overridden = next(a for a in appeals if a["decision"]["action"] == "override")
    assert confirmed["decision"]["result"]["answer"] is False
    assert confirmed["current"]["answer"] is True
    assert overridden["decision"]["result"]["answer"] is True
    assert confirmed["original"]["answer"] == overridden["original"]["answer"] is False
    assert confirmed["decision"]["expected_revision"] == 0
    assert overridden["decision"]["expected_revision"] == 1
    assert (
        confirmed["current_revision"] == overridden["current_revision"] == before["revision"] == 2
    )
    assert fixture("workspace/decision.override.response.json")["evaluation"] == before


@pytest.mark.parametrize(
    "mutation",
    [
        {"weight": True},
        {"weight": -1},
        {"type": "flag", "weight": 10},
        {"type": "binary", "scale": [{"value": 0, "description": "Synthetic"}]},
        {"allow_na": True, "na_rule": None},
        {"allow_na": False, "na_rule": "Unpermitted"},
        {
            "type": "scale",
            "scale": [
                {"value": 0, "description": "Synthetic"},
                {"value": 0, "description": "Synthetic"},
            ],
        },
    ],
)
def test_invalid_criterion_structures_are_rejected(mutation):
    criterion = deepcopy(fixture("checklist.initial.json")["criteria"][0])
    criterion.update(mutation)
    assert not validator("Criterion").is_valid(criterion)


def test_failed_evaluation_cannot_contain_successful_assessment():
    failed = fixture("evaluation.failed.json")
    failed["original"] = fixture("evaluation.completed.json")["original"]
    assert not validator("Evaluation").is_valid(failed)


def test_na_cannot_contain_false_instead_of_null():
    criterion = fixture("provider.response.json")["criterion_results"][2]
    criterion["answer"] = False
    assert not validator("ProviderCriterionResult").is_valid(criterion)


def test_synthetic_history_and_message_references_are_consistent():
    before = fixture("evaluation.completed.json")
    after = fixture("decision.response.json")["evaluation"]
    assert after["original"] == before["original"]
    assert after["revision"] == before["revision"] + 1
    assert before["final"]["total"] == 70
    assert after["final"]["total"] == 100
    message_ids = {message["id"] for message in fixture("transcript.snapshot.json")["messages"]}
    assert {item["criterion_id"] for item in before["original"]["criteria"]} == {
        criterion["id"] for criterion in fixture("checklist-version.response.json")["criteria"]
    }
    for criterion in before["original"]["criteria"]:
        for evidence in criterion["evidence"]:
            ids = [value for key, value in evidence.items() if key.endswith("message_id")]
            assert set(ids) <= message_ids


def test_runtime_health_and_error_responses_match_target_contract(settings):
    with TestClient(create_app(settings)) as client:
        validator("Health").validate(client.get("/health").json())
        validator("Error").validate(client.get("/unknown").json())
        runtime = client.get("/openapi.json").json()
    assert {"/health", "/api/v1/checklists", "/api/v1/conversations/import"} <= set(
        runtime["paths"]
    )
    assert "post" in CONTRACT["paths"]["/api/v1/evaluations"]
