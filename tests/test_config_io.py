import unittest

from contact.utilities.config_io import _is_repeated_field, splitCompoundName


class ConfigIoTests(unittest.TestCase):
    def test_split_compound_name_preserves_multi_part_values(self) -> None:
        self.assertEqual(splitCompoundName("config.device.role"), ["config", "device", "role"])

    def test_split_compound_name_duplicates_single_part_values(self) -> None:
        self.assertEqual(splitCompoundName("owner"), ["owner", "owner"])

    def test_is_repeated_field_prefers_new_style_attribute(self) -> None:
        field = type("Field", (), {"is_repeated": True})()

        self.assertTrue(_is_repeated_field(field))

    def test_is_repeated_field_falls_back_to_label_comparison(self) -> None:
        field_type = type("Field", (), {"label": 3, "LABEL_REPEATED": 3})

        self.assertTrue(_is_repeated_field(field_type()))
