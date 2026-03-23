"""
Standalone Thorlabs MLJ250 axis adapter.

Provides a lightweight axis interface compatible with ``XYTable`` for
manual Z control, without depending on ``analyzr2``.
"""

import logging
import time
from typing import ClassVar

import serial

from xyz_table.thorlabs.driver.MLJ250_motion_controller import MLJ250MotionController

logger = logging.getLogger(__name__)


class MLJ250Axis:
    """Single-axis wrapper for a Thorlabs MLJ250 controller."""

    _shared_serials: ClassVar[dict[str, serial.Serial]] = {}
    _ref_counts: ClassVar[dict[str, int]] = {}

    def __init__(self, port: str, timeout: float = 1.0):
        self._port = port
        self._timeout = timeout
        created_serial = False

        if (
            port not in MLJ250Axis._shared_serials
            or not MLJ250Axis._shared_serials[port].is_open
        ):
            ser = serial.Serial(
                port=port,
                baudrate=115200,
                bytesize=serial.EIGHTBITS,
                stopbits=serial.STOPBITS_ONE,
                parity=serial.PARITY_NONE,
                rtscts=True,
                timeout=timeout,
            )
            MLJ250Axis._shared_serials[port] = ser
            MLJ250Axis._ref_counts[port] = 0
            created_serial = True
            logger.info("Opened MLJ250 serial port %s", port)

        self._serial = MLJ250Axis._shared_serials[port]
        MLJ250Axis._ref_counts[port] += 1

        try:
            self._controller = MLJ250MotionController(self._serial)
            self._update_status()
            logger.info("MLJ250 connected on %s at %.2f um", port, self.position)
        except Exception:
            # Roll back this axis registration so failed connects do not
            # leave stale serial handles or ref counts.
            MLJ250Axis._ref_counts[port] -= 1
            if MLJ250Axis._ref_counts[port] <= 0 and created_serial:
                try:
                    self._serial.close()
                finally:
                    del MLJ250Axis._shared_serials[port]
                    del MLJ250Axis._ref_counts[port]
                    logger.info("Closed MLJ250 serial port %s after init failure", port)
            raise

    @property
    def position(self) -> float:
        """Current position in micrometers."""
        return self._controller.position_um

    def _update_status(self) -> None:
        """Query the controller for an updated status snapshot."""
        self._controller.update_status()

    def homing(self, timeout_s: float = 120.0) -> None:
        """Home the axis and block until complete."""
        self._controller.set_home_parameters()
        self._controller.home()

        start = time.monotonic()
        while True:
            self._controller.update_status()
            if self._controller.homed:
                return
            if (time.monotonic() - start) > timeout_s:
                raise TimeoutError("MLJ250: homing timed out.")
            time.sleep(0.01)

    def move_to(self, position_um: float, timeout_s: float = 120.0) -> None:
        """Move to an absolute position in micrometers."""
        self._controller.move_absolute(position_um)
        self._wait_motion_done(timeout_s)

    def move_by(self, distance_um: float, timeout_s: float = 120.0) -> None:
        """Move by a relative distance in micrometers."""
        self._controller.move_relative(distance_um)
        self._wait_motion_done(timeout_s)

    def _wait_motion_done(self, timeout_s: float) -> None:
        start = time.monotonic()
        while True:
            self._controller.update_status()
            if not self._controller.moving and not self._controller.jogging:
                return
            if (time.monotonic() - start) > timeout_s:
                raise TimeoutError("MLJ250: motion timed out.")
            time.sleep(0.01)

    def halt(self) -> None:
        """Stop current motion immediately."""
        self._controller.stop()

    def close(self) -> None:
        """Release the serial port (reference-counted)."""
        port = self._port
        if port in MLJ250Axis._ref_counts:
            MLJ250Axis._ref_counts[port] -= 1
            if MLJ250Axis._ref_counts[port] <= 0:
                self._serial.close()
                del MLJ250Axis._shared_serials[port]
                del MLJ250Axis._ref_counts[port]
                logger.info("Closed MLJ250 serial port %s", port)
