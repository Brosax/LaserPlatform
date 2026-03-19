"""
XY(Z) Table — lightweight wrapper around SMC100Axis instances.

Provides a simple interface for XY movement, with optional Z axis
support. No dependency on ``analyzr2`` or the ``xyz_table`` package.
"""

import logging
from typing import Optional, Protocol

from .smc100_axis import SMC100Axis

logger = logging.getLogger(__name__)


class _AxisLike(Protocol):
    @property
    def position(self) -> float: ...

    def move_to(self, position_um: float) -> None: ...

    def move_by(self, distance_um: float) -> None: ...

    def homing(self) -> None: ...

    def halt(self) -> None: ...

    def close(self) -> None: ...


class XYTable:
    """
    Two-axis (X + Y) motion controller, with optional Z axis.

    Parameters
    ----------
    x_axis : SMC100Axis
        X axis controller.
    y_axis : SMC100Axis
        Y axis controller.
    z_axis : _AxisLike, optional
        Z axis controller. If None, Z-related methods are no-ops or
        raise informative errors.
    """

    def __init__(
        self,
        x_axis: SMC100Axis,
        y_axis: SMC100Axis,
        z_axis: Optional[_AxisLike] = None,
    ):
        self.x: SMC100Axis = x_axis
        self.y: SMC100Axis = y_axis
        self.z: Optional[_AxisLike] = z_axis

    # ---- Properties -------------------------------------------------- #

    @property
    def has_z(self) -> bool:
        """Whether a Z axis is attached."""
        return self.z is not None

    # ---- Position ---------------------------------------------------- #

    @property
    def position(self) -> tuple[float, float]:
        """Current (x, y) position in micrometers."""
        return (self.x.position, self.y.position)

    @property
    def position_z(self) -> Optional[float]:
        """Current Z position in micrometers, or None if no Z axis."""
        if self.z is not None:
            return self.z.position
        return None

    def update_position(self) -> tuple[float, float]:
        """Query hardware and return refreshed (x, y) in um."""
        self.x._update_status()
        self.y._update_status()
        return self.position

    def update_position_z(self) -> Optional[float]:
        """Query Z hardware and return refreshed Z position in um."""
        if self.z is not None:
            if hasattr(self.z, "_update_status"):
                self.z._update_status()
            return self.z.position
        return None

    # ---- XY Movement ------------------------------------------------- #

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

    # ---- Z Movement -------------------------------------------------- #

    def move_z(self, z_um: float) -> None:
        """Move Z axis to absolute position (blocking)."""
        if self.z is None:
            raise RuntimeError("Z axis is not connected.")
        self.z.move_to(z_um)

    def jog_z(self, distance_um: float) -> None:
        """Relative move on Z axis (blocking)."""
        if self.z is None:
            raise RuntimeError("Z axis is not connected.")
        self.z.move_by(distance_um)

    # ---- Homing ------------------------------------------------------ #

    def homing(self) -> None:
        """Home X and Y axes sequentially."""
        self.x.homing()
        self.y.homing()

    def homing_z(self) -> None:
        """Home Z axis."""
        if self.z is None:
            raise RuntimeError("Z axis is not connected.")
        self.z.homing()

    # ---- Stop / Close ------------------------------------------------ #

    def halt(self) -> None:
        """Stop all motion immediately (all connected axes)."""
        self.x.halt()
        self.y.halt()
        if self.z is not None:
            self.z.halt()

    def close(self) -> None:
        """Close all axis connections (reference-counted serial ports)."""
        self.x.close()
        self.y.close()
        if self.z is not None:
            self.z.close()
        logger.info("XY table closed.")
