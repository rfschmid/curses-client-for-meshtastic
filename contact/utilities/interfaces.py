import atexit
import concurrent.futures
import contextlib
import inspect
import io
import logging
import threading
import time
from typing import Optional

import meshtastic.ble_interface
import meshtastic.mesh_interface
import meshtastic.serial_interface
import meshtastic.tcp_interface
from meshtastic.protobuf import mesh_pb2

DEFAULT_CLOSE_TIMEOUT_SECONDS = 5.0
BLE_CONNECT_TIMEOUT_SECONDS = 30.0
BLE_GATT_TIMEOUT_SECONDS = 10.0
BLE_DISCONNECT_TIMEOUT_SECONDS = 3.0
BLE_HEARTBEAT_INTERVAL_SECONDS = 30.0
BLE_RECONNECT_MAX_SECONDS = 20.0


class _StatusMessageConfigMixin:
    """Read status-message config omitted by Meshtastic 2.7.11's receiver."""

    def _handleFromRadio(self, fromRadioBytes):
        packet = mesh_pb2.FromRadio()
        packet.ParseFromString(fromRadioBytes)
        if packet.HasField("moduleConfig") and packet.moduleConfig.HasField("statusmessage"):
            self.localNode.moduleConfig.statusmessage.CopyFrom(packet.moduleConfig.statusmessage)
        return super()._handleFromRadio(fromRadioBytes)


class SerialInterface(_StatusMessageConfigMixin, meshtastic.serial_interface.SerialInterface):
    pass


class TCPInterface(_StatusMessageConfigMixin, meshtastic.tcp_interface.TCPInterface):
    pass


class BLEInterface(_StatusMessageConfigMixin, meshtastic.ble_interface.BLEInterface):
    """BLE interface with non-deadlocking disconnect cleanup and bounded GATT calls."""

    def __init__(self, *args, **kwargs):
        self._init_ble_tracking()
        try:
            super().__init__(*args, **kwargs)
        except BaseException:
            self.close()
            raise
        self._ble_connected = True

    def _init_ble_tracking(self) -> None:
        if hasattr(self, "_state_lock"):
            return
        self._state_lock = threading.Lock()
        self._closing = False
        self._disconnect_detected = False
        self._disconnect_notified = False
        self._ble_connected = False
        self._abort_connect_event = threading.Event()

    def _unregister_exit_handler(self) -> None:
        handler = getattr(self, "_exit_handler", None)
        if handler is not None:
            atexit.unregister(handler)
            self._exit_handler = None

    def _cancel_heartbeat_timer(self) -> None:
        timer = getattr(self, "heartbeatTimer", None)
        if timer is not None:
            with contextlib.suppress(Exception):
                timer.cancel()
            self.heartbeatTimer = None

    def _ble_transport_connected(self) -> bool:
        if getattr(self, "_closing", False) or getattr(self, "_disconnect_detected", False):
            return False
        if not getattr(self, "_want_receive", True):
            return False
        if isinstance(getattr(self, "failure", None), BaseException):
            return False
        client = getattr(self, "client", None)
        if client is None:
            return False
        event_thread = getattr(client, "_eventThread", None)
        if event_thread is not None and not event_thread.is_alive():
            return False
        event_loop = getattr(client, "_eventLoop", None)
        if event_loop is not None and event_loop.is_closed():
            return False
        bleak_client = getattr(client, "bleak_client", None)
        if bleak_client is not None:
            bleak_connected = getattr(bleak_client, "is_connected", None)
            if isinstance(bleak_connected, bool) and not bleak_connected:
                return False
        return True

    def is_transport_connected(self) -> bool:
        """Return True only while both Meshtastic and the underlying BLE link are alive."""
        connected = getattr(self, "isConnected", None)
        if hasattr(connected, "is_set") and not connected.is_set():
            return False
        return self._ble_transport_connected()

    def _mark_disconnected(self) -> None:
        self._init_ble_tracking()
        self._abort_connect_event.set()
        self._cancel_heartbeat_timer()
        with self._state_lock:
            self._disconnect_detected = True
            should_notify = not self._disconnect_notified
            self._disconnect_notified = True
        if should_notify:
            self._disconnected()
        elif hasattr(self, "isConnected") and hasattr(self.isConnected, "clear"):
            self.isConnected.clear()

    def _on_ble_disconnect(self) -> None:
        """Handle transport disconnect safely, including from Bleak's event loop thread."""
        self._init_ble_tracking()
        self._want_receive = False
        self._unregister_exit_handler()
        self._mark_disconnected()
        with self._state_lock:
            already_closing = self._closing
        if not already_closing:
            threading.Thread(target=self.close, name="ble-disconnect-close", daemon=True).start()

    def _safe_close_ble_client(self, client, *, disconnect_first: bool) -> None:
        if client is None:
            return
        if disconnect_first:
            with contextlib.suppress(Exception):
                client.disconnect()
        with contextlib.suppress(Exception):
            client.close()

    def _configure_ble_client(self, client) -> None:
        """Guard BLEClient against event-loop deadlocks and unbounded awaits."""
        original_async_run = client.async_run

        def safe_async_await(coro, timeout=None):
            event_thread = getattr(client, "_eventThread", None)
            event_loop = getattr(client, "_eventLoop", None)
            if event_thread is not None and threading.current_thread() is event_thread:
                if inspect.iscoroutine(coro):
                    coro.close()
                self._on_ble_disconnect()
                raise meshtastic.ble_interface.BLEInterface.BLEError(
                    "Cannot await BLE operation on BLE event loop thread"
                )
            if (event_thread is not None and not event_thread.is_alive()) or (
                event_loop is not None and event_loop.is_closed()
            ):
                if inspect.iscoroutine(coro):
                    coro.close()
                self._on_ble_disconnect()
                raise meshtastic.ble_interface.BLEInterface.BLEError("BLE event loop is no longer running")

            effective_timeout = timeout
            if effective_timeout is None:
                effective_timeout = (
                    BLE_GATT_TIMEOUT_SECONDS
                    if getattr(self, "_ble_connected", False)
                    else BLE_CONNECT_TIMEOUT_SECONDS
                )

            future = original_async_run(coro)
            try:
                return future.result(effective_timeout)
            except (concurrent.futures.TimeoutError, TimeoutError) as exc:
                future.cancel()
                self._on_ble_disconnect()
                raise meshtastic.ble_interface.BLEInterface.BLEError(
                    f"BLE operation timed out after {effective_timeout:.1f}s"
                ) from exc

        def safe_disconnect(**kwargs):
            bleak_client = getattr(client, "bleak_client", None)
            if bleak_client is None or not getattr(bleak_client, "is_connected", False):
                return
            event_thread = getattr(client, "_eventThread", None)
            if event_thread is not None and (
                not event_thread.is_alive() or threading.current_thread() is event_thread
            ):
                return
            try:
                client.async_await(
                    bleak_client.disconnect(**kwargs),
                    timeout=BLE_DISCONNECT_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                logging.debug("Ignoring BLE disconnect error: %s", exc)

        def safe_close():
            event_loop = getattr(client, "_eventLoop", None)
            event_thread = getattr(client, "_eventThread", None)
            if event_loop is not None and not event_loop.is_closed():
                with contextlib.suppress(RuntimeError):
                    event_loop.call_soon_threadsafe(event_loop.stop)
            if (
                event_thread is not None
                and event_thread.is_alive()
                and threading.current_thread() is not event_thread
            ):
                event_thread.join(timeout=2.0)

        client.async_await = safe_async_await
        client.disconnect = safe_disconnect
        client.close = safe_close

    def connect(self, address: Optional[str] = None):
        device = self.find_device(address)
        client = meshtastic.ble_interface.BLEClient(
            device.address,
            disconnected_callback=lambda _client: self._on_ble_disconnect(),
        )
        self._configure_ble_client(client)
        try:
            client.connect()
            client.discover()
        except BaseException:
            self._safe_close_ble_client(client, disconnect_first=True)
            raise
        return client

    def _waitConnected(self, timeout=30.0):
        self._init_ble_tracking()
        if not self.noProto:
            deadline = time.monotonic() + timeout
            while not self.isConnected.is_set():
                if self._abort_connect_event.is_set() or self._disconnect_detected or self._closing:
                    raise meshtastic.mesh_interface.MeshInterface.MeshInterfaceError(
                        "BLE connection closed before setup completed"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise meshtastic.mesh_interface.MeshInterface.MeshInterfaceError(
                        "Timed out waiting for connection completion"
                    )
                self.isConnected.wait(min(0.2, remaining))

        if self.failure:
            raise self.failure

    def _receiveFromRadioImpl(self) -> None:
        try:
            super()._receiveFromRadioImpl()
        except Exception as exc:
            logging.warning("BLE receive loop failed: %s", exc)
        finally:
            if not getattr(self, "_closing", False):
                self._on_ble_disconnect()

    def _sendToRadioImpl(self, toRadio) -> None:
        serialized = toRadio.SerializeToString()
        if not serialized:
            return
        client = getattr(self, "client", None)
        if getattr(self, "_closing", False):
            if (
                client is not None
                and not getattr(self, "_disconnect_detected", False)
                and threading.current_thread() is not getattr(client, "_eventThread", None)
            ):
                with contextlib.suppress(Exception):
                    super()._sendToRadioImpl(toRadio)
            return

        if client is None or not self._ble_transport_connected():
            self._on_ble_disconnect()
            raise meshtastic.ble_interface.BLEInterface.BLEError("BLE device is disconnected")

        try:
            super()._sendToRadioImpl(toRadio)
        except Exception:
            self._on_ble_disconnect()
            raise

    def sendHeartbeat(self):
        try:
            super().sendHeartbeat()
        except Exception:
            self._on_ble_disconnect()
            raise

    def _startHeartbeat(self):
        self._init_ble_tracking()
        self._cancel_heartbeat_timer()

        def schedule_next() -> None:
            if getattr(self, "_closing", False) or getattr(self, "_disconnect_detected", False):
                return
            timer = threading.Timer(BLE_HEARTBEAT_INTERVAL_SECONDS, callback)
            timer.daemon = True
            self.heartbeatTimer = timer
            timer.start()

        def callback() -> None:
            self.heartbeatTimer = None
            if getattr(self, "_closing", False) or getattr(self, "_disconnect_detected", False):
                return
            try:
                self.sendHeartbeat()
            except Exception as exc:
                logging.warning("BLE heartbeat failed; marking connection lost: %s", exc)
                self._on_ble_disconnect()
                return
            schedule_next()

        schedule_next()

    def close(self) -> None:
        self._init_ble_tracking()
        with self._state_lock:
            if getattr(self, "_close_finished", False) or self._closing:
                return
            self._closing = True
            should_send_disconnect = not self._disconnect_detected

        self._unregister_exit_handler()
        self._cancel_heartbeat_timer()
        self._want_receive = False
        self._abort_connect_event.set()

        client = getattr(self, "client", None)
        if (
            should_send_disconnect
            and client is not None
            and threading.current_thread() is not getattr(client, "_eventThread", None)
        ):
            bleak_client = getattr(client, "bleak_client", None)
            if bleak_client is None or getattr(bleak_client, "is_connected", True):
                with contextlib.suppress(Exception):
                    self._sendDisconnect()

        receive_thread = getattr(self, "_receiveThread", None)
        if (
            receive_thread is not None
            and receive_thread.is_alive()
            and receive_thread is not threading.current_thread()
        ):
            receive_thread.join(timeout=2.0)
        self._receiveThread = None

        if client is not None:
            self._safe_close_ble_client(client, disconnect_first=True)
            self.client = None

        self._mark_disconnected()
        with self._state_lock:
            self._close_finished = True


def close_interface(interface: object, timeout_seconds: float = DEFAULT_CLOSE_TIMEOUT_SECONDS) -> bool:
    """Close an interface in a daemon thread so wedged transports cannot hang shutdown."""
    if interface is None:
        return True

    close_errors = []

    def _close_target() -> None:
        try:
            interface.close()
        except BaseException as error:  # Keep shutdown resilient even for KeyboardInterrupt/SystemExit from libraries.
            close_errors.append(error)

    close_thread = threading.Thread(target=_close_target, name="meshtastic-interface-close", daemon=True)
    close_thread.start()
    close_thread.join(timeout_seconds)

    if close_thread.is_alive():
        logging.warning("Timed out closing interface after %.1fs; continuing shutdown", timeout_seconds)
        return False

    if not close_errors:
        return True

    error = close_errors[0]
    if isinstance(error, KeyboardInterrupt):
        logging.info("Interrupted while closing interface; continuing shutdown")
        return True

    logging.warning("Ignoring error while closing interface: %r", error)
    return True


def _ble_transport_is_connected(interface) -> bool:
    if hasattr(interface, "is_transport_connected"):
        return bool(interface.is_transport_connected())
    if getattr(interface, "_closing", False) or getattr(interface, "_disconnect_detected", False):
        return False
    if not getattr(interface, "_want_receive", True):
        return False
    client = getattr(interface, "client", None)
    if client is None:
        return False
    event_thread = getattr(client, "_eventThread", None)
    if event_thread is not None and not event_thread.is_alive():
        return False
    bleak_client = getattr(client, "bleak_client", None)
    if bleak_client is not None:
        bleak_connected = getattr(bleak_client, "is_connected", None)
        if isinstance(bleak_connected, bool) and not bleak_connected:
            return False
    return True


def interface_is_connected(interface) -> bool:
    """Return the transport-independent connection state for an interface.

    TCPInterface deliberately leaves ``stream`` set to ``None`` and uses its
    ``socket`` instead.  Checking only ``stream`` therefore treats every TCP
    connection (including meshtasticd) as disconnected.
    """
    if interface is None:
        return False

    if isinstance(getattr(interface, "failure", None), BaseException):
        return False

    connected = getattr(interface, "isConnected", None)
    if hasattr(connected, "is_set"):
        if not connected.is_set():
            return False
        if isinstance(interface, meshtastic.ble_interface.BLEInterface):
            return _ble_transport_is_connected(interface)
        return True
    if isinstance(connected, bool):
        return connected
    if hasattr(interface, "socket"):
        return getattr(interface, "socket", None) is not None
    if hasattr(interface, "stream"):
        return getattr(interface, "stream", None) is not None
    return getattr(interface, "localNode", None) is not None


def initialize_interface(args, status_callback=None):
    try:

        if args.ble:
            return BLEInterface(args.ble if args.ble != "any" else None)

        elif args.host:
            try:
                if ":" in args.host:
                    tcp_hostname, tcp_port = args.host.split(":")
                else:
                    tcp_hostname = args.host
                    tcp_port = meshtastic.tcp_interface.DEFAULT_TCP_PORT
                return TCPInterface(tcp_hostname, portNumber=tcp_port)
            except Exception as ex:
                logging.error(f"Error connecting to {args.host}. {ex}")
        else:
            try:
                # The library prints its fallback notice directly to stdout,
                # which would overwrite the curses splash screen.
                with contextlib.redirect_stdout(io.StringIO()):
                    client = SerialInterface(args.port)
            except FileNotFoundError as ex:
                logging.error(f"The serial device at '{args.port}' was not found. {ex}")
            except PermissionError as ex:
                logging.error(
                    f"You probably need to add yourself to the `dialout` group to use a serial connection. {ex}"
                )
            except Exception as ex:
                logging.error(f"Unexpected error initializing interface: {ex}")
            except OSError as ex:
                logging.error(f"The serial device couldn't be opened, it might be in use by another process. {ex}")
            if client.devPath is None:
                try:
                    if status_callback:
                        status_callback("No serial device found.\nConnecting via TCP to localhost…")
                    client = TCPInterface("localhost")
                except Exception as ex:
                    logging.error(f"Error connecting to localhost:{ex}")

            return client

    except Exception as ex:
        logging.critical(f"Fatal error initializing interface: {ex}")


def reconnect_interface(
    args,
    attempts: int = 20,
    delay_seconds: float = 1.0,
    max_seconds: Optional[float] = None,
):
    last_error = None
    target = getattr(args, "host", None) or getattr(args, "port", None) or getattr(args, "ble", None) or "auto"
    if max_seconds is None and getattr(args, "ble", None):
        max_seconds = BLE_RECONNECT_MAX_SECONDS
    deadline = time.monotonic() + max_seconds if max_seconds is not None else None

    for attempt in range(attempts):
        attempt_number = attempt + 1
        logging.info("Reconnect attempt %d/%d to %s", attempt_number, attempts, target)
        try:
            interface = initialize_interface(args)
            if (
                interface_is_connected(interface)
                and getattr(interface, "localNode", None) is not None
                and getattr(interface.localNode, "localConfig", None) is not None
            ):
                node_num = getattr(interface.localNode, "nodeNum", None)
                node_label = f" !{node_num:08x}" if isinstance(node_num, int) else ""
                logging.info("Reconnected to Meshtastic node%s on attempt %d/%d", node_label, attempt_number, attempts)
                return interface
            last_error = RuntimeError("interface did not complete connection setup")
            close_interface(interface)
        except Exception as ex:
            last_error = ex

        logging.warning("Reconnect attempt %d/%d failed: %s", attempt_number, attempts, last_error)

        if deadline is not None and time.monotonic() >= deadline:
            break

        if attempt < attempts - 1:
            time.sleep(delay_seconds)

    logging.error("Unable to reconnect to Meshtastic node after %d attempts", attempts)
    raise RuntimeError("Failed to reconnect to the Meshtastic node") from last_error
