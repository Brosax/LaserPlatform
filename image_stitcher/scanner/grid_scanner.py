"""
Grid scanner - computes scan positions for a serpentine (boustrophedon) path.

Given two corner points and step sizes, calculates the grid of positions
for the XY platform to visit during image acquisition.
"""

import logging
from typing import List, Tuple

from ..config import ScanConfig

logger = logging.getLogger(__name__)


class GridScanner:
    """
    Computes a serpentine grid scan path from a ScanConfig.

    The serpentine (boustrophedon) pattern minimizes travel distance by
    alternating the X-direction on each row:
    - Even rows: left to right
    - Odd rows: right to left

    This significantly reduces total scan time compared to a raster pattern
    that returns to the start of each row.
    """

    def __init__(self, config: ScanConfig):
        """
        Parameters
        ----------
        config : ScanConfig
            Scan configuration containing corner points and step sizes.
        """
        self._config = config
        self._positions: List[Tuple[int, int, float, float]] = []
        self._compute_grid()

    def _compute_grid(self):
        """Compute all grid positions in serpentine order."""
        cfg = self._config
        self._positions.clear()

        for row in range(cfg.num_rows):
            if row % 2 == 0:
                # Even row: left to right
                col_range = range(cfg.num_cols)
            else:
                # Odd row: right to left (serpentine)
                col_range = range(cfg.num_cols - 1, -1, -1)

            for col in col_range:
                x_um = cfg.origin_x + col * cfg.step_x_um
                y_um = cfg.origin_y + row * cfg.step_y_um
                self._positions.append((row, col, x_um, y_um))

        logger.info(
            f"Grid computed: {cfg.num_rows} rows x {cfg.num_cols} cols = "
            f"{len(self._positions)} positions, "
            f"step=({cfg.step_x_um:.1f}, {cfg.step_y_um:.1f}) um"
        )

    @property
    def positions(self) -> List[Tuple[int, int, float, float]]:
        """
        All scan positions in serpentine order.

        Returns
        -------
        List[Tuple[int, int, float, float]]
            List of (row, col, x_um, y_um) tuples.
        """
        return self._positions

    @property
    def grid_shape(self) -> Tuple[int, int]:
        """
        Grid dimensions.

        Returns
        -------
        Tuple[int, int]
            (num_rows, num_cols)
        """
        return (self._config.num_rows, self._config.num_cols)

    @property
    def total_positions(self) -> int:
        """Total number of scan positions."""
        return len(self._positions)

    def get_position(self, index: int) -> Tuple[int, int, float, float]:
        """
        Get a specific position by sequential index.

        Parameters
        ----------
        index : int
            Position index in the scan sequence.

        Returns
        -------
        Tuple[int, int, float, float]
            (row, col, x_um, y_um)
        """
        return self._positions[index]

    def get_position_by_grid(self, row: int, col: int) -> Tuple[float, float]:
        """
        Get the physical position for a given grid cell.

        Parameters
        ----------
        row : int
            Row index.
        col : int
            Column index.

        Returns
        -------
        Tuple[float, float]
            (x_um, y_um) physical position.
        """
        cfg = self._config
        x_um = cfg.origin_x + col * cfg.step_x_um
        y_um = cfg.origin_y + row * cfg.step_y_um
        return (x_um, y_um)

    def estimate_scan_time_s(self) -> float:
        """
        Estimate total scan time in seconds.

        This is a rough estimate based on:
        - Travel time between positions (using configured velocity)
        - Settle time at each position
        - A fixed user confirmation time estimate (5s per tile)

        Returns
        -------
        float
            Estimated scan time in seconds.
        """
        cfg = self._config
        user_confirm_time = 5.0  # estimated seconds per tile for user confirmation

        if len(self._positions) < 2:
            return cfg.settle_time_s + user_confirm_time

        total_time = 0.0
        for i in range(1, len(self._positions)):
            _, _, x_prev, y_prev = self._positions[i - 1]
            _, _, x_curr, y_curr = self._positions[i]

            # Travel distance
            distance = ((x_curr - x_prev) ** 2 + (y_curr - y_prev) ** 2) ** 0.5

            # Travel time (simplified: assumes constant velocity)
            if cfg.velocity_um_s > 0:
                travel_time = distance / cfg.velocity_um_s
            else:
                travel_time = 0.0

            # Add settle + user confirmation time
            total_time += travel_time + cfg.settle_time_s + user_confirm_time

        # Add first position settle + user confirmation
        total_time += cfg.settle_time_s + user_confirm_time

        return total_time
