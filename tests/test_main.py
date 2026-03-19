from argparse import Namespace
import unittest
from unittest import mock

import contact.__main__ as entrypoint


class MainRuntimeTests(unittest.TestCase):
    def test_initialize_runtime_interface_uses_demo_branch(self) -> None:
        args = Namespace(demo_screenshot=True)

        with mock.patch.object(entrypoint, "configure_demo_database") as configure_demo_database:
            with mock.patch.object(entrypoint, "build_demo_interface", return_value="demo-interface") as build_demo:
                with mock.patch.object(entrypoint, "initialize_interface") as initialize_interface:
                    result = entrypoint.initialize_runtime_interface(args)

        self.assertEqual(result, "demo-interface")
        configure_demo_database.assert_called_once_with()
        build_demo.assert_called_once_with()
        initialize_interface.assert_not_called()

    def test_initialize_runtime_interface_uses_live_branch_without_demo_flag(self) -> None:
        args = Namespace(demo_screenshot=False)

        with mock.patch.object(entrypoint, "initialize_interface", return_value="live-interface") as initialize_interface:
            result = entrypoint.initialize_runtime_interface(args)

        self.assertEqual(result, "live-interface")
        initialize_interface.assert_called_once_with(args)
