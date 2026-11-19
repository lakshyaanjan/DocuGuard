import io
import os
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from docuguard.llm_client import (
    LLMError,
    _post_json,
    create_embeddings,
    create_structured_response,
    get_api_base,
    get_api_key,
)


class LLMClientTests(unittest.TestCase):
    def test_transient_503_is_retried_then_succeeds(self):
        error = HTTPError(
            "https://example.test/v1/chat/completions",
            503,
            "Service Unavailable",
            {},
            io.BytesIO(b'{"error":"overloaded"}'),
        )
        response = io.BytesIO(b'{"ok": true}')
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "unit-test-key", "DOCUGUARD_OPENAI_BASE_URL": "https://example.test/v1"},
            clear=True,
        ):
            with patch("docuguard.llm_client.urlopen", side_effect=[error, response]) as request:
                with patch("docuguard.llm_client.time.sleep") as sleep:
                    result = _post_json("chat/completions", {"model": "test"})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(0.8)

    def test_retryable_503_exhaustion_reports_attempt_count(self):
        errors = [
            HTTPError("https://example.test", 503, "Service Unavailable", {}, io.BytesIO(b'busy'))
            for _ in range(3)
        ]
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "unit-test-key", "DOCUGUARD_OPENAI_BASE_URL": "https://example.test/v1"},
            clear=True,
        ):
            with patch("docuguard.llm_client.urlopen", side_effect=errors) as request:
                with patch("docuguard.llm_client.time.sleep"):
                    with self.assertRaisesRegex(LLMError, "HTTP 503 after 3 attempt"):
                        _post_json("chat/completions", {"model": "test"})
        self.assertEqual(request.call_count, 3)

    def test_embeddings_are_returned_in_input_order(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-key"}, clear=True):
            with patch(
                "docuguard.llm_client._post_json",
                return_value={
                    "data": [
                        {"index": 1, "embedding": [0.4, 0.5]},
                        {"index": 0, "embedding": [0.1, 0.2]},
                    ]
                },
            ) as request:
                vectors = create_embeddings(["first", "second"], model="test-embedding")
        self.assertEqual(vectors, [[0.1, 0.2], [0.4, 0.5]])
        self.assertEqual(request.call_args.args[0], "embeddings")
        self.assertEqual(request.call_args.args[1]["model"], "test-embedding")

    def test_empty_embedding_input_does_not_call_api(self):
        with patch("docuguard.llm_client._post_json") as request:
            self.assertEqual(create_embeddings([]), [])
        request.assert_not_called()

    def test_chat_completions_json_output_is_parsed(self):
        response = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": '{"analyses": []}',
                },
                "finish_reason": "stop",
            }],
        }
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-key"}, clear=True):
            with patch("docuguard.llm_client._post_json", return_value=response) as request:
                parsed = create_structured_response(
                    "Review this change.",
                    {
                        "type": "object",
                        "properties": {
                            "analyses": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["analyses"],
                        "additionalProperties": False,
                    },
                    model="test-model",
                )
        self.assertEqual(parsed, {"analyses": []})
        self.assertEqual(request.call_args.args[0], "chat/completions")
        payload = request.call_args.args[1]
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])

    def test_gemini_api_key_alias_is_recognised(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test-key"}, clear=True):
            self.assertEqual(get_api_key(), "gemini-test-key")

    def test_openai_compatible_gemini_base_url_is_accepted(self):
        with patch.dict(
            os.environ,
            {"DOCUGUARD_OPENAI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai/"},
            clear=True,
        ):
            self.assertEqual(
                get_api_base(),
                "https://generativelanguage.googleapis.com/v1beta/openai",
            )

    def test_gemini_key_takes_precedence_for_gemini_endpoint(self):
        with patch.dict(
            os.environ,
            {
                "DOCUGUARD_OPENAI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai",
                "OPENAI_API_KEY": "wrong-provider-key",
                "GEMINI_API_KEY": "gemini-provider-key",
            },
            clear=True,
        ):
            self.assertEqual(get_api_key(), "gemini-provider-key")

    def test_missing_key_fails_clearly(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(LLMError, "No API key"):
                create_embeddings(["text"])

    def test_api_key_cannot_be_sent_to_plain_http_remote_host(self):
        with patch.dict(
            os.environ,
            {"DOCUGUARD_OPENAI_BASE_URL": "http://example.com/v1"},
            clear=True,
        ):
            with self.assertRaisesRegex(LLMError, "HTTPS"):
                get_api_base()


if __name__ == "__main__":
    unittest.main()
