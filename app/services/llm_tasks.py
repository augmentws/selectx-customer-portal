"""Structured data clean-up tasks run through OpenRouter (stub: nothing calls these yet).

A task is instructions plus a Pydantic output model. `run_task` sends the input as JSON, asks
for a reply matching the model's JSON schema, validates it, and on an invalid reply asks once
more with the validation errors. Requests are routed only to providers that support
`response_format` (`provider.require_parameters`), so a model without structured-output
support fails with a clear 503 instead of returning free text.
"""

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.config import get_settings
from app.integrations.openrouter import OpenRouterClient, OpenRouterError, Usage

log = logging.getLogger(__name__)


class LLMNotConfiguredError(RuntimeError):
    pass


class LLMTaskError(RuntimeError):
    """The model didn't produce a valid result."""


@lru_cache
def get_openrouter_client() -> OpenRouterClient:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise LLMNotConfiguredError("OPENROUTER_API_KEY is not set")
    return OpenRouterClient(
        settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        timeout=settings.openrouter_timeout_seconds,
        max_retries=settings.openrouter_max_retries,
        app_title=settings.openrouter_app_title or None,
        app_url=settings.web_origin,
        debug_bodies=settings.openrouter_debug_bodies,
    )


@dataclass(frozen=True)
class LLMTask[Out: BaseModel]:
    name: str  # letters, digits, underscores: also the response schema's name
    instructions: str
    output: type[Out]
    model: str | None = None  # None: OPENROUTER_DEFAULT_MODEL
    temperature: float = 0.0


@dataclass(frozen=True)
class TaskResult[Out: BaseModel]:
    output: Out
    model: str  # the model that served the final, valid reply
    usage: Usage  # summed over attempts
    attempts: int


def _parse(task: LLMTask, content: str | None):
    text = (content or "").strip()
    # Some models wrap JSON in a Markdown fence despite response_format.
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return task.output.model_validate_json(text)


def _add(a: Usage, b: Usage) -> Usage:
    cost = None if a.cost is None and b.cost is None else (a.cost or 0) + (b.cost or 0)
    return Usage(
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
        total_tokens=a.total_tokens + b.total_tokens,
        cost=cost,
    )


def run_task[Out: BaseModel](
    task: LLMTask[Out],
    data: BaseModel | dict[str, Any] | str,
    *,
    model: str | None = None,
    client: OpenRouterClient | None = None,
) -> TaskResult[Out]:
    """Run one task on one input. Raises LLMNotConfiguredError, OpenRouterError (after the
    client's retries), or LLMTaskError when the replies never validate."""
    chosen = model or task.model or get_settings().openrouter_default_model
    if not chosen:
        raise LLMNotConfiguredError(
            f"No model for task {task.name}: pass one or set OPENROUTER_DEFAULT_MODEL"
        )
    client = client or get_openrouter_client()
    if isinstance(data, BaseModel):
        payload = data.model_dump_json()
    elif isinstance(data, dict):
        payload = json.dumps(data, default=str)
    else:
        payload = data
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": f"{task.instructions}\n\nReply with only a JSON object matching the schema.",
        },
        {"role": "user", "content": payload},
    ]
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": task.name, "schema": task.output.model_json_schema()},
    }

    usage = Usage()
    last_error: ValidationError | None = None
    for attempt in (1, 2):
        result = client.chat(
            messages,
            model=chosen,
            response_format=response_format,
            temperature=task.temperature,
            provider={"require_parameters": True},
        )
        usage = _add(usage, result.usage)
        try:
            output = _parse(task, result.content)
        except ValidationError as exc:
            last_error = exc
            log.warning(
                "Task %s: invalid reply from %s (attempt %s)", task.name, result.model, attempt
            )
            messages = [
                *messages,
                {"role": "assistant", "content": result.content or ""},
                {
                    "role": "user",
                    "content": "That reply didn't match the schema:\n"
                    f"{exc.errors(include_url=False, include_input=False)}\n"
                    "Reply again with only the corrected JSON object.",
                },
            ]
            continue
        return TaskResult(output=output, model=result.model, usage=usage, attempts=attempt)
    raise LLMTaskError(f"Task {task.name}: no valid reply after 2 attempts") from last_error


# --- Example task (not wired into anything yet) -------------------------------------------


class NormalizedAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str
    address2: str | None
    city: str
    state: str  # two-letter USPS code
    zip: str  # ZIP or ZIP+4
    confidence: Literal["high", "medium", "low"]
    note: str | None  # why confidence isn't high, or what was changed


ADDRESS_CLEANUP = LLMTask(
    name="address_cleanup",
    instructions=(
        "You clean up US postal addresses from a pest-control CRM. Fix casing and obvious typos, "
        "expand nothing that USPS abbreviates (ST, AVE, STE), move suite/floor/unit details to "
        "address2, use the two-letter state code, and keep the ZIP as given unless it is "
        "clearly malformed. Never invent information that isn't in the input; when something "
        "is missing or ambiguous, keep the input value and lower the confidence."
    ),
    output=NormalizedAddress,
)

__all__ = [
    "ADDRESS_CLEANUP",
    "LLMNotConfiguredError",
    "LLMTask",
    "LLMTaskError",
    "NormalizedAddress",
    "OpenRouterError",
    "TaskResult",
    "get_openrouter_client",
    "run_task",
]
