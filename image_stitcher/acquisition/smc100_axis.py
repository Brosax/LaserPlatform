"""
Standalone SMC100 (Newport) axis controller.

Communicates directly over serial using the Newport ASCII protocol,
with no dependency on ``analyzr2`` or the existing ``xyz_table`` package.

Features
--------
- Shared serial port with reference counting (for daisy-chained controllers)
- Blocking ``move_to`` / ``move_by`` / ``homing`` with 50 ms polling
- Position in micrometers; wire protocol uses millimeters
- Automatic error checking after every command
- Retry on transient read failures
"""

import logging
import threading
import time
from typing import ClassVar, Optional

import serial

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#  Newport message
# ------------------------------------------------------------------ #


class NewportMessage:
    """One Newport ASCII protocol message."""

    def __init__(self, command: str, *, address: str = "", data: str = ""):
        self.address = address
        self.command = command
        self.data = data

    def pack(self) -> bytes:
        return f"{self.address}{self.command}{self.data}\r\n".encode("utf-8")

    def __str__(self) -> str:
        return f"{self.address}{self.command}{self.data}"


# ------------------------------------------------------------------ #
#  Exceptions
# ------------------------------------------------------------------ #


class SMC100Error(RuntimeError):
    """Raised when the SMC100 controller reports an error."""


# ------------------------------------------------------------------ #
#  SMC100 Axis
# ------------------------------------------------------------------ #

# State groups (hex strings returned by the TS query)
_NOT_REFERENCED = {"0A", "0B", "0C", "0D", "0E", "0F", "10", "11", "14"}
_HOMING_STATES = {"1E", "1F"}
_READY_STATES = {"32", "33", "34", "35"}
_MOVING_STATES = {"28"}
_JOGGING_STATES = {"46", "47"}

# Serial settings for SMC100
_COM_SETTINGS = {
    "baudrate": 57600,
    "bytesize": serial.EIGHTBITS,
    "parity": serial.PARITY_NONE,
    "stopbits": serial.STOPBITS_ONE,
    "rtscts": False,
    "xonxoff": True,
}

MAX_RETRY = 4


class SMC100Axis:
    """
    Single-axis controller for a Newport SMC100 stage.

    Parameters
    ----------
    port : str
        Serial port name (e.g. ``"COM11"``).
    address : int
        Controller address on the daisy chain (1-31).
    timeout : float
        Serial read timeout in seconds.
    """

    # Class-level shared serial ports {port_name: serial.Serial}
    _shared_serials: ClassVar[dict[str, serial.Serial]] = {}
    _ref_counts: ClassVar[dict[str, int]] = {}
    _locks: ClassVar[dict[str, threading.RLock]] = {}

    def __init__(self, port: str, address: int, timeout: float = 1.0):
        self._port = port
        self._address = address
        self._address_str = str(address)
        self._timeout = timeout

        created_serial = False

        # --- Shared serial port ---
        if (
            port not in SMC100Axis._shared_serials
            or not SMC100Axis._shared_serials[port].is_open
        ):
            ser = serial.Serial(
                port=port,
                timeout=timeout,
                **_COM_SETTINGS,
            )
            SMC100Axis._shared_serials[port] = ser
            SMC100Axis._ref_counts[port] = 0
            SMC100Axis._locks[port] = threading.RLock()
            created_serial = True
            logger.info(f"Opened serial port {port} (57600, 8N1, XON/XOFF)")

        self._serial = SMC100Axis._shared_serials[port]
        SMC100Axis._ref_counts[port] += 1

        # Internal state
        self._position_um: float = 0.0
        self._state: str = "0A"
        self._error: str = "0000"
        self._neg_limit_um: float = 0.0
        self._pos_limit_um: float = 0.0
        self._retry_count: int = 0

        # Query initial state
        try:
            self._update_status()
            self._read_software_limits()
            logger.info(
                f"SMC100 addr={address} on {port}: state={self._state}, "
                f"pos={self._position_um:.1f} um, "
                f"limits=[{self._neg_limit_um:.0f}, {self._pos_limit_um:.0f}] um"
            )
        except Exception:
            # Roll back this axis registration so failed connects do not
            # leave stale serial handles or ref counts.
            SMC100Axis._ref_counts[port] -= 1
            if SMC100Axis._ref_counts[port] <= 0 and created_serial:
                try:
                    self._serial.close()
                finally:
                    del SMC100Axis._shared_serials[port]
                    del SMC100Axis._ref_counts[port]
                    SMC100Axis._locks.pop(port, None)
                    logger.info(f"Closed serial port {port} after init failure")
            raise

    # ------------------------------------------------------------------ #
    #  Properties
    # ------------------------------------------------------------------ #

    @property
    def position(self) -> float:
        """Current position in micrometers."""
        return self._position_um

    @property
    def homed(self) -> bool:
        return self._state not in (_NOT_REFERENCED | _HOMING_STATES)

    @property
    def ready(self) -> bool:
        return self._state in _READY_STATES

    @property
    def moving(self) -> bool:
        return self._state in _MOVING_STATES

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def homing(self) -> None:
        """
        Execute a home search and block until complete.

        Skips if the axis is already homed.
        """
        self._update_status()
        if self.homed:
            logger.info(f"SMC100 addr={self._address}: already homed.")
            return

        logger.info(f"SMC100 addr={self._address}: starting home search...")
        self._send(NewportMessage("OR", address=self._address_str))
        self._verify_last_command()

        while True:
            time.sleep(0.05)
            self._update_status()
            if self.ready:
                logger.info(
                    f"SMC100 addr={self._address}: homing complete, "
                    f"pos={self._position_um:.1f} um"
                )
                return
            if self._state in _HOMING_STATES or self.moving:
                continue
            raise SMC100Error(
                f"SMC100 addr={self._address}: unexpected state {self._state} "
                f"during homing"
            )

    def move_to(self, position_um: float) -> None:
        """
        Move to an absolute position in micrometers (blocking).

        The position is clamped to the controller's software limits.
        """
        position_um = self._clamp(position_um)

        self._update_status()
        if abs(position_um - self._position_um) < 0.01:
            return

        pos_mm = position_um / 1000.0
        logger.debug(
            f"SMC100 addr={self._address}: move_to {position_um:.1f} um "
            f"({pos_mm:.4f} mm)"
        )
        self._send(NewportMessage("PA", address=self._address_str, data=str(pos_mm)))
        self._verify_last_command()
        self._wait_until_ready()

    def move_by(self, distance_um: float) -> None:
        """
        Move by a relative distance in micrometers (blocking).

        The resulting position is clamped to software limits.
        """
        if abs(distance_um) < 0.01:
            return

        # Clamp the target
        self._update_status()
        target = self._clamp(self._position_um + distance_um)
        actual_distance = target - self._position_um
        if abs(actual_distance) < 0.01:
            return

        dist_mm = actual_distance / 1000.0
        self._send(NewportMessage("PR", address=self._address_str, data=str(dist_mm)))
        self._verify_last_command()
        self._wait_until_ready()

    def halt(self) -> None:
        """Stop motion immediately."""
        self._send(NewportMessage("ST", address=self._address_str))
        self._verify_last_command()

    def set_velocity(self, velocity_um_s: float) -> None:
        """Set the motion velocity in um/s."""
        vel_mm = velocity_um_s / 1000.0
        self._send(NewportMessage("VA", address=self._address_str, data=str(vel_mm)))
        self._verify_last_command()

    def set_acceleration(self, accel_um_s2: float) -> None:
        """Set the motion acceleration in um/s^2."""
        acc_mm = accel_um_s2 / 1000.0
        self._send(NewportMessage("AC", address=self._address_str, data=str(acc_mm)))
        self._verify_last_command()

    def close(self) -> None:
        """
        Release the serial port (reference-counted).

        Only actually closes the port when the last axis on it disconnects.
        """
        port = self._port
        if port in SMC100Axis._ref_counts:
            SMC100Axis._ref_counts[port] -= 1
            if SMC100Axis._ref_counts[port] <= 0:
                self._serial.close()
                del SMC100Axis._shared_serials[port]
                del SMC100Axis._ref_counts[port]
                SMC100Axis._locks.pop(port, None)
                logger.info(f"Closed serial port {port}")
            else:
                logger.debug(
                    f"Released SMC100 addr={self._address} on {port} "
                    f"({SMC100Axis._ref_counts[port]} remaining)"
                )

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    @property
    def _lock(self) -> threading.RLock:
        return SMC100Axis._locks[self._port]

    def _send(self, msg: NewportMessage) -> None:
        with self._lock:
            self._serial.write(msg.pack())

    def _read(self) -> NewportMessage:
        raw = self._serial.readline()
        if not raw:
            raise TimeoutError(f"SMC100 addr={self._address}: no response (timeout)")
        text = raw.decode("utf-8").strip()
        # Parse: address digits + 2-char command + remaining data
        # Address may be 1-2 digits
        addr = ""
        idx = 0
        while idx < len(text) and text[idx].isdigit():
            addr += text[idx]
            idx += 1
        command = text[idx : idx + 2]
        data = text[idx + 2 :]
        return NewportMessage(command, address=addr, data=data)

    def _query(self, msg: NewportMessage) -> NewportMessage:
        """Send a query and read the response, with retry on decode errors."""
        with self._lock:
            try:
                self._serial.write(msg.pack())
                reply = self._read()
                self._retry_count = 0
                return reply
            except UnicodeDecodeError:
                self._retry_count += 1
                if self._retry_count >= MAX_RETRY:
                    self._retry_count = 0
                    raise TimeoutError(f"SMC100 addr={self._address}: max retries exceeded")
        # Retry outside the lock to allow other threads to proceed
        return self._query(msg)

    def _verify_last_command(self) -> None:
        """Check that the last command did not produce an error."""
        reply = self._query(NewportMessage("TE", address=self._address_str, data=""))
        if reply.data.strip() != "@":
            # Get error description
            err_code = reply.data.strip()
            desc_reply = self._query(
                NewportMessage("TB", address=self._address_str, data=err_code)
            )
            raise SMC100Error(
                f"SMC100 addr={self._address}: command error {err_code} - "
                f"{desc_reply.data.strip()}"
            )

    def _update_status(self) -> None:
        """Query controller state and position."""
        # TS -> 6 chars: 4 error + 2 state
        reply = self._query(NewportMessage("TS", address=self._address_str, data=""))
        status_str = reply.data.strip()
        if len(status_str) >= 6:
            self._error = status_str[:4]
            self._state = status_str[4:6]
        elif len(status_str) >= 2:
            self._state = status_str[-2:]

        if self._error != "0000":
            raise SMC100Error(
                f"SMC100 addr={self._address}: controller error {self._error}"
            )

        # TP -> position in mm
        reply = self._query(NewportMessage("TP", address=self._address_str, data=""))
        try:
            self._position_um = float(reply.data.strip()) * 1000.0
        except ValueError:
            logger.warning(
                f"SMC100 addr={self._address}: could not parse position '{reply.data}'"
            )

    def _read_software_limits(self) -> None:
        """Read negative and positive software limits from the controller."""
        reply = self._query(NewportMessage("SL", address=self._address_str, data="?"))
        try:
            self._neg_limit_um = float(reply.data.strip()) * 1000.0
        except ValueError:
            self._neg_limit_um = -1e9

        reply = self._query(NewportMessage("SR", address=self._address_str, data="?"))
        try:
            self._pos_limit_um = float(reply.data.strip()) * 1000.0
        except ValueError:
            self._pos_limit_um = 1e9

    def _clamp(self, position_um: float) -> float:
        """Clamp position to software limits."""
        if position_um < self._neg_limit_um:
            logger.warning(
                f"SMC100 addr={self._address}: clamping {position_um:.1f} to "
                f"negative limit {self._neg_limit_um:.1f} um"
            )
            return self._neg_limit_um
        if position_um > self._pos_limit_um:
            logger.warning(
                f"SMC100 addr={self._address}: clamping {position_um:.1f} to "
                f"positive limit {self._pos_limit_um:.1f} um"
            )
            return self._pos_limit_um
        return position_um

    def _wait_until_ready(self) -> None:
        """Poll status every 50 ms until the controller is ready."""
        while True:
            time.sleep(0.05)
            self._update_status()
            if self.ready:
                return
            if self.moving or self._state in _HOMING_STATES:
                continue
            raise SMC100Error(
                f"SMC100 addr={self._address}: unexpected state {self._state} "
                f"while waiting for ready"
            )
