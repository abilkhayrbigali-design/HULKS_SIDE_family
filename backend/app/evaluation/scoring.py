"""Pure Decimal scoring; the same function is used after human appeal decisions."""

import math
from decimal import ROUND_HALF_UP, Decimal, localcontext

from pydantic import TypeAdapter, ValidationError

from app.evaluation.errors import EvaluationError
from app.evaluation.schemas import CriterionResult, Message
from app.schemas.data import CriteriaInput

ZERO = Decimal(0)
HUNDRED = Decimal(100)
CENT = Decimal("0.01")


def _decimal(value) -> Decimal:
    return Decimal(str(value))


def _wire(value: Decimal, *, rounded: bool = False) -> float:
    result = float(value.quantize(CENT, rounding=ROUND_HALF_UP) if rounded else value)
    if not math.isfinite(result):
        raise EvaluationError("AI_INVALID_RESPONSE")
    return result


def validate_results(*, criteria, results, messages):
    """Validate exact criterion set, types, N/A, scales and snapshot evidence links."""
    try:
        definitions = CriteriaInput(criteria=criteria).criteria
        answers = TypeAdapter(list[CriterionResult]).validate_python(results)
        transcript = TypeAdapter(list[Message]).validate_python(messages)
    except ValidationError:
        raise EvaluationError("AI_INVALID_RESPONSE") from None
    if not transcript:
        raise EvaluationError("AI_INVALID_RESPONSE")
    positions = {item.id: item.position for item in transcript}
    if len(positions) != len(transcript) or len(set(positions.values())) != len(transcript):
        raise EvaluationError("AI_INVALID_RESPONSE")
    by_id = {item.criterion_id: item for item in answers}
    if len(by_id) != len(answers) or set(by_id) != {item.id for item in definitions}:
        raise EvaluationError("AI_INVALID_RESPONSE")
    for definition in definitions:
        result = by_id[definition.id]
        if result.applicability == "not_applicable":
            if not definition.allow_na or result.answer is not None:
                raise EvaluationError("AI_INVALID_RESPONSE")
        elif definition.type in {"binary", "flag"}:
            if type(result.answer) is not bool:
                raise EvaluationError("AI_INVALID_RESPONSE")
        elif type(result.answer) not in {int, float} or result.answer not in {
            step.value for step in definition.scale
        }:
            raise EvaluationError("AI_INVALID_RESPONSE")
        for evidence in result.evidence:
            if evidence.kind == "message":
                if evidence.message_id not in positions:
                    raise EvaluationError("AI_INVALID_RESPONSE")
            else:
                start = positions.get(evidence.start_message_id)
                end = positions.get(evidence.end_message_id)
                if start is None or end is None or start > end:
                    raise EvaluationError("AI_INVALID_RESPONSE")
    return definitions, [by_id[item.id] for item in definitions]


def calculate_assessment(*, criteria, results, messages) -> dict:
    """Return JSON-ready assessment without mutating snapshots or input answers."""
    definitions, answers = validate_results(criteria=criteria, results=results, messages=messages)
    # High precision protects intermediate ratios; rounding occurs only at presentation fields.
    with localcontext() as context:
        context.prec = 80
        denominator = sum(
            (
                _decimal(item.weight)
                for item, answer in zip(definitions, answers, strict=True)
                if item.type != "flag" and answer.applicability == "applicable"
            ),
            ZERO,
        )
        numerator = ZERO
        rows = []
        sections = {}
        gross_error = None
        for definition, answer in zip(definitions, answers, strict=True):
            weight = _decimal(definition.weight)
            applicable = answer.applicability == "applicable" and definition.type != "flag"
            factor = ZERO
            if applicable:
                factor = (
                    Decimal(int(answer.answer))
                    if definition.type == "binary"
                    else _decimal(answer.answer) / max(_decimal(s.value) for s in definition.scale)
                )
            base = weight * factor
            numerator += base
            effective_weight = (
                HUNDRED * weight / denominator if applicable and denominator else ZERO
            )
            row = answer.model_dump(mode="json")
            row.update(
                weight=definition.weight,
                base_points=_wire(base),
                effective_weight=_wire(effective_weight, rounded=True),
                effective_points=_wire(effective_weight * factor, rounded=True),
                review_required=bool(answer.review_reasons),
            )
            rows.append(row)
            section = sections.setdefault(definition.section, [ZERO, ZERO])
            section[0] += base
            section[1] += weight if applicable else ZERO
            if definition.id == "gross_errors" and definition.type == "flag":
                gross_error = answer.answer
        return {
            "total": _wire(HUNDRED * numerator / denominator, rounded=True)
            if denominator
            else None,
            "no_applicable_reason": None if denominator else "Нет применимых критериев с весом.",
            "gross_error": gross_error,
            "criteria": rows,
            "sections": [
                {
                    "name": name,
                    "base_points": _wire(points),
                    "applicable_weight": _wire(weight),
                    "total": _wire(HUNDRED * points / weight, rounded=True) if weight else None,
                }
                for name, (points, weight) in sections.items()
            ],
        }
