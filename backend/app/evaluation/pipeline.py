"""SQL-free orchestration consumed by the persisted backend worker."""

import logging
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from app.config import Settings
from app.evaluation.budget import BudgetGuard
from app.evaluation.errors import EvaluationError
from app.evaluation.schemas import ChecklistSnapshot, ProviderResult, TranscriptSnapshot
from app.evaluation.scoring import calculate_assessment

PROMPT_VERSION = "cqa-2026-11-07-v1"
logger = logging.getLogger("cqa.evaluation")


class EvaluationProvider(Protocol):
    async def evaluate(
        self, transcript: TranscriptSnapshot, checklist: ChecklistSnapshot, prompt_version: str
    ) -> ProviderResult: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class PipelineResult:
    assessment: dict
    provenance: dict
    review_required: bool
    review_reasons: list[str]


def build_provenance(result: ProviderResult, prompt_version: str = PROMPT_VERSION) -> dict:
    return {
        "provider": result.provider,
        "model_requested": result.model_requested,
        "model_reported": result.model_reported,
        "prompt_version": prompt_version,
        "duration_ms": result.duration_ms,
        "usage": result.usage.model_dump(),
        "estimated_cost_usd": None,
    }


class EvaluationPipeline:
    def __init__(
        self,
        settings: Settings,
        provider: EvaluationProvider | None = None,
        *,
        budget_guard: BudgetGuard | None = None,
    ):
        self.settings = settings
        self.provider = provider
        self.budget_guard = budget_guard

    async def evaluate(self, *, transcript, checklist) -> PipelineResult:
        try:
            transcript = TranscriptSnapshot.model_validate(transcript)
            checklist = ChecklistSnapshot.model_validate(checklist)
        except ValidationError:
            raise EvaluationError("AI_INVALID_SNAPSHOT") from None
        if self.provider is None:
            from app.evaluation.provider import OpenAIProvider

            self.provider = OpenAIProvider(self.settings, budget_guard=self.budget_guard)
        result = await self.provider.evaluate(transcript, checklist, PROMPT_VERSION)
        try:
            result = ProviderResult.model_validate(result)
        except ValidationError:
            raise EvaluationError("AI_INVALID_RESPONSE") from None
        provenance = build_provenance(result)
        if result.usage.request_count < 1:
            raise EvaluationError("AI_INVALID_RESPONSE", provenance=provenance)
        try:
            assessment = calculate_assessment(
                criteria=checklist.criteria,
                results=result.criterion_results,
                messages=transcript.messages,
            )
        except EvaluationError as exc:
            exc.provenance = provenance
            logger.warning("event=evaluation_validation_failed error=AI_INVALID_RESPONSE")
            raise
        reasons = list(
            dict.fromkeys(
                [
                    *result.review_reasons,
                    *(
                        reason
                        for item in result.criterion_results
                        for reason in item.review_reasons
                    ),
                ]
            )
        )
        return PipelineResult(assessment, provenance, bool(reasons), reasons)

    async def aclose(self) -> None:
        if self.provider is not None:
            await self.provider.aclose()
