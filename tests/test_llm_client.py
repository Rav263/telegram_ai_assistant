import json
from urllib.error import URLError
import unittest
from unittest.mock import patch

from telegram_ai_assistant.llm_client import LMStudioClient, LMStudioError


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class LMStudioClientTests(unittest.TestCase):
    def test_extract_json_posts_chat_completion_and_returns_assistant_content(self):
        seen_requests = []

        def transport(request):
            seen_requests.append(request)
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"actions": []}',
                            }
                        }
                    ]
                }
            )

        client = LMStudioClient(
            base_url="http://127.0.0.1:1234/v1/",
            model="local-model",
            transport=transport,
        )

        content = client.extract_json(messages=[{"role": "user", "content": "extract"}])

        self.assertEqual(content, '{"actions": []}')
        self.assertEqual(len(seen_requests), 1)
        request = seen_requests[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:1234/v1/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "local-model")
        self.assertEqual(body["messages"], [{"role": "user", "content": "extract"}])
        self.assertEqual(body["max_tokens"], 8192)
        self.assertEqual(body["max_completion_tokens"], 8192)
        self.assertFalse(body["stream"])
        response_format = body["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        json_schema = response_format["json_schema"]
        self.assertEqual(json_schema["name"], "telegram_action_response")
        self.assertTrue(json_schema["strict"])
        schema = json_schema["schema"]
        self.assertEqual(schema["required"], ["actions"])
        self.assertFalse(schema["additionalProperties"])
        action_schema = schema["properties"]["actions"]["items"]
        self.assertIn("create_item", action_schema["properties"]["type"]["enum"])
        self.assertIn("target_item_id", action_schema["required"])
        self.assertIn("payload", action_schema["required"])
        self.assertIn("rationale", action_schema["required"])

    def test_default_transport_uses_five_minute_timeout(self):
        seen_timeouts = []

        def fake_urlopen(_request, *, timeout):
            seen_timeouts.append(timeout)
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"actions": []}',
                            }
                        }
                    ]
                }
            )

        client = LMStudioClient()

        with patch("telegram_ai_assistant.llm_client.urlopen", side_effect=fake_urlopen):
            client.extract_json(messages=[{"role": "user", "content": "extract"}])

        self.assertEqual(seen_timeouts, [300.0])

    def test_extract_json_wraps_transport_failures(self):
        def failing_transport(_request):
            raise TimeoutError("lm studio is unavailable")

        client = LMStudioClient(transport=failing_transport)

        with self.assertRaises(LMStudioError):
            client.extract_json(messages=[{"role": "user", "content": "extract"}])

    def test_extract_json_wraps_transport_failures_with_safe_diagnostics(self):
        def failing_transport(_request):
            raise URLError("private connection details")

        client = LMStudioClient(
            base_url="http://127.0.0.1:1234/v1",
            transport=failing_transport,
        )

        with self.assertRaises(LMStudioError) as captured:
            client.extract_json(messages=[{"role": "user", "content": "extract"}])

        self.assertEqual(
            captured.exception.safe_metadata,
            {
                "endpoint_scheme": "http",
                "endpoint_host": "127.0.0.1",
                "endpoint_path": "/v1/chat/completions",
                "timeout_seconds": 300.0,
                "max_tokens": 8192,
                "max_completion_tokens": 8192,
                "transport_error_type": "URLError",
            },
        )
        self.assertNotIn("private connection details", str(captured.exception))

    def test_extract_json_wraps_invalid_response_shape_with_safe_diagnostics(self):
        def transport(_request):
            return FakeResponse(
                {
                    "error": {"message": "private model details"},
                    "object": "error",
                }
            )

        client = LMStudioClient(
            base_url="http://127.0.0.1:1234/v1",
            transport=transport,
        )

        with self.assertRaises(LMStudioError) as captured:
            client.extract_json(messages=[{"role": "user", "content": "extract"}])

        self.assertEqual(
            captured.exception.safe_metadata,
            {
                "endpoint_scheme": "http",
                "endpoint_host": "127.0.0.1",
                "endpoint_path": "/v1/chat/completions",
                "timeout_seconds": 300.0,
                "max_tokens": 8192,
                "max_completion_tokens": 8192,
                "failure_stage": "response_schema",
                "response_keys": ["error", "object"],
            },
        )
        self.assertNotIn("private model details", str(captured.exception.safe_metadata))

    def test_extract_json_wraps_empty_assistant_content_with_safe_shape_diagnostics(self):
        def transport(_request):
            return FakeResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "length",
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "reasoning_content": "private reasoning",
                            },
                        }
                    ],
                    "created": 1780000000,
                    "model": "local-model",
                }
            )

        client = LMStudioClient(
            base_url="http://127.0.0.1:1234/v1",
            transport=transport,
        )

        with self.assertRaises(LMStudioError) as captured:
            client.extract_json(messages=[{"role": "user", "content": "extract"}])

        metadata = captured.exception.safe_metadata
        self.assertEqual(metadata["failure_stage"], "response_schema")
        self.assertEqual(metadata["max_tokens"], 8192)
        self.assertEqual(metadata["max_completion_tokens"], 8192)
        self.assertEqual(metadata["choices_count"], 1)
        self.assertEqual(metadata["finish_reason"], "length")
        self.assertEqual(metadata["message_keys"], ["content", "reasoning_content", "role"])
        self.assertEqual(metadata["content_type"], "str")
        self.assertEqual(metadata["content_length"], 0)
        self.assertEqual(metadata["reasoning_content_length"], 17)
        self.assertNotIn("private reasoning", str(metadata))


if __name__ == "__main__":
    unittest.main()
