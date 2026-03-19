import unittest

from contact.utilities.arg_parser import setup_parser


class ArgParserTests(unittest.TestCase):
    def test_demo_screenshot_flag_is_supported(self) -> None:
        args = setup_parser().parse_args(["--demo-screenshot"])
        self.assertTrue(args.demo_screenshot)

    def test_demo_screenshot_defaults_to_false(self) -> None:
        args = setup_parser().parse_args([])
        self.assertFalse(args.demo_screenshot)
