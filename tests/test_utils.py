import unittest
from unittest import mock

import contact.ui.default_config as config
from contact.utilities.demo_data import DEMO_LOCAL_NODE_NUM, build_demo_interface
from contact.utilities.singleton import interface_state, ui_state
from contact.utilities.utils import add_new_message, get_node_list

from tests.test_support import reset_singletons, restore_config, snapshot_config


class UtilsTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_singletons()
        self.saved_config = snapshot_config("node_sort")

    def tearDown(self) -> None:
        restore_config(self.saved_config)
        reset_singletons()

    def test_get_node_list_keeps_local_first_and_ignored_last(self) -> None:
        config.node_sort = "lastHeard"
        interface = build_demo_interface()
        interface_state.interface = interface
        interface_state.myNodeNum = DEMO_LOCAL_NODE_NUM

        node_list = get_node_list()

        self.assertEqual(node_list[0], DEMO_LOCAL_NODE_NUM)
        self.assertEqual(node_list[-1], 0xA1000008)

    def test_add_new_message_groups_messages_by_hour(self) -> None:
        ui_state.all_messages = {"MediumFast": []}

        with mock.patch("contact.utilities.utils.time.time", side_effect=[1000, 1000]):
            with mock.patch("contact.utilities.utils.time.strftime", return_value="[00:16:40] "):
                with mock.patch("contact.utilities.utils.datetime.datetime") as mocked_datetime:
                    mocked_datetime.fromtimestamp.return_value.strftime.return_value = "2025-02-04 17:00"
                    add_new_message("MediumFast", ">> Test: ", "First")
                    add_new_message("MediumFast", ">> Test: ", "Second")

        self.assertEqual(
            ui_state.all_messages["MediumFast"],
            [
                ("-- 2025-02-04 17:00 --", ""),
                ("[00:16:40] >> Test: ", "First"),
                ("[00:16:40] >> Test: ", "Second"),
            ],
        )
