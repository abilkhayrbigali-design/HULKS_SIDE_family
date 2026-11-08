"""OpenAI Responses adapter with one visible bounded retry budget and safe failures."""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

import httpx
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)
from pydantic import ValidationError

from app.config import ConfigurationUnavailable, Settings
from app.diagnostics import log_internal_error
from app.evaluation.budget import (
    MODEL,
    BudgetGuard,
    conservative_settlement,
    current_context,
    make_quote,
)
from app.evaluation.errors import EvaluationError
from app.evaluation.prompts import INSTRUCTIONS, build_input, response_schema
from app.evaluation.schemas import (
    ChecklistSnapshot,
    ModelResult,
    ProviderResult,
    TranscriptSnapshot,
    Usage,
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
        budget_guard: BudgetGuard | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.settings = settings
        self._client = client
        self._owns_client = client is None
        self._sleep = sleep
        self._budget_guard = budget_guard

    def _require_key(self):
        try:
            self.settings.require_llm()
        except ConfigurationUnavailable:
            raise EvaluationError("AI_NOT_CONFIGURED") from None

    async def _get_client(self):
        self._require_key()
        if self._client is None:
            http_client = httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(retries=0, trust_env=False),
                follow_redirects=False,
                trust_env=False,
                timeout=self.settings.llm_timeout_seconds,
            )
            try:
                self._client = AsyncOpenAI(
                    api_key=self.settings.openai_api_key.get_secret_value(),
                    base_url="https://api.openai.com/v1",
                    max_retries=0,
                    timeout=self.settings.llm_timeout_seconds,
                    http_client=http_client,
                )
            except BaseException:
                await http_client.aclose()
                raise
        return self._client

    def _validate_injected_sdk(self):
        if isinstance(self._client, AsyncOpenAI) and (
            self._client.max_retries != 0
            or self._client._client.follow_redirects
            or self._client.base_url != httpx.URL("https://api.openai.com/v1/")
        ):
            raise EvaluationError("AI_BUDGET_POLICY_UNSUPPORTED")

    async def _reserve(self, *, context, attempt, quote):
        try:
            return await self._budget_guard.reserve(context=context, attempt=attempt, quote=quote)
        except EvaluationError:
            raise
        except Exception:
            raise EvaluationError("AI_BUDGET_UNAVAILABLE") from None

    async def _settle(self, reservation_id, usage):
        try:
            await self._budget_guard.settle(reservation_id=reservation_id, usage=usage)
        except EvaluationError:
            raise
        except Exception:
            raise EvaluationError("AI_BUDGET_UNAVAILABLE") from None

    async def _retain_unknown(self, reservation_id):
        # The persisted full reservation already protects the cap. A failed
        # cleanup must never release it or hide the original cancellation/error.
        if reservation_id is not None:
            try:
                await self._settle(reservation_id, None)
            except EvaluationError:
                logger.warning("event=ai_budget_retained error=AI_BUDGET_UNAVAILABLE")

    async def evaluate(
        self, transcript: TranscriptSnapshot, checklist: ChecklistSnapshot, prompt_version: str
    ) -> ProviderResult:
        # Preserve the existing missing-key error, without constructing an SDK client.
        self._require_key()
        started = time.monotonic()
        attempts = []
        model_requested = self.settings.openai_model
        model_reported = None
        reservation_id = None

        def provenance():
            return {
                "provider": "openai",
                "model_requested": model_requested,
                "model_reported": model_reported,
                "prompt_version": prompt_version,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "usage": _merge_usage(attempts),
                "estimated_cost_usd": None,
            }

        try:
            self._validate_injected_sdk()
            context = current_context()
            if self._budget_guard is None or context is None:
                raise EvaluationError("AI_BUDGET_DISABLED")
            quote = make_quote(
                model=model_requested,
                price_version=getattr(self.settings, "llm_price_version", ""),
                max_output_tokens=self.settings.llm_max_output_tokens,
                service_tier=getattr(self.settings, "llm_service_tier", "default"),
            )
            # Build local data before reserving or counting an SDK invocation.
            # Bind monetary parameters to the frozen quote across guard waits.
            payload = {
                "model": quote.model,
                "instructions": INSTRUCTIONS,
                "input": [{"role": "user", "content": build_input(transcript, checklist)}],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "cqa_evaluation",
                        "strict": True,
                        "schema": response_schema(checklist),
                    }
                },
                "reasoning": {"effort": self.settings.llm_reasoning_effort},
                "max_output_tokens": quote.max_output_tokens,
                "service_tier": "default",
                "store": False,
            }
            for attempt in range(1, self.settings.llm_max_retries + 2):
                # Guard may await a transient active reservation. No transaction,
                # SDK client, timeout/retry count or paid attempt exists yet.
                reservation_id = await self._reserve(context=context, attempt=attempt, quote=quote)
                if not isinstance(reservation_id, str) or not reservation_id:
                    raise EvaluationError("AI_BUDGET_UNAVAILABLE")
                client = await self._get_client()
                create = client.responses.create
                counts = dict.fromkeys(TOKEN_FIELDS)
                try:
                    # SDK retries are disabled; timeout applies to each actual request, including
                    # mocked/injected clients. No previous_response_id or response storage is used.
                    async with asyncio.timeout(self.settings.llm_timeout_seconds):
                        logger.info("event=ai_request_started attempt=%d", attempt)
                        attempts.append(counts)
                        response = await create(**payload)
                    counts.update(_usage(response))
                    reported = getattr(response, "model", None)
                    if isinstance(reported, str) and reported.strip():
                        model_reported = reported
                    compatible_policy = reported == MODEL and getattr(
                        response, "service_tier", None
                    ) in {None, "default"}
                    usage = Usage(request_count=1, **counts)
                    if not compatible_policy or conservative_settlement(quote, usage) is None:
                        usage = None
                    # Paid invalid/refused/incomplete answers still settle known usage.
                    # Never depend on successful JSON parsing to account for a paid request.
                    await self._settle(reservation_id, usage)
                    reservation_id = None
                    if not compatible_policy:
                        raise EvaluationError("AI_BUDGET_POLICY_UNSUPPORTED")
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
                except (json.JSONDecodeError, UnicodeDecodeError, APIResponseValidationError):
                    last_error = EvaluationError("AI_INVALID_RESPONSE", retryable=True)
                except (TimeoutError, APITimeoutError):
                    last_error = EvaluationError("AI_TIMEOUT", retryable=True)
                except APIConnectionError:
                    last_error = EvaluationError("AI_UNAVAILABLE", retryable=True)
                except APIStatusError as exc:
                    last_error = _http_failure(exc)
                except EvaluationError as exc:
                    if exc.code.startswith("AI_BUDGET_"):
                        raise
                    last_error = exc
                else:
                    duration = int((time.monotonic() - started) * 1000)
                    logger.info(
                        "event=ai_request_completed attempt=%d duration_ms=%d",
                        attempt,
                        duration,
                    )
                    return ProviderResult(
                        **parsed.model_dump(),
                        provider="openai",
                        model_requested=model_requested,
                        model_reported=model_reported,
                        usage=_merge_usage(attempts),
                        duration_ms=duration,
                    )
                if reservation_id is not None:
                    await self._settle(reservation_id, None)
                    reservation_id = None
                last_error.provenance = provenance()
                if not last_error.retryable or attempt > self.settings.llm_max_retries:
                    # Worker owns the final ERROR and state transition.
                    logger.warning(
                        "event=ai_request_failed attempt=%d error=%s", attempt, last_error.code
                    )
                    raise last_error from None
                logger.warning(
                    "event=ai_request_retry attempt=%d error=%s", attempt, last_error.code
                )
                await self._sleep(min(0.5 * 2 ** (attempt - 1), 8))
        except asyncio.CancelledError as exc:
            # Per-call state only: concurrent evaluations must never share usage. Preserve
            # known paid attempts; an in-flight cancelled request has unknown token counts.
            exc.provenance = provenance()
            await self._retain_unknown(reservation_id)
            logger.warning("event=ai_request_interrupted attempts=%d", len(attempts))
            raise
        except EvaluationError as exc:
            await self._retain_unknown(reservation_id)
            exc.provenance = provenance()
            if exc.code.startswith("AI_BUDGET_"):
                logger.warning("event=ai_budget_rejected error=%s", exc.code)
            raise
        except Exception as exc:
            await self._retain_unknown(reservation_id)
            log_internal_error("AI_PROVIDER_INTERNAL_ERROR", exc)
            raise EvaluationError("AI_UNAVAILABLE", provenance=provenance()) from None

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.close()
            self._client = None
