"""
Scan configuration data classes.

Defines all parameters required for a grid scan operation including
scan area, camera settings, overlap ratio, and motion parameters.
"""

from dataclasses import dataclass, field
from typing import Tuple, Optional
import math


@dataclass
class ScanConfig:
    """
    Configuration for a grid scan operation.

    All spatial units are in micrometers (um) to match the AxisInterface convention.
    """

    # --- Scan area (defined by two corner points) ---
    corner1: Tuple[float, float] = (0.0, 0.0)
    """Top-left corner of scan area (x1, y1) in um."""

    corner2: Tuple[float, float] = (1000.0, 1000.0)
    """Bottom-right corner of scan area (x2, y2) in um."""

    z_position: float = 0.0
    """Fixed Z-axis position during scan, in um."""

    # --- Overlap parameters ---
    overlap_ratio: float = 0.2
    """Overlap ratio between adjacent tiles (0.0 to 0.5). Default 20%."""

    # --- Camera parameters ---
    pixel_size_um: float = 5.5
    """Physical size of one pixel projected onto the sample, in um/pixel."""

    image_width: int = 2048
    """Single frame width in pixels."""

    image_height: int = 2048
    """Single frame height in pixels."""

    exposure_time_us: float = 1000.0
    """Camera exposure time in microseconds."""

    bit_depth: int = 14
    """Camera bit depth (e.g. 14 for Mono14)."""

    # --- Motion parameters ---
    settle_time_s: float = 0.3
    """Time to wait after platform movement before capturing, in seconds."""

    velocity_um_s: float = 1000.0
    """Platform movement velocity in um/s."""

    acceleration_um_s2: float = 500.0
    """Platform movement acceleration in um/s^2."""

    # --- Feature matching ---
    matching_method: str = "ORB"
    """Feature matching algorithm: 'ORB' (fast) or 'SIFT' (accurate)."""

    fallback_to_position: bool = True
    """If feature matching fails, fall back to motor-position-based placement."""

    # --- Output ---
    output_directory: str = ""
    """Directory for saving output images and intermediate tiles."""

    save_individual_tiles: bool = False
    """Whether to save each captured tile individually."""

    # --- Computed properties ---

    @property
    def field_of_view_x_um(self) -> float:
        """Field of view width in um."""
        return self.image_width * self.pixel_size_um

    @property
    def field_of_view_y_um(self) -> float:
        """Field of view height in um."""
        return self.image_height * self.pixel_size_um

    @property
    def step_x_um(self) -> float:
        """Effective step size in X direction (accounting for overlap), in um."""
        return self.field_of_view_x_um * (1.0 - self.overlap_ratio)

    @property
    def step_y_um(self) -> float:
        """Effective step size in Y direction (accounting for overlap), in um."""
        return self.field_of_view_y_um * (1.0 - self.overlap_ratio)

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
        if self.scan_range_x <= 0:
            return 1
        return max(1, math.ceil(self.scan_range_x / self.step_x_um) + 1)

    @property
    def num_rows(self) -> int:
        """Number of rows in the grid."""
        if self.scan_range_y <= 0:
            return 1
        return max(1, math.ceil(self.scan_range_y / self.step_y_um) + 1)

    @property
    def total_tiles(self) -> int:
        """Total number of tiles to capture."""
        return self.num_rows * self.num_cols

    @property
    def origin_x(self) -> float:
        """Scan origin X coordinate (minimum X), in um."""
        return min(self.corner1[0], self.corner2[0])

    @property
    def origin_y(self) -> float:
        """Scan origin Y coordinate (minimum Y), in um."""
        return min(self.corner1[1], self.corner2[1])

    @property
    def overlap_pixels_x(self) -> int:
        """Overlap width between adjacent tiles in pixels."""
        return int(self.image_width * self.overlap_ratio)

    @property
    def overlap_pixels_y(self) -> int:
        """Overlap height between adjacent tiles in pixels."""
        return int(self.image_height * self.overlap_ratio)

    @property
    def estimated_canvas_width(self) -> int:
        """Estimated final composite image width in pixels."""
        effective_width = int(self.image_width * (1.0 - self.overlap_ratio))
        return effective_width * (self.num_cols - 1) + self.image_width

    @property
    def estimated_canvas_height(self) -> int:
        """Estimated final composite image height in pixels."""
        effective_height = int(self.image_height * (1.0 - self.overlap_ratio))
        return effective_height * (self.num_rows - 1) + self.image_height

    @property
    def estimated_memory_mb(self) -> float:
        """Estimated memory usage for the canvas in MB."""
        bytes_per_pixel = 2 if self.bit_depth > 8 else 1
        # Canvas + weight map (float32)
        canvas_bytes = (
            self.estimated_canvas_width * self.estimated_canvas_height * bytes_per_pixel
        )
        weight_bytes = self.estimated_canvas_width * self.estimated_canvas_height * 4
        return (canvas_bytes + weight_bytes) / (1024 * 1024)

    def validate(self) -> list[str]:
        """
        Validate the configuration and return a list of error messages.
        Returns an empty list if configuration is valid.
        """
        errors = []
        if self.overlap_ratio < 0.0 or self.overlap_ratio > 0.5:
            errors.append(
                f"Overlap ratio must be between 0.0 and 0.5, got {self.overlap_ratio}"
            )
        if self.pixel_size_um <= 0:
            errors.append(f"Pixel size must be positive, got {self.pixel_size_um}")
        if self.image_width <= 0 or self.image_height <= 0:
            errors.append(
                f"Image dimensions must be positive: {self.image_width}x{self.image_height}"
            )
        if self.exposure_time_us <= 0:
            errors.append(
                f"Exposure time must be positive, got {self.exposure_time_us}"
            )
        if self.settle_time_s < 0:
            errors.append(f"Settle time cannot be negative, got {self.settle_time_s}")
        if self.corner1 == self.corner2:
            errors.append("Corner points must define a non-zero area")
        if self.matching_method not in ("ORB", "SIFT"):
            errors.append(f"Unknown matching method: {self.matching_method}")
        if self.estimated_memory_mb > 4096:
            errors.append(
                f"Estimated memory usage ({self.estimated_memory_mb:.0f} MB) exceeds 4 GB. "
                "Consider reducing the scan area or increasing pixel size."
            )
        return errors
