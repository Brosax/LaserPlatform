"""
Scan configuration data classes.

Defines all parameters required for an S-pattern grid scan operation including
scan area, step sizes, camera settings, and motion parameters.
"""

from dataclasses import dataclass
from typing import Tuple
import math


@dataclass
class ScanConfig:
    """
    Configuration for an S-pattern grid scan operation.

    All spatial units are in micrometers (um) to match the AxisInterface convention.
    """

    # --- Scan area (defined by two corner points) ---
    corner1: Tuple[float, float] = (0.0, 0.0)
    """Start corner of scan area (x1, y1) in um."""

    corner2: Tuple[float, float] = (1000.0, 1000.0)
    """End corner of scan area (x2, y2) in um."""

    # --- Step sizes (user-defined) ---
    step_x_um: float = 500.0
    """Step size in X direction, in um."""

    step_y_um: float = 500.0
    """Step size in Y direction, in um."""

    # --- Camera parameters ---
    exposure_time_us: float = 1000.0
    """Camera exposure time in microseconds."""

    # --- Motion parameters ---
    settle_time_s: float = 0.3
    """Time to wait after platform movement before capturing, in seconds."""

    velocity_um_s: float = 1000.0
    """Platform movement velocity in um/s."""

    # --- Output ---
    output_directory: str = ""
    """Directory for saving captured images."""

    # --- Computed properties ---

    @property
    def scan_range_x(self) -> float:
        """Total scan range in X direction, in um."""
        x1, _ = self.corner1
        x2, _ = self.corner2
        return abs(x2 - x1)

    @property
    def scan_range_y(self) -> float:
        """Total scan range in Y direction, in um."""
        _, y1 = self.corner1
        _, y2 = self.corner2
        return abs(y2 - y1)

    @property
    def num_cols(self) -> int:
        """Number of columns in the grid."""
        if self.scan_range_x <= 0 or self.step_x_um <= 0:
            return 1
        return max(1, math.floor(self.scan_range_x / self.step_x_um) + 1)

    @property
    def num_rows(self) -> int:
        """Number of rows in the grid."""
        if self.scan_range_y <= 0 or self.step_y_um <= 0:
            return 1
        return max(1, math.floor(self.scan_range_y / self.step_y_um) + 1)

    @property
    def total_tiles(self) -> int:
        """Total number of positions to capture."""
        return self.num_rows * self.num_cols

    @property
    def origin_x(self) -> float:
        """Scan origin X coordinate (minimum X), in um."""
        return min(self.corner1[0], self.corner2[0])

    @property
    def origin_y(self) -> float:
        """Scan origin Y coordinate (minimum Y), in um."""
        return min(self.corner1[1], self.corner2[1])

    def validate(self) -> list[str]:
        """
        Validate the configuration and return a list of error messages.
        Returns an empty list if configuration is valid.
        """
        errors = []
        if self.step_x_um <= 0:
            errors.append(f"X step size must be positive, got {self.step_x_um}")
        if self.step_y_um <= 0:
            errors.append(f"Y step size must be positive, got {self.step_y_um}")
        if self.exposure_time_us <= 0:
            errors.append(
                f"Exposure time must be positive, got {self.exposure_time_us}"
            )
        if self.settle_time_s < 0:
            errors.append(f"Settle time cannot be negative, got {self.settle_time_s}")
        if self.corner1 == self.corner2:
            errors.append("Corner points must define a non-zero area")
        return errors
