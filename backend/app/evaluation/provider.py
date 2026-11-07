"""OpenAI Responses adapter with one visible bounded retry budget and safe failures."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import ValidationError

from app.config import ConfigurationUnavailable, Settings
from app.evaluation.errors import EvaluationError
from app.evaluation.prompts import INSTRUCTIONS, build_input, response_schema
from app.evaluation.schemas import (
    ChecklistSnapshot,
    ModelResult,
    ProviderResult,
    TranscriptSnapshot,
)
from app.evaluation.scoring import validate_results

logger = logging.getLogger("cqa.evaluation")
TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_input_tokens",
    "reasoning_output_tokens",
)


def _counter(value):
    return value if type(value) is int and value >= 0 else None


def _usage(response) -> dict:
    usage = getattr(response, "usage", None)
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    return {
        "input_tokens": _counter(getattr(usage, "input_tokens", None)),
        "output_tokens": _counter(getattr(usage, "output_tokens", None)),
        "total_tokens": _counter(getattr(usage, "total_tokens", None)),
        "cached_input_tokens": _counter(getattr(input_details, "cached_tokens", None)),
        "reasoning_output_tokens": _counter(getattr(output_details, "reasoning_tokens", None)),
    }


def _merge_usage(attempts: list[dict]) -> dict:
    # An unknown count on any attempt makes that aggregate unknown, not zero.
    return {
        "request_count": len(attempts),
        **{
            field: sum(item[field] for item in attempts)
            if all(item[field] is not None for item in attempts)
            else None
            for field in TOKEN_FIELDS
        },
    }


def _http_failure(exc: APIStatusError) -> EvaluationError:
    status = exc.status_code
    if status in {401, 403, 404}:
        return EvaluationError("AI_AUTHENTICATION_FAILED")
    if status == 429:
        return EvaluationError("AI_RATE_LIMITED", retryable=True)
    if status in {408, 409} or status >= 500:
        return EvaluationError("AI_UNAVAILABLE", retryable=True)
    return EvaluationError("AI_REQUEST_REJECTED")


class OpenAIProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        client=None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.settings = settings
        self._client = client
        self._owns_client = client is None
        self._sleep = sleep

    def _get_client(self):
        try:
            self.settings.require_llm()
        except ConfigurationUnavailable:
            raise EvaluationError("AI_NOT_CONFIGURED") from None
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.settings.openai_api_key.get_secret_value(),
                max_retries=0,
                timeout=self.settings.llm_timeout_seconds,
            )
        return self._client

    async def evaluate(
        self, transcript: TranscriptSnapshot, checklist: ChecklistSnapshot, prompt_version: str
    ) -> ProviderResult:
        client = self._get_client()
        started = time.monotonic()
        attempts = []
        model_reported = None
        for attempt in range(1, self.settings.llm_max_retries + 2):
            logger.info("event=ai_request_started attempt=%d", attempt)
            counts = dict.fromkeys(TOKEN_FIELDS)
            try:
                # SDK retries are disabled; timeout applies to each actual request, including
                # mocked/injected clients. No previous_response_id or response storage is used.
                async with asyncio.timeout(self.settings.llm_timeout_seconds):
                    response = await client.responses.create(
                        model=self.settings.openai_model,
                        instructions=INSTRUCTIONS,
                        input=[{"role": "user", "content": build_input(transcript, checklist)}],
                        text={
                            "format": {
                                "type": "json_schema",
                                "name": "cqa_evaluation",
                                "strict": True,
                                "schema": response_schema(checklist),
                            }
                        },
                        reasoning={
                            "effort": getattr(self.settings, "llm_reasoning_effort", "medium")
                        },
                        max_output_tokens=getattr(self.settings, "llm_max_output_tokens", 12000),
                        store=False,
                    )
                counts = _usage(response)
                reported = getattr(response, "model", None)
                if isinstance(reported, str) and reported.strip():
                    model_reported = reported
                output = getattr(response, "output", None)
                if not isinstance(output, list):
                    raise EvaluationError("AI_INVALID_RESPONSE", retryable=True)
                text_parts = []
                for item in output:
                    if getattr(item, "type", None) != "message":
                        continue
                    content_items = getattr(item, "content", None)
                    if not isinstance(content_items, list):
                        raise EvaluationError("AI_INVALID_RESPONSE", retryable=True)
                    for content in content_items:
                        if getattr(content, "type", None) == "refusal":
                            raise EvaluationError("AI_REFUSED")
                        if getattr(content, "type", None) == "output_text":
                            text = getattr(content, "text", None)
                            if not isinstance(text, str):
                                raise EvaluationError("AI_INVALID_RESPONSE", retryable=True)
                            text_parts.append(text)
                if getattr(response, "status", None) != "completed":
                    raise EvaluationError("AI_INCOMPLETE", retryable=True)
                try:
                    parsed = ModelResult.model_validate_json("".join(text_parts))
                except ValidationError:
                    raise EvaluationError("AI_INVALID_RESPONSE", retryable=True) from None
                try:
                    validate_results(
                        criteria=checklist.criteria,
                        results=parsed.criterion_results,
                        messages=transcript.messages,
                    )
                except EvaluationError:
                    raise EvaluationError("AI_INVALID_RESPONSE", retryable=True) from None
            except (TimeoutError, APITimeoutError):
                last_error = EvaluationError("AI_TIMEOUT", retryable=True)
            except APIConnectionError:
                last_error = EvaluationError("AI_UNAVAILABLE", retryable=True)
            except APIStatusError as exc:
                last_error = _http_failure(exc)
            except EvaluationError as exc:
                last_error = exc
            else:
                attempts.append(counts)
                duration = int((time.monotonic() - started) * 1000)
                logger.info(
                    "event=ai_request_completed attempt=%d duration_ms=%d",
                    attempt,
                    duration,
                )
                return ProviderResult(
                    **parsed.model_dump(),
                    provider="openai",
                    model_requested=self.settings.openai_model,
                    model_reported=model_reported,
                    usage=_merge_usage(attempts),
                    duration_ms=duration,
                )
            attempts.append(counts)
            last_error.provenance = {
                "provider": "openai",
                "model_requested": self.settings.openai_model,
                "model_reported": model_reported,
                "prompt_version": prompt_version,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "usage": _merge_usage(attempts),
                "estimated_cost_usd": None,
            }
            if not last_error.retryable or attempt > self.settings.llm_max_retries:
                # Worker owns the final ERROR and state transition.
                logger.warning(
                    "event=ai_request_failed attempt=%d error=%s", attempt, last_error.code
                )
                raise last_error from None
            logger.warning("event=ai_request_retry attempt=%d error=%s", attempt, last_error.code)
            await self._sleep(min(0.5 * 2 ** (attempt - 1), 8))

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.close()
            self._client = None
