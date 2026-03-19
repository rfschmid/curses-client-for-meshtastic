import unittest
from unittest import mock

import contact.ui.default_config as config
from contact.message_handlers import rx_handler
from contact.utilities.singleton import interface_state, menu_state, ui_state

from tests.test_support import reset_singletons, restore_config, snapshot_config


class RxHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_singletons()
        self.saved_config = snapshot_config("notification_sound", "message_prefix")
        config.notification_sound = "False"

    def tearDown(self) -> None:
        restore_config(self.saved_config)
        reset_singletons()

    def test_on_receive_text_message_refreshes_selected_channel(self) -> None:
        interface_state.myNodeNum = 111
        ui_state.channel_list = ["Primary"]
        ui_state.all_messages = {"Primary": []}
        ui_state.selected_channel = 0

        packet = {
            "from": 222,
            "to": 999,
            "channel": 0,
            "hopStart": 3,
            "hopLimit": 1,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "payload": b"hello"},
        }

        with mock.patch.object(rx_handler, "refresh_node_list", return_value=True):
            with mock.patch.object(rx_handler, "draw_node_list") as draw_node_list:
                with mock.patch.object(rx_handler, "draw_messages_window") as draw_messages_window:
                    with mock.patch.object(rx_handler, "draw_channel_list") as draw_channel_list:
                        with mock.patch.object(rx_handler, "add_notification") as add_notification:
                            with mock.patch.object(rx_handler, "save_message_to_db") as save_message_to_db:
                                with mock.patch.object(rx_handler, "get_name_from_database", return_value="SAT2"):
                                    rx_handler.on_receive(packet, interface=None)

        draw_node_list.assert_called_once_with()
        draw_messages_window.assert_called_once_with(True)
        draw_channel_list.assert_not_called()
        add_notification.assert_not_called()
        save_message_to_db.assert_called_once_with("Primary", 222, "hello")
        self.assertEqual(ui_state.all_messages["Primary"][-1][1], "hello")
        self.assertIn("SAT2:", ui_state.all_messages["Primary"][-1][0])
        self.assertIn("[2]", ui_state.all_messages["Primary"][-1][0])

    def test_on_receive_direct_message_adds_channel_and_notification(self) -> None:
        interface_state.myNodeNum = 111
        ui_state.channel_list = ["Primary"]
        ui_state.all_messages = {"Primary": []}
        ui_state.selected_channel = 0

        packet = {
            "from": 222,
            "to": 111,
            "hopStart": 1,
            "hopLimit": 1,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "payload": b"dm"},
        }

        with mock.patch.object(rx_handler, "refresh_node_list", return_value=False):
            with mock.patch.object(rx_handler, "draw_messages_window") as draw_messages_window:
                with mock.patch.object(rx_handler, "draw_channel_list") as draw_channel_list:
                    with mock.patch.object(rx_handler, "add_notification") as add_notification:
                        with mock.patch.object(rx_handler, "update_node_info_in_db") as update_node_info_in_db:
                            with mock.patch.object(rx_handler, "save_message_to_db") as save_message_to_db:
                                with mock.patch.object(rx_handler, "get_name_from_database", return_value="SAT2"):
                                    rx_handler.on_receive(packet, interface=None)

        self.assertIn(222, ui_state.channel_list)
        self.assertIn(222, ui_state.all_messages)
        draw_messages_window.assert_not_called()
        draw_channel_list.assert_called_once_with()
        add_notification.assert_called_once_with(1)
        update_node_info_in_db.assert_called_once_with(222, chat_archived=False)
        save_message_to_db.assert_called_once_with(222, 222, "dm")

    def test_on_receive_trims_packet_buffer_even_when_packet_is_undecoded(self) -> None:
        ui_state.packet_buffer = list(range(25))
        ui_state.display_log = True
        ui_state.current_window = 4

        with mock.patch.object(rx_handler, "draw_packetlog_win") as draw_packetlog_win:
            rx_handler.on_receive({"id": "new"}, interface=None)

        draw_packetlog_win.assert_called_once_with()
        self.assertEqual(len(ui_state.packet_buffer), 20)
        self.assertEqual(ui_state.packet_buffer[-1], {"id": "new"})
        self.assertTrue(menu_state.need_redraw)
