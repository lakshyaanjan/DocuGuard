import unittest

from docuguard.value_utils import (
    contains_value,
    find_value_spans,
    replace_value_once,
)


class ValueMatchingTests(unittest.TestCase):

    def test_integer_requires_complete_numeric_token(self):
        self.assertTrue(contains_value(80, "The port is 80."))
        self.assertFalse(contains_value(80, "The port is 8000."))
        self.assertFalse(contains_value(80, "The port is 180."))
        self.assertFalse(contains_value(80, "The port is 80.5."))
        self.assertFalse(contains_value(80, "The port is -80."))

    def test_negative_integer_matches_sign_and_digits(self):
        self.assertTrue(contains_value(-1, "The retry count is -1."))
        self.assertFalse(contains_value(-1, "The retry count is 1."))
        self.assertFalse(contains_value(1, "The retry count is -1."))

    def test_float_requires_complete_numeric_token(self):
        self.assertTrue(contains_value(2.5, "The scale is 2.5."))
        self.assertFalse(contains_value(2.5, "The scale is 12.5."))
        self.assertFalse(contains_value(2.5, "The scale is 2.50."))

    def test_boolean_matches_as_a_word_case_insensitively(self):
        self.assertTrue(contains_value(True, "Feature enabled: true."))
        self.assertFalse(contains_value(True, "Feature is untrue"))

    def test_string_matches_as_a_complete_token(self):
        self.assertTrue(contains_value("localhost", "Host: localhost."))
        self.assertFalse(
            contains_value("localhost", "Host: localhost.localdomain")
        )

    def test_cli_flag_matches_as_a_complete_token(self):
        self.assertTrue(contains_value("--old-name", "Use --old-name now."))
        self.assertFalse(
            contains_value("--old-name", "Use --old-name-extra now.")
        )

    def test_replacement_refuses_prefix_match(self):
        self.assertIsNone(
            replace_value_once(80, 90, "The default port is 8000.")
        )

    def test_replacement_occurs_once_with_exact_spans(self):
        sentence = "The default port is 80."
        spans = find_value_spans(80, sentence)
        self.assertEqual(len(spans), 1)
        self.assertEqual(
            replace_value_once(80, 90, sentence),
            "The default port is 90."
        )


if __name__ == "__main__":
    unittest.main()
