"""OpenRouter chat-completions client (https://openrouter.ai/docs/api-reference/overview).

One platform-wide API key (OPENROUTER_API_KEY); the model is chosen per call by its OpenRouter
id, e.g. "provider/model". Build clients with app.services.llm_tasks.get_openrouter_client.

Errors: the HTTP status matches the body's `error.code` (402 out of credits, 429 rate limited,
502 model down, 503 no provider meets the routing requirements). An error raised during
generation can arrive as a 200 whose body holds only `error`, so the body is always checked.
Prompts and completions are logged only when OPENROUTER_DEBUG_BODIES is enabled.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
# Statuses worth retrying: timeout, rate limit, model down, no provider available right now.
RETRYABLE_STATUSES = frozenset({408, 429, 502, 503})

log = logging.getLogger(__name__)


class OpenRouterError(Exception):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.status is None or self.status in RETRYABLE_STATUSES


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float | None = None  # credits, when OpenRouter reports it


@dataclass(frozen=True)
class ChatResult:
    id: str | None
    model: str  # the model that actually served the request
    content: str | None
    finish_reason: str | None
    usage: Usage


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        max_retries: int = 2,
        app_title: str | None = None,
        app_url: str | None = None,
        debug_bodies: bool = False,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("An OpenRouter API key is required")
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._timeout = (10.0, timeout)
        self._max_retries = max_retries
        self._debug_bodies = debug_bodies
        self._sleep = sleep
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {api_key}"
        if app_title:
            self._session.headers["X-Title"] = app_title
        if app_url:
            self._session.headers["HTTP-Referer"] = app_url

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        provider: dict[str, Any] | None = None,
    ) -> ChatResult:
        """One non-streaming completion. Retries transient failures; raises OpenRouterError."""
        payload: dict[str, Any] = {"model": model, "messages": messages}
        for key, value in (
            ("response_format", response_format),
            ("temperature", temperature),
            ("max_tokens", max_tokens),
            ("provider", provider),
        ):
            if value is not None:
                payload[key] = value

        for attempt in range(self._max_retries + 1):
            try:
                return self._post(payload)
            except OpenRouterError as exc:
                if not exc.retryable or attempt == self._max_retries:
                    raise
                delay = 2.0**attempt
                log.warning(
                    "OpenRouter %s (%s); retrying in %.0fs",
                    exc.status or "network error",
                    exc,
                    delay,
                )
                self._sleep(delay)
        raise AssertionError("unreachable")

    def _post(self, payload: dict[str, Any]) -> ChatResult:
        log.info("→ OpenRouter chat model=%s", payload["model"])
        if self._debug_bodies:
            log.info("  request messages: %s", payload["messages"])
        try:
            response = self._session.post(self._url, json=payload, timeout=self._timeout)
        except requests.RequestException as exc:
            raise OpenRouterError(f"Could not reach OpenRouter: {type(exc).__name__}") from exc

        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise OpenRouterError(
                f"OpenRouter returned a non-JSON response ({response.status_code})",
                status=response.status_code if response.status_code != 200 else 502,
            )
        error = body.get("error")
        if response.status_code != 200 or error is not None:
            message = error.get("message") if isinstance(error, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            status = response.status_code if response.status_code != 200 else code
            raise OpenRouterError(
                f"OpenRouter error {status}: {message or 'no message'}",
                status=status if isinstance(status, int) else None,
            )

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise OpenRouterError("OpenRouter returned no choices", status=502)
        choice = choices[0]
        if choice.get("finish_reason") == "error":
            raise OpenRouterError("The model failed during generation", status=502)
        message = choice.get("message") or {}
        raw_usage = body.get("usage") or {}
        result = ChatResult(
            id=body.get("id"),
            model=body.get("model") or payload["model"],
            content=message.get("content"),
            finish_reason=choice.get("finish_reason"),
            usage=Usage(
                prompt_tokens=raw_usage.get("prompt_tokens") or 0,
                completion_tokens=raw_usage.get("completion_tokens") or 0,
                total_tokens=raw_usage.get("total_tokens") or 0,
                cost=raw_usage.get("cost"),
            ),
        )
        log.info(
            "← OpenRouter model=%s finish=%s tokens=%s",
            result.model,
            result.finish_reason,
            result.usage.total_tokens,
        )
        if self._debug_bodies:
            log.info("  response content: %s", result.content)
        return result
