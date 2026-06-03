import json
from urllib.error import URLError
import unittest

from telegram_ai_assistant.llm_client import LMStudioClient, LMStudioError


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

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
                                "content": '{"items": [], "status_changes": []}',
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

        self.assertEqual(content, '{"items": [], "status_changes": []}')
        self.assertEqual(len(seen_requests), 1)
        request = seen_requests[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:1234/v1/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "local-model")
        self.assertEqual(body["messages"], [{"role": "user", "content": "extract"}])

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
                "transport_error_type": "URLError",
            },
        )
        self.assertNotIn("private connection details", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
