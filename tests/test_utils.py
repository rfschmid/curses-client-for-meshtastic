import unittest
from unittest import mock

import contact.ui.default_config as config
from contact.utilities.demo_data import DEMO_LOCAL_NODE_NUM, build_demo_interface
from contact.utilities.singleton import interface_state, ui_state
from contact.utilities.utils import add_new_message, get_channels, get_node_list, parse_protobuf

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

    def test_get_channels_populates_message_buckets_for_device_channels(self) -> None:
        interface_state.interface = build_demo_interface()
        ui_state.channel_list = []
        ui_state.all_messages = {}

        channels = get_channels()

        self.assertIn("MediumFast", channels)
        self.assertIn("Another Channel", channels)
        self.assertIn("MediumFast", ui_state.all_messages)
        self.assertIn("Another Channel", ui_state.all_messages)

    def test_get_channels_rebuilds_renamed_channels_and_preserves_messages(self) -> None:
        interface = build_demo_interface()
        interface.localNode.channels[0].settings.name = "Renamed Channel"
        interface_state.interface = interface
        ui_state.channel_list = ["MediumFast", "Another Channel", 2701131788]
        ui_state.all_messages = {
            "MediumFast": [("prefix", "first")],
            "Another Channel": [("prefix", "second")],
            2701131788: [("prefix", "dm")],
        }
        ui_state.selected_channel = 2

        channels = get_channels()

        self.assertEqual(channels[0], "Renamed Channel")
        self.assertEqual(channels[1], "Another Channel")
        self.assertEqual(channels[2], 2701131788)
        self.assertEqual(ui_state.all_messages["Renamed Channel"], [("prefix", "first")])
        self.assertEqual(ui_state.all_messages["Another Channel"], [("prefix", "second")])
        self.assertEqual(ui_state.all_messages[2701131788], [("prefix", "dm")])
        self.assertNotIn("MediumFast", ui_state.all_messages)

    def test_parse_protobuf_returns_string_payload_unchanged(self) -> None:
        packet = {"decoded": {"portnum": "TEXT_MESSAGE_APP", "payload": "hello"}}

        self.assertEqual(parse_protobuf(packet), "hello")

    def test_parse_protobuf_returns_placeholder_for_text_messages(self) -> None:
        packet = {"decoded": {"portnum": "TEXT_MESSAGE_APP", "payload": b"hello"}}

        self.assertEqual(parse_protobuf(packet), "✉️")
