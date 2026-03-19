import unittest

from contact.utilities.validation_rules import get_validation_for


class ValidationRulesTests(unittest.TestCase):
    def test_get_validation_for_matches_exact_keys(self) -> None:
        self.assertEqual(get_validation_for("shortName"), {"max_length": 4})

    def test_get_validation_for_matches_substrings(self) -> None:
        self.assertEqual(get_validation_for("config.position.latitude"), {"min_value": -90, "max_value": 90})

    def test_get_validation_for_returns_empty_dict_for_unknown_key(self) -> None:
        self.assertEqual(get_validation_for("totally_unknown"), {})
