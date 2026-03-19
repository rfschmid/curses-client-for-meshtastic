import unittest
from unittest import mock

import contact.ui.default_config as config
from contact.ui import contact_ui
from contact.utilities.singleton import ui_state

from tests.test_support import reset_singletons, restore_config, snapshot_config


class ContactUiTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_singletons()
        self.saved_config = snapshot_config("single_pane_mode")

    def tearDown(self) -> None:
        restore_config(self.saved_config)
        reset_singletons()

    def test_handle_backtick_refreshes_channels_after_settings_menu(self) -> None:
        stdscr = mock.Mock()
        ui_state.current_window = 1
        config.single_pane_mode = "False"

        with mock.patch.object(contact_ui.curses, "curs_set") as curs_set:
            with mock.patch.object(contact_ui, "settings_menu") as settings_menu:
                with mock.patch.object(contact_ui, "get_channels") as get_channels:
                    with mock.patch.object(contact_ui, "refresh_node_list") as refresh_node_list:
                        with mock.patch.object(contact_ui, "handle_resize") as handle_resize:
                            contact_ui.handle_backtick(stdscr)

        settings_menu.assert_called_once()
        get_channels.assert_called_once_with()
        refresh_node_list.assert_called_once_with()
        handle_resize.assert_called_once_with(stdscr, False)
        self.assertEqual(curs_set.call_args_list[0].args, (0,))
        self.assertEqual(curs_set.call_args_list[-1].args, (1,))
        self.assertEqual(ui_state.current_window, 1)

    def test_process_pending_ui_updates_draws_requested_windows(self) -> None:
        stdscr = mock.Mock()
        ui_state.redraw_channels = True
        ui_state.redraw_messages = True
        ui_state.redraw_nodes = True
        ui_state.redraw_packetlog = True
        ui_state.scroll_messages_to_bottom = True

        with mock.patch.object(contact_ui, "draw_channel_list") as draw_channel_list:
            with mock.patch.object(contact_ui, "draw_messages_window") as draw_messages_window:
                with mock.patch.object(contact_ui, "draw_node_list") as draw_node_list:
                    with mock.patch.object(contact_ui, "draw_packetlog_win") as draw_packetlog_win:
                        contact_ui.process_pending_ui_updates(stdscr)

        draw_channel_list.assert_called_once_with()
        draw_messages_window.assert_called_once_with(True)
        draw_node_list.assert_called_once_with()
        draw_packetlog_win.assert_called_once_with()

    def test_process_pending_ui_updates_full_redraw_uses_handle_resize(self) -> None:
        stdscr = mock.Mock()
        ui_state.redraw_full_ui = True
        ui_state.redraw_channels = True
        ui_state.redraw_messages = True

        with mock.patch.object(contact_ui, "handle_resize") as handle_resize:
            contact_ui.process_pending_ui_updates(stdscr)

        handle_resize.assert_called_once_with(stdscr, False)
        self.assertFalse(ui_state.redraw_channels)
        self.assertFalse(ui_state.redraw_messages)

    def test_refresh_node_selection_highlights_full_row_width(self) -> None:
        ui_state.node_list = [101, 202]
        ui_state.selected_node = 1
        ui_state.start_index = [0, 0, 0]
        contact_ui.nodes_pad = mock.Mock()
        contact_ui.nodes_pad.getmaxyx.return_value = (4, 20)
        contact_ui.nodes_win = mock.Mock()
        contact_ui.nodes_win.getmaxyx.return_value = (10, 20)

        interface = mock.Mock()
        interface.nodesByNum = {101: {}, 202: {}}

        with mock.patch.object(contact_ui, "refresh_pad") as refresh_pad:
            with mock.patch.object(contact_ui, "draw_window_arrows") as draw_window_arrows:
                with mock.patch.object(contact_ui, "get_node_row_color", side_effect=[11, 22]):
                    with mock.patch("contact.ui.contact_ui.interface_state.interface", interface):
                        contact_ui.refresh_node_selection(old_index=0, highlight=True)

        self.assertEqual(
            contact_ui.nodes_pad.chgat.call_args_list,
            [mock.call(0, 1, 18, 11), mock.call(1, 1, 18, 22)],
        )
        refresh_pad.assert_called_once_with(2)
        draw_window_arrows.assert_called_once_with(2)
