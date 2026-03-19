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
