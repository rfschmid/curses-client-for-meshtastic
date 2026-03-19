import unittest

from contact.utilities.emoji_utils import normalize_message_text


class EmojiUtilsTests(unittest.TestCase):
    def test_strips_modifiers_from_keycaps_and_skin_tones(self) -> None:
        self.assertEqual(normalize_message_text("👍🏽 7️⃣"), "👍 7")

    def test_rewrites_flag_emoji_to_country_codes(self) -> None:
        self.assertEqual(normalize_message_text("🇺🇸 hello 🇩🇪"), "US hello DE")
