import unittest

from contact.utilities.control_utils import transform_menu_path


class ControlUtilsTests(unittest.TestCase):
    def test_transform_menu_path_applies_replacements_and_normalization(self) -> None:
        transformed = transform_menu_path(["Main Menu", "Radio Settings", "Channel 2", "Detail"])

        self.assertEqual(transformed, ["config", "channel", "Detail"])

    def test_transform_menu_path_preserves_unmatched_entries(self) -> None:
        transformed = transform_menu_path(["Main Menu", "Module Settings", "WiFi"])

        self.assertEqual(transformed, ["module", "WiFi"])
