import json

import pytest
import requests
import responses

from app.core.config import get_settings
from app.integrations.openrouter import OpenRouterClient, OpenRouterError
from app.services import llm_tasks
from app.services.llm_tasks import ADDRESS_CLEANUP, LLMNotConfiguredError, LLMTaskError, run_task

URL = "https://openrouter.test/api/v1/chat/completions"
MODEL = "test-provider/test-model"
ADDRESS = {
    "address": "150 e 44th st, front 1",
    "city": "new york",
    "state": "New York",
    "zip": "10017",
}
CLEAN = {
    "address": "150 E 44TH ST",
    "address2": "FRONT 1",
    "city": "NEW YORK",
    "state": "NY",
    "zip": "10017",
    "confidence": "high",
    "note": None,
}


def completion(content: str, *, model: str = MODEL, finish: str = "stop", cost=None) -> dict:
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    if cost is not None:
        usage["cost"] = cost
    return {
        "id": "gen-1",
        "model": model,
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": finish}
        ],
        "usage": usage,
    }


@pytest.fixture
def api():
    with responses.RequestsMock() as rsps:
        yield rsps


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def client(sleeps):
    return OpenRouterClient(
        "test-key",
        base_url="https://openrouter.test/api/v1",
        max_retries=2,
        app_title="Test",
        sleep=sleeps.append,
    )


def sent(api, index: int = 0) -> dict:
    return json.loads(api.calls[index].request.body)


def test_task_returns_validated_output_and_usage(api, client):
    api.post(URL, json=completion(json.dumps(CLEAN), cost=0.0004))
    result = run_task(ADDRESS_CLEANUP, ADDRESS, model=MODEL, client=client)

    assert result.output.state == "NY" and result.output.address2 == "FRONT 1"
    assert (result.model, result.attempts) == (MODEL, 1)
    assert result.usage.total_tokens == 120 and result.usage.cost == 0.0004

    request = api.calls[0].request
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.headers["X-Title"] == "Test"
    body = sent(api)
    assert body["model"] == MODEL
    assert body["provider"] == {"require_parameters": True}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "address_cleanup"
    assert "confidence" in body["response_format"]["json_schema"]["schema"]["properties"]
    assert json.loads(body["messages"][1]["content"]) == ADDRESS


def test_fenced_json_is_accepted(api, client):
    api.post(URL, json=completion(f"```json\n{json.dumps(CLEAN)}\n```"))
    assert run_task(ADDRESS_CLEANUP, ADDRESS, model=MODEL, client=client).output.city == "NEW YORK"


def test_invalid_reply_is_retried_once_with_the_errors(api, client):
    api.post(URL, json=completion('{"address": "150 E 44TH ST"}'))
    api.post(URL, json=completion(json.dumps(CLEAN)))
    result = run_task(ADDRESS_CLEANUP, ADDRESS, model=MODEL, client=client)

    assert result.attempts == 2 and result.usage.total_tokens == 240
    retry = sent(api, 1)["messages"]
    assert retry[-2] == {"role": "assistant", "content": '{"address": "150 E 44TH ST"}'}
    assert "didn't match the schema" in retry[-1]["content"]


def test_two_invalid_replies_raise(api, client):
    api.post(URL, json=completion("not json"))
    api.post(URL, json=completion("still not json"))
    with pytest.raises(LLMTaskError):
        run_task(ADDRESS_CLEANUP, ADDRESS, model=MODEL, client=client)


@pytest.mark.parametrize("status", [429, 502, 503])
def test_transient_errors_are_retried(api, client, sleeps, status):
    api.post(URL, status=status, json={"error": {"code": status, "message": "busy"}})
    api.post(URL, json=completion(json.dumps(CLEAN)))
    assert run_task(ADDRESS_CLEANUP, ADDRESS, model=MODEL, client=client).attempts == 1
    assert sleeps == [1.0]


def test_network_errors_are_retried_then_raised(api, client, sleeps):
    api.post(URL, body=requests.ConnectionError("down"))
    api.post(URL, body=requests.ConnectionError("down"))
    api.post(URL, body=requests.ConnectionError("down"))
    with pytest.raises(OpenRouterError, match="Could not reach OpenRouter"):
        run_task(ADDRESS_CLEANUP, ADDRESS, model=MODEL, client=client)
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize("status", [400, 401, 402, 403])
def test_client_errors_are_not_retried(api, client, sleeps, status):
    api.post(URL, status=status, json={"error": {"code": status, "message": "nope"}})
    with pytest.raises(OpenRouterError) as exc:
        run_task(ADDRESS_CLEANUP, ADDRESS, model=MODEL, client=client)
    assert exc.value.status == status
    assert len(api.calls) == 1 and sleeps == []


def test_error_inside_a_200_is_raised(api, client):
    # Errors during generation arrive with status 200 and only an `error` in the body.
    for _ in range(3):
        api.post(URL, json={"error": {"code": 502, "message": "provider failed"}})
    with pytest.raises(OpenRouterError, match="provider failed"):
        run_task(ADDRESS_CLEANUP, ADDRESS, model=MODEL, client=client)


def test_a_model_is_required(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_DEFAULT_MODEL", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(LLMNotConfiguredError, match="No model"):
            run_task(ADDRESS_CLEANUP, ADDRESS, client=client)
    finally:
        get_settings.cache_clear()


def test_missing_api_key_is_reported(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    get_settings.cache_clear()
    llm_tasks.get_openrouter_client.cache_clear()
    try:
        with pytest.raises(LLMNotConfiguredError, match="OPENROUTER_API_KEY"):
            llm_tasks.get_openrouter_client()
    finally:
        get_settings.cache_clear()
        llm_tasks.get_openrouter_client.cache_clear()
