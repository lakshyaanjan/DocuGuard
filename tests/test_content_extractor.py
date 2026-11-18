import unittest

from docuguard.content_extractor import extract_sentences


class ContentExtractorTests(unittest.TestCase):

    def test_skips_content_inside_fenced_code_blocks(self):
        document = {
            "file": "README.md",
            "lines": [
                {"line": 1, "content": "# Guide"},
                {"line": 2, "content": "The default port is 8000."},
                {"line": 3, "content": chr(96) * 3 + "python"},
                {"line": 4, "content": "DEFAULT_PORT = 8000"},
                {"line": 5, "content": chr(96) * 3},
                {"line": 6, "content": "The service starts normally."}
            ]
        }
        result = extract_sentences(document)
        self.assertEqual(
            [item["content"] for item in result],
            ["The default port is 8000.", "The service starts normally."]
        )

    def test_keeps_markdown_table_rows_with_locations(self):
        document = {
            "file": "README.md",
            "lines": [
                {"line": 1, "content": "| Option | Default |"},
                {"line": 2, "content": "|---|---|"},
                {"line": 3, "content": "| host | localhost |"}
            ]
        }
        result = extract_sentences(document)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "table_row")
        self.assertEqual(result[1]["line"], 3)


if __name__ == "__main__":
    unittest.main()
