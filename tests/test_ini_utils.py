import os
import tempfile
import unittest
from unittest import mock

from contact.utilities.ini_utils import parse_ini_file


class IniUtilsTests(unittest.TestCase):
    def test_parse_ini_file_reads_sections_fields_and_help_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ini_path = os.path.join(tmpdir, "settings.ini")
            with open(ini_path, "w", encoding="utf-8") as handle:
                handle.write('; comment\n')
                handle.write('[config.device]\n')
                handle.write('title,"Device","Device help"\n')
                handle.write('name,"Node Name","Node help"\n')
                handle.write('empty_help,"Fallback",""\n')

            with mock.patch("contact.utilities.ini_utils.i18n.t", return_value="No help available."):
                mapping, help_text = parse_ini_file(ini_path)

        self.assertEqual(mapping["config.device"], "Device")
        self.assertEqual(help_text["config.device"], "Device help")
        self.assertEqual(mapping["config.device.name"], "Node Name")
        self.assertEqual(help_text["config.device.name"], "Node help")
        self.assertEqual(help_text["config.device.empty_help"], "No help available.")

    def test_parse_ini_file_uses_builtin_help_fallback_when_i18n_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ini_path = os.path.join(tmpdir, "settings.ini")
            with open(ini_path, "w", encoding="utf-8") as handle:
                handle.write('[section]\n')
                handle.write('name,"Name"\n')

            with mock.patch("contact.utilities.ini_utils.i18n.t", side_effect=RuntimeError("boom")):
                mapping, help_text = parse_ini_file(ini_path)

        self.assertEqual(mapping["section.name"], "Name")
        self.assertEqual(help_text["section.name"], "No help available.")
