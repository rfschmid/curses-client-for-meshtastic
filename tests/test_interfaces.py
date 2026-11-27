import asyncio
import concurrent.futures
import threading
import time
from argparse import Namespace
from types import SimpleNamespace
import unittest
from unittest import mock

import meshtastic.ble_interface
from meshtastic.protobuf import localonly_pb2, mesh_pb2

from contact.ui.menus import generate_menu_from_protobuf
from contact.utilities.interfaces import (
    BLEInterface,
    SerialInterface,
    TCPInterface,
    close_interface,
    interface_is_connected,
    reconnect_interface,
)


class InterfacesTests(unittest.TestCase):
    def test_received_status_message_appears_in_settings_after_reconnect(self):
        for transport in (SerialInterface, TCPInterface, BLEInterface):
            with self.subTest(transport=transport.__name__):
                # A fresh interface has no cached value from the previous save.
                interface = transport.__new__(transport)
                interface.configId = 123
                interface.localNode = SimpleNamespace(
                    localConfig=localonly_pb2.LocalConfig(),
                    moduleConfig=localonly_pb2.LocalModuleConfig(),
                    getChannelByChannelIndex=lambda _: None,
                )
                interface.getMyNodeInfo = lambda: {"position": {}}
                for status in ("Available", ""):
                    packet = mesh_pb2.FromRadio()
                    packet.moduleConfig.statusmessage.node_status = status
                    interface._handleFromRadio(packet.SerializeToString())

                    # Other module packets must still pass through normally,
                    # without clearing the status message already received.
                    packet = mesh_pb2.FromRadio()
                    packet.moduleConfig.mqtt.enabled = True
                    interface._handleFromRadio(packet.SerializeToString())

                    self.assertTrue(interface.localNode.moduleConfig.mqtt.enabled)
                    menu = generate_menu_from_protobuf(interface)
                    value = menu["Main Menu"]["Module Settings"]["statusmessage"]["node_status"][1]
                    self.assertEqual(value, status)

    def test_reconnect_interface_retries_until_connection_succeeds(self) -> None:
        args = Namespace()

        ready_interface = SimpleNamespace(localNode=SimpleNamespace(localConfig=object(), nodeNum=123))
        with mock.patch(
            "contact.utilities.interfaces.initialize_interface", side_effect=[None, None, ready_interface]
        ) as initialize:
            with mock.patch("contact.utilities.interfaces.time.sleep") as sleep:
                with mock.patch("contact.utilities.interfaces.logging.info") as info:
                    result = reconnect_interface(args, attempts=3, delay_seconds=0.25)

        self.assertIs(result, ready_interface)
        self.assertEqual(initialize.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(any("Reconnected to Meshtastic node" in call.args[0] for call in info.call_args_list))

    def test_reconnect_interface_raises_after_exhausting_attempts(self) -> None:
        args = Namespace()

        with mock.patch("contact.utilities.interfaces.initialize_interface", return_value=None):
            with mock.patch("contact.utilities.interfaces.time.sleep"):
                with self.assertRaises(RuntimeError):
                    reconnect_interface(args, attempts=2, delay_seconds=0)

    def test_reconnect_interface_stops_at_ble_time_budget(self) -> None:
        args = Namespace(ble="any")

        with mock.patch("contact.utilities.interfaces.initialize_interface", return_value=None) as initialize:
            with mock.patch("contact.utilities.interfaces.time.monotonic", side_effect=[0.0, 11.0, 22.0]):
                with mock.patch("contact.utilities.interfaces.time.sleep") as sleep:
                    with self.assertRaises(RuntimeError):
                        reconnect_interface(args, attempts=20, delay_seconds=1.0)

        self.assertEqual(initialize.call_count, 2)
        sleep.assert_called_once_with(1.0)

    def _make_ble_interface(self, *, connected: bool = True) -> BLEInterface:
        iface = BLEInterface.__new__(BLEInterface)
        iface._init_ble_tracking()
        iface.noProto = False
        iface.failure = None
        iface._want_receive = True
        iface._receiveThread = None
        iface.heartbeatTimer = None
        iface._exit_handler = None
        iface._ble_connected = connected
        iface.isConnected = threading.Event()
        if connected:
            iface.isConnected.set()
        event_thread = SimpleNamespace(is_alive=lambda: True)
        event_loop = SimpleNamespace(is_closed=lambda: False, call_soon_threadsafe=mock.Mock())
        iface.client = SimpleNamespace(
            _eventThread=event_thread,
            _eventLoop=event_loop,
            bleak_client=SimpleNamespace(is_connected=connected),
            disconnect=mock.Mock(),
            close=mock.Mock(),
        )
        return iface

    def test_interface_is_connected_detects_dropped_ble_transport(self) -> None:
        iface = self._make_ble_interface(connected=True)
        self.assertTrue(interface_is_connected(iface))

        iface.client.bleak_client.is_connected = False
        self.assertFalse(interface_is_connected(iface))

        iface.client.bleak_client.is_connected = True
        iface._want_receive = False
        self.assertFalse(interface_is_connected(iface))

        iface._want_receive = True
        iface.client._eventThread = SimpleNamespace(is_alive=lambda: False)
        self.assertFalse(interface_is_connected(iface))

        iface.client = None
        self.assertFalse(interface_is_connected(iface))

    def test_ble_disconnect_callback_on_event_thread_does_not_deadlock(self) -> None:
        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()
        self.addCleanup(lambda: (loop.call_soon_threadsafe(loop.stop), loop_thread.join(timeout=1.0), loop.close()))

        iface = self._make_ble_interface(connected=True)
        iface.client._eventLoop = loop
        iface.client._eventThread = loop_thread
        iface.client.bleak_client = SimpleNamespace(is_connected=False)

        callback_done = threading.Event()
        close_called = threading.Event()
        send_disconnect_called = False

        def fake_send_disconnect():
            nonlocal send_disconnect_called
            send_disconnect_called = True

        iface._sendDisconnect = fake_send_disconnect
        orig_close = iface.close

        def wrapped_close():
            orig_close()
            close_called.set()

        iface.close = wrapped_close

        def trigger_on_event_thread():
            iface._on_ble_disconnect()
            callback_done.set()

        with mock.patch("contact.utilities.interfaces.atexit.unregister") as unregister:
            iface._exit_handler = object()
            loop.call_soon_threadsafe(trigger_on_event_thread)
            self.assertTrue(callback_done.wait(timeout=2.0))
            self.assertTrue(close_called.wait(timeout=2.0))

        self.assertFalse(send_disconnect_called)
        self.assertFalse(iface.isConnected.is_set())
        self.assertIsNone(iface.client)
        unregister.assert_called_once()

    def test_ble_async_await_timeout_marks_disconnected_and_raises(self) -> None:
        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()
        self.addCleanup(lambda: (loop.call_soon_threadsafe(loop.stop), loop_thread.join(timeout=1.0), loop.close()))

        iface = self._make_ble_interface(connected=True)
        client = meshtastic.ble_interface.BLEClient.__new__(meshtastic.ble_interface.BLEClient)
        client._eventLoop = loop
        client._eventThread = loop_thread
        client.bleak_client = SimpleNamespace(is_connected=True, disconnect=mock.AsyncMock())
        iface.client = client
        iface._configure_ble_client(client)

        async def hung_coro():
            await asyncio.sleep(10)

        with self.assertRaises(meshtastic.ble_interface.BLEInterface.BLEError):
            client.async_await(hung_coro(), timeout=0.05)

        self.assertFalse(iface.isConnected.is_set())

    def test_ble_safe_disconnect_skips_when_already_disconnected(self) -> None:
        iface = self._make_ble_interface(connected=False)
        client = meshtastic.ble_interface.BLEClient.__new__(meshtastic.ble_interface.BLEClient)
        client._eventLoop = SimpleNamespace(is_closed=lambda: False)
        client._eventThread = SimpleNamespace(is_alive=lambda: True)
        client.bleak_client = SimpleNamespace(is_connected=False, disconnect=mock.Mock())
        client.async_run = mock.Mock()
        iface._configure_ble_client(client)

        client.disconnect()
        client.async_run.assert_not_called()

    def test_ble_send_to_radio_raises_instead_of_silently_ignoring_disconnect(self) -> None:
        iface = self._make_ble_interface(connected=True)
        iface.client = None
        to_radio = mesh_pb2.ToRadio()
        to_radio.heartbeat.CopyFrom(mesh_pb2.Heartbeat())

        with self.assertRaises(meshtastic.ble_interface.BLEInterface.BLEError):
            iface._sendToRadioImpl(to_radio)

        self.assertFalse(iface.isConnected.is_set())

    def test_ble_wait_connected_aborts_when_disconnect_detected(self) -> None:
        iface = self._make_ble_interface(connected=False)
        threading.Timer(0.05, iface._on_ble_disconnect).start()

        start = time.monotonic()
        with self.assertRaises(meshtastic.mesh_interface.MeshInterface.MeshInterfaceError):
            iface._waitConnected(timeout=10.0)
        self.assertLess(time.monotonic() - start, 2.0)

    def test_close_interface_times_out_without_blocking(self) -> None:
        unblock = threading.Event()

        def stuck_close():
            unblock.wait(timeout=2.0)

        interface = SimpleNamespace(close=stuck_close)
        try:
            self.assertFalse(close_interface(interface, timeout_seconds=0.05))
        finally:
            unblock.set()

    def test_ble_receive_loop_exit_marks_disconnected(self) -> None:
        iface = self._make_ble_interface(connected=True)
        with mock.patch.object(
            meshtastic.ble_interface.BLEInterface,
            "_receiveFromRadioImpl",
            side_effect=RuntimeError("ble read failed"),
        ):
            iface._receiveFromRadioImpl()

        self.assertFalse(iface.isConnected.is_set())

    def test_ble_heartbeat_failure_marks_disconnected(self) -> None:
        iface = self._make_ble_interface(connected=True)
        timers = []

        def fake_timer(interval, fn):
            timer = mock.Mock()
            timer.fn = fn
            timer.interval = interval
            timers.append(timer)
            return timer

        with mock.patch("contact.utilities.interfaces.threading.Timer", side_effect=fake_timer):
            iface._startHeartbeat()

        self.assertEqual(len(timers), 1)
        self.assertTrue(timers[0].daemon)

        with mock.patch.object(
            meshtastic.ble_interface.BLEInterface,
            "sendHeartbeat",
            side_effect=meshtastic.ble_interface.BLEInterface.BLEError("write failed"),
        ):
            timers[0].fn()

        self.assertFalse(iface.isConnected.is_set())
