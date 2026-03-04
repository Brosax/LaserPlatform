"""
XY Table — lightweight wrapper around two SMC100Axis instances.

Provides a simple interface for XY movement without any dependency
on ``analyzr2`` or the ``xyz_table`` package.
"""

import logging
from typing import Optional

from .smc100_axis import SMC100Axis

logger = logging.getLogger(__name__)


class XYTable:
    """
    Two-axis (X + Y) motion controller.

    Parameters
    ----------
    x_axis : SMC100Axis
        X axis controller.
    y_axis : SMC100Axis
        Y axis controller.
    """

    def __init__(self, x_axis: SMC100Axis, y_axis: SMC100Axis):
        self.x: SMC100Axis = x_axis
        self.y: SMC100Axis = y_axis

    # ---- Position ---------------------------------------------------- #

    @property
    def position(self) -> tuple[float, float]:
        """Current (x, y) position in micrometers."""
        return (self.x.position, self.y.position)

    def update_position(self) -> tuple[float, float]:
        """Query hardware and return refreshed (x, y) in um."""
        self.x._update_status()
        self.y._update_status()
        return self.position

    # ---- Movement ---------------------------------------------------- #

    def move_to(self, x_um: float, y_um: float) -> None:
        """Move both axes to absolute positions (blocking, sequential)."""
        self.x.move_to(x_um)
        self.y.move_to(y_um)

    def move_x(self, x_um: float) -> None:
        """Move X axis to absolute position (blocking)."""
        self.x.move_to(x_um)

    def move_y(self, y_um: float) -> None:
        """Move Y axis to absolute position (blocking)."""
        self.y.move_to(y_um)

    def jog_x(self, distance_um: float) -> None:
        """Relative move on X axis (blocking)."""
        self.x.move_by(distance_um)

    def jog_y(self, distance_um: float) -> None:
        """Relative move on Y axis (blocking)."""
        self.y.move_by(distance_um)

    # ---- Homing ------------------------------------------------------ #

    def homing(self) -> None:
        """Home both axes sequentially."""
        self.x.homing()
        self.y.homing()

    # ---- Stop / Close ------------------------------------------------ #

    def halt(self) -> None:
        """Stop all motion immediately."""
        self.x.halt()
        self.y.halt()

    def close(self) -> None:
        """Close both axis connections (reference-counted serial ports)."""
        self.x.close()
        self.y.close()
        logger.info("XY table closed.")
