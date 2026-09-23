"""OpenRouter client over the OpenAI-compatible chat API: retries, error mapping, usage and cost capture."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Protocol

from openai import (
    APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, InternalServerError, RateLimitError,
)

log = logging.getLogger(__name__)


class LLMError(Exception):
    """The model can't be used right now. `code`: unavailable | credits | auth | bad_request | empty | disabled."""

    def __init__(self, message: str, code: str = "unavailable"):
        super().__init__(message)
        self.code = code


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class LLMResult:
    text: str
    tool_calls: list[ToolCall]
    message: dict                   # the assistant message, appended to history verbatim
    reasoning: str | None = None
    finish_reason: str | None = None
    usage: dict = field(default_factory=dict)


class LLM(Protocol):
    model: str

    async def chat(
        self, messages: list[dict], *, tools: list[dict] | None = None, reasoning: dict | None = None,
        response_format: dict | None = None, max_tokens: int = 4000, cache: bool = True,
    ) -> LLMResult: ...


class OpenRouterLLM:
    def __init__(self, api_key: str, model: str, base_url: str, timeout_s: float, app_url: str):
        self.model = model
        self._client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=0,
            default_headers={"HTTP-Referer": app_url, "X-Title": "Perfect Saturday Planner"},
        )

    async def chat(
        self, messages: list[dict], *, tools: list[dict] | None = None, reasoning: dict | None = None,
        response_format: dict | None = None, max_tokens: int = 4000, cache: bool = True,
    ) -> LLMResult:
        extra: dict = {}
        if reasoning is not None:
            extra["reasoning"] = reasoning
        if cache:
            extra["cache_control"] = {"type": "ephemeral"}  # OpenRouter automatic prompt caching (Anthropic)
        kwargs: dict = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "extra_body": extra}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if response_format:
            kwargs["response_format"] = response_format

        resp = None
        for attempt, delay in enumerate((0.8, 2.0, None)):
            try:
                resp = await self._client.chat.completions.create(**kwargs)
                break
            except (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError) as exc:
                if delay is None:
                    raise LLMError(f"model unavailable after retries ({exc.__class__.__name__})") from exc
                log.warning("openrouter attempt %s failed: %s", attempt + 1, exc)
                await asyncio.sleep(delay)
            except APIStatusError as exc:
                code = {401: "auth", 402: "credits", 403: "auth"}.get(exc.status_code, "bad_request")
                raise LLMError(f"model error {exc.status_code}: {_error_text(exc)}", code) from exc

        if resp is None or not resp.choices:
            err = (getattr(resp, "model_extra", None) or {}).get("error") if resp is not None else None
            raise LLMError(f"empty response from model: {err}", "empty")
        choice = resp.choices[0]
        msg = choice.message
        message = msg.model_dump(exclude_none=True)
        message["role"] = "assistant"
        if not message.get("content"):
            message.pop("content", None)       # empty text blocks are rejected upstream
        if not message.get("annotations"):
            message.pop("annotations", None)
        extra_fields = msg.model_extra or {}
        return LLMResult(
            text=(msg.content or "").strip(),
            tool_calls=[ToolCall(tc.id, tc.function.name, tc.function.arguments or "{}") for tc in (msg.tool_calls or [])],
            message=message,
            reasoning=_reasoning_text(extra_fields),
            finish_reason=choice.finish_reason,
            usage=_usage(resp.usage),
        )


def _reasoning_text(extra: dict) -> str | None:
    text = extra.get("reasoning")
    if isinstance(text, str) and text.strip():
        return text.strip()
    parts = [d.get("text") or d.get("summary") or "" for d in extra.get("reasoning_details") or [] if isinstance(d, dict)]
    joined = " ".join(p for p in parts if isinstance(p, str)).strip()
    return joined or None


def _usage(usage) -> dict:
    if usage is None:
        return {}
    extra = usage.model_extra or {}
    details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) if details is not None else 0
    return {
        "prompt_tokens": usage.prompt_tokens or 0,
        "completion_tokens": usage.completion_tokens or 0,
        "cached_tokens": cached or 0,
        "cost_usd": float(extra.get("cost") or 0.0),
    }


def _error_text(exc: APIStatusError) -> str:
    body = exc.body if isinstance(exc.body, dict) else {}
    err = body.get("error", body)
    if isinstance(err, dict):
        return str(err.get("message") or err)[:300]
    return str(exc)[:300]


class DisabledLLM:
    """Stand-in when no API key is configured: every call fails fast so the fallbacks take over."""

    model = "disabled"

    async def chat(self, messages, **_kwargs) -> LLMResult:
        raise LLMError("no OPENROUTER_API_KEY configured", "disabled")
