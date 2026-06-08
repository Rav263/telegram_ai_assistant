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


def request_json_body(request):
    return json.loads(request.data.decode("utf-8")) if request.data else None


TEST_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "test_response",
        "schema": {"type": "object"},
    },
}


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

        content = client.extract_json(
            messages=[{"role": "user", "content": "extract"}],
            response_format=TEST_RESPONSE_FORMAT,
        )

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
        self.assertEqual(body["response_format"], TEST_RESPONSE_FORMAT)

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
            client.extract_json(
                messages=[{"role": "user", "content": "extract"}],
                response_format=TEST_RESPONSE_FORMAT,
            )

        self.assertEqual(seen_timeouts, [300.0])

    def test_load_model_posts_native_lm_studio_context_length(self):
        seen_requests = []

        def transport(request):
            seen_requests.append(request)
            return FakeResponse(
                {
                    "instance_id": "google/gemma-4-12b",
                    "status": "loaded",
                    "load_config": {
                        "context_length": 8192,
                    },
                }
            )

        client = LMStudioClient(
            base_url="http://192.168.0.10:1234/v1",
            model="google/gemma-4-12b",
            context_length=8192,
            transport=transport,
        )

        client.load_model()

        self.assertEqual(len(seen_requests), 1)
        request = seen_requests[0]
        self.assertEqual(request.full_url, "http://192.168.0.10:1234/api/v1/models/load")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            body,
            {
                "model": "google/gemma-4-12b",
                "context_length": 8192,
                "echo_load_config": True,
            },
        )

    def test_ensure_model_loaded_reuses_matching_loaded_instance(self):
        seen_requests = []

        def transport(request):
            seen_requests.append(request)
            return FakeResponse(
                {
                    "models": [
                        {
                            "type": "llm",
                            "key": "google/gemma-4-12b-qat",
                            "loaded_instances": [
                                {
                                    "id": "instance-ok",
                                    "config": {"context_length": 8192},
                                }
                            ],
                        }
                    ]
                }
            )

        client = LMStudioClient(
            base_url="http://192.168.0.10:1234/v1",
            model="google/gemma-4-12b-qat",
            context_length=8192,
            transport=transport,
        )

        client.ensure_model_loaded()

        self.assertEqual(len(seen_requests), 1)
        self.assertEqual(seen_requests[0].full_url, "http://192.168.0.10:1234/api/v1/models")
        self.assertEqual(seen_requests[0].get_method(), "GET")

    def test_ensure_model_loaded_unloads_mismatched_instance_before_load(self):
        seen_requests = []

        def transport(request):
            seen_requests.append(request)
            if request.full_url.endswith("/api/v1/models"):
                return FakeResponse(
                    {
                        "models": [
                            {
                                "type": "llm",
                                "key": "google/gemma-4-12b-qat",
                                "loaded_instances": [
                                    {
                                        "id": "instance-wrong",
                                        "config": {"context_length": 4096},
                                    }
                                ],
                            }
                        ]
                    }
                )
            if request.full_url.endswith("/api/v1/models/unload"):
                return FakeResponse({"instance_id": "instance-wrong"})
            return FakeResponse(
                {
                    "type": "llm",
                    "instance_id": "google/gemma-4-12b-qat",
                    "status": "loaded",
                    "load_config": {"context_length": 8192},
                }
            )

        client = LMStudioClient(
            base_url="http://192.168.0.10:1234/v1",
            model="google/gemma-4-12b-qat",
            context_length=8192,
            transport=transport,
        )

        client.ensure_model_loaded()

        self.assertEqual([request.get_method() for request in seen_requests], ["GET", "POST", "POST"])
        self.assertEqual(seen_requests[1].full_url, "http://192.168.0.10:1234/api/v1/models/unload")
        self.assertEqual(request_json_body(seen_requests[1]), {"instance_id": "instance-wrong"})
        self.assertEqual(seen_requests[2].full_url, "http://192.168.0.10:1234/api/v1/models/load")
        self.assertEqual(request_json_body(seen_requests[2])["context_length"], 8192)

    def test_ensure_model_loaded_unloads_mismatched_configured_instances_even_when_one_matches(self):
        seen_requests = []

        def transport(request):
            seen_requests.append(request)
            if request.full_url.endswith("/api/v1/models"):
                return FakeResponse(
                    {
                        "models": [
                            {
                                "type": "llm",
                                "key": "google/gemma-4-12b-qat",
                                "loaded_instances": [
                                    {"id": "instance-ok", "config": {"context_length": 8192}},
                                    {"id": "instance-wrong", "config": {"context_length": 4096}},
                                ],
                            }
                        ]
                    }
                )
            return FakeResponse({"instance_id": "instance-wrong"})

        client = LMStudioClient(
            base_url="http://192.168.0.10:1234/v1",
            model="google/gemma-4-12b-qat",
            context_length=8192,
            transport=transport,
        )

        client.ensure_model_loaded()

        self.assertEqual(
            [request.full_url for request in seen_requests],
            [
                "http://192.168.0.10:1234/api/v1/models",
                "http://192.168.0.10:1234/api/v1/models/unload",
            ],
        )
        self.assertEqual(request_json_body(seen_requests[1]), {"instance_id": "instance-wrong"})

    def test_ensure_model_loaded_does_not_unload_other_models(self):
        seen_requests = []

        def transport(request):
            seen_requests.append(request)
            if request.full_url.endswith("/api/v1/models"):
                return FakeResponse(
                    {
                        "models": [
                            {
                                "type": "llm",
                                "key": "other/model",
                                "loaded_instances": [
                                    {"id": "other-instance", "config": {"context_length": 4096}}
                                ],
                            },
                            {
                                "type": "llm",
                                "key": "google/gemma-4-12b-qat",
                                "loaded_instances": [],
                            },
                        ]
                    }
                )
            return FakeResponse(
                {
                    "type": "llm",
                    "instance_id": "google/gemma-4-12b-qat",
                    "status": "loaded",
                    "load_config": {"context_length": 8192},
                }
            )

        client = LMStudioClient(
            base_url="http://192.168.0.10:1234/v1",
            model="google/gemma-4-12b-qat",
            context_length=8192,
            transport=transport,
        )

        client.ensure_model_loaded()

        self.assertEqual(
            [request.full_url for request in seen_requests],
            [
                "http://192.168.0.10:1234/api/v1/models",
                "http://192.168.0.10:1234/api/v1/models/load",
            ],
        )

    def test_ensure_model_loaded_raises_safe_error_when_configured_model_missing(self):
        def transport(_request):
            return FakeResponse(
                {"models": [{"type": "llm", "key": "other/model", "loaded_instances": []}]}
            )

        client = LMStudioClient(
            base_url="http://192.168.0.10:1234/v1",
            model="google/gemma-4-12b-qat",
            context_length=8192,
            transport=transport,
        )

        with self.assertRaises(LMStudioError) as captured:
            client.ensure_model_loaded()

        self.assertEqual(captured.exception.safe_metadata["failure_stage"], "model_missing")
        self.assertEqual(captured.exception.safe_metadata["configured_model_key"], "google/gemma-4-12b-qat")
        self.assertEqual(captured.exception.safe_metadata["context_length"], 8192)
        self.assertEqual(captured.exception.safe_metadata["observed_model_count"], 1)

    def test_ensure_model_loaded_unloads_new_instance_when_load_applies_wrong_context(self):
        seen_requests = []

        def transport(request):
            seen_requests.append(request)
            if request.full_url.endswith("/api/v1/models"):
                return FakeResponse(
                    {
                        "models": [
                            {
                                "type": "llm",
                                "key": "google/gemma-4-12b-qat",
                                "loaded_instances": [],
                            }
                        ]
                    }
                )
            if request.full_url.endswith("/api/v1/models/load"):
                return FakeResponse(
                    {
                        "type": "llm",
                        "instance_id": "new-instance",
                        "status": "loaded",
                        "load_config": {"context_length": 4096},
                    }
                )
            return FakeResponse({"instance_id": "new-instance"})

        client = LMStudioClient(
            base_url="http://192.168.0.10:1234/v1",
            model="google/gemma-4-12b-qat",
            context_length=8192,
            transport=transport,
        )

        with self.assertRaises(LMStudioError) as captured:
            client.ensure_model_loaded()

        self.assertEqual(seen_requests[-1].full_url, "http://192.168.0.10:1234/api/v1/models/unload")
        self.assertEqual(request_json_body(seen_requests[-1]), {"instance_id": "new-instance"})
        self.assertEqual(captured.exception.safe_metadata["failure_stage"], "model_load_config_mismatch")
        self.assertEqual(captured.exception.safe_metadata["configured_model_key"], "google/gemma-4-12b-qat")
        self.assertEqual(captured.exception.safe_metadata["applied_context_length"], 4096)

    def test_extract_json_wraps_transport_failures(self):
        def failing_transport(_request):
            raise TimeoutError("lm studio is unavailable")

        client = LMStudioClient(transport=failing_transport)

        with self.assertRaises(LMStudioError):
            client.extract_json(
                messages=[{"role": "user", "content": "extract"}],
                response_format=TEST_RESPONSE_FORMAT,
            )

    def test_extract_json_wraps_transport_failures_with_safe_diagnostics(self):
        def failing_transport(_request):
            raise URLError("private connection details")

        client = LMStudioClient(
            base_url="http://127.0.0.1:1234/v1",
            transport=failing_transport,
        )

        with self.assertRaises(LMStudioError) as captured:
            client.extract_json(
                messages=[{"role": "user", "content": "extract"}],
                response_format=TEST_RESPONSE_FORMAT,
            )

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
            client.extract_json(
                messages=[{"role": "user", "content": "extract"}],
                response_format=TEST_RESPONSE_FORMAT,
            )

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
            client.extract_json(
                messages=[{"role": "user", "content": "extract"}],
                response_format=TEST_RESPONSE_FORMAT,
            )

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
