import os
import unittest
from unittest.mock import patch

from docuguard.llm_client import (
    LLMError,
    create_embeddings,
    create_structured_response,
    get_api_base,
)


class LLMClientTests(unittest.TestCase):
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
            ):
                vectors = create_embeddings(["first", "second"])
        self.assertEqual(vectors, [[0.1, 0.2], [0.4, 0.5]])

    def test_empty_embedding_input_does_not_call_api(self):
        with patch("docuguard.llm_client._post_json") as request:
            self.assertEqual(create_embeddings([]), [])
        request.assert_not_called()

    def test_responses_api_json_output_is_parsed(self):
        response = {
            "status": "completed",
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": '{"analyses": []}',
                }],
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
        self.assertEqual(request.call_args.args[0], "responses")
        self.assertEqual(request.call_args.args[1]["model"], "test-model")
        self.assertFalse(request.call_args.args[1]["store"])

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
