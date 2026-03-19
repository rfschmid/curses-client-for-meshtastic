from argparse import Namespace
import unittest
from unittest import mock

from contact.utilities.interfaces import reconnect_interface


class InterfacesTests(unittest.TestCase):
    def test_reconnect_interface_retries_until_connection_succeeds(self) -> None:
        args = Namespace()

        with mock.patch("contact.utilities.interfaces.initialize_interface", side_effect=[None, None, "iface"]) as initialize:
            with mock.patch("contact.utilities.interfaces.time.sleep") as sleep:
                result = reconnect_interface(args, attempts=3, delay_seconds=0.25)

        self.assertEqual(result, "iface")
        self.assertEqual(initialize.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_reconnect_interface_raises_after_exhausting_attempts(self) -> None:
        args = Namespace()

        with mock.patch("contact.utilities.interfaces.initialize_interface", return_value=None):
            with mock.patch("contact.utilities.interfaces.time.sleep"):
                with self.assertRaises(RuntimeError):
                    reconnect_interface(args, attempts=2, delay_seconds=0)
