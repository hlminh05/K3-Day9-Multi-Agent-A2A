from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from ecommerce_dispute.llm import LLMError, OpenRouterClient


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, *args, **kwargs):
        return self.payload


class OpenRouterClientTests(unittest.TestCase):
    def test_structured_call_and_exact_model_identity(self):
        chat = FakeHTTPResponse(
            {
                "model": "qwen/qwen3-8b",
                "choices": [{"message": {"content": '{"accepted": true}'}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4},
            }
        )
        client = OpenRouterClient(api_key="sk-or-v1-test")
        with patch("urllib.request.urlopen", return_value=chat):
            result = client.invoke(
                agent_name="test_agent",
                system_prompt="Check the payload.",
                payload={"value": 1},
                schema={
                    "type": "object",
                    "properties": {"accepted": {"type": "boolean"}},
                    "required": ["accepted"],
                },
            )
        self.assertEqual({"accepted": True}, result.content)
        self.assertEqual(1, client.stats()["model_calls"])
        self.assertEqual(11, client.stats()["prompt_tokens"])

    def test_missing_api_key_fails_closed(self):
        client = OpenRouterClient(api_key="")
        with patch.dict("os.environ", {}, clear=True):
            client.api_key = ""
            with self.assertRaisesRegex(LLMError, "OPENROUTER_API_KEY"):
                client.assert_ready()

    def test_provider_cannot_substitute_a_larger_model(self):
        chat = FakeHTTPResponse(
            {
                "model": "qwen/qwen3-32b",
                "choices": [{"message": {"content": '{"accepted": true}'}}],
                "usage": {},
            }
        )
        client = OpenRouterClient(api_key="sk-or-v1-test")
        with patch("urllib.request.urlopen", return_value=chat):
            with self.assertRaisesRegex(LLMError, "Model identity hard gate"):
                client.invoke(
                    agent_name="test_agent",
                    system_prompt="Check.",
                    payload={},
                    schema={"type": "object"},
                )


if __name__ == "__main__":
    unittest.main()
