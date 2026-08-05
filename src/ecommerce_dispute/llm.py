"""OpenRouter gateway shared by every agent.

Only the API key comes from the environment. Provider, endpoint and exact model
ID are committed in source so the grader can verify the <=10B constraint.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from .config import MODEL_API_NAME, OPENROUTER_BASE_URL
from .contracts import LLMReview


class LLMError(RuntimeError):
    """Raised when the mandatory API model cannot produce a valid response."""


@dataclass(frozen=True)
class LLMCallResult:
    content: dict[str, Any]
    response_json: str
    duration_ms: float
    prompt_tokens: int
    completion_tokens: int


class ModelGateway(Protocol):
    model_name: str

    def invoke(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> LLMCallResult: ...

    def stats(self) -> dict[str, Any]: ...


class OpenRouterClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = OPENROUTER_BASE_URL,
        model_name: str = MODEL_API_NAME,
        timeout_seconds: int = 180,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self._calls = 0
        self._duration_ms = 0.0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._retry_count = 0

    def assert_ready(self) -> None:
        if not self.api_key:
            raise LLMError(
                "OPENROUTER_API_KEY is required. Put it in the repository .env file."
            )
        if not self.api_key.startswith("sk-or-"):
            raise LLMError("OPENROUTER_API_KEY does not look like an OpenRouter key")

    def invoke(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> LLMCallResult:
        self.assert_ready()
        request_body = {
            "model": self.model_name,
            "stream": False,
            "temperature": 0.1,
            "seed": 42,
            "max_tokens": 160,
            "reasoning": {"enabled": False, "exclude": True},
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"You are {agent_name}. {system_prompt} /no_think\n"
                        "Return only one JSON object matching this JSON Schema: "
                        f"{json.dumps(schema, ensure_ascii=False)}. "
                        "Never invent facts or IDs."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, default=str),
                },
            ],
        }
        encoded = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=encoded,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/olist-dispute-multi-agent",
                "X-Title": "Olist Multi-Agent Dispute Lab",
            },
            method="POST",
        )
        started = time.perf_counter()
        body: dict[str, Any] | None = None
        for attempt in range(1, 5):
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout_seconds
                ) as response:
                    body = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                retryable = exc.code in {408, 409, 429, 500, 502, 503, 504}
                if not retryable or attempt == 4:
                    raise LLMError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                if attempt == 4:
                    raise LLMError(
                        f"OpenRouter call failed for {agent_name}: {exc}"
                    ) from exc
            self._retry_count += 1
            time.sleep(2 ** (attempt - 1))
        if body is None:
            raise LLMError(f"OpenRouter returned no response for {agent_name}")
        duration_ms = round((time.perf_counter() - started) * 1000, 3)

        returned_model = body.get("model")
        if returned_model != self.model_name:
            raise LLMError(
                f"Model identity hard gate failed: requested={self.model_name!r}, "
                f"returned={returned_model!r}"
            )
        try:
            content_text = body["choices"][0]["message"]["content"]
            content = json.loads(content_text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMError(
                f"{agent_name} returned invalid structured content: {body!r}"
            ) from exc
        if not isinstance(content, dict):
            raise LLMError(f"{agent_name} response must be a JSON object")

        usage = body.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        self._calls += 1
        self._duration_ms += duration_ms
        self._prompt_tokens += prompt_tokens
        self._completion_tokens += completion_tokens
        return LLMCallResult(
            content=content,
            response_json=json.dumps(content, ensure_ascii=False, sort_keys=True),
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def stats(self) -> dict[str, Any]:
        return {
            "backend": "openrouter",
            "base_url": self.base_url,
            "model": self.model_name,
            "model_calls": self._calls,
            "total_duration_ms": round(self._duration_ms, 3),
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "retry_count": self._retry_count,
        }


def review(call: LLMCallResult, expected: dict[str, Any], model_name: str) -> LLMReview:
    agreed = all(call.content.get(key) == value for key, value in expected.items())
    return LLMReview(
        model_name=model_name,
        response_json=call.response_json,
        agreed_with_guardrail=agreed,
        duration_ms=call.duration_ms,
    )
