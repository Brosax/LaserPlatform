"""
Coordinate transformation utilities.

Provides conversion between grid indices and physical coordinates (um).
"""

from typing import Tuple


def grid_index_to_position(
    row: int,
    col: int,
    origin_x_um: float,
    origin_y_um: float,
    step_x_um: float,
    step_y_um: float,
) -> Tuple[float, float]:
    """
    Convert grid indices (row, col) to physical XY position (um).

    Parameters
    ----------
    row : int
        Row index (0-based).
    col : int
        Column index (0-based).
    origin_x_um : float
        X position of the grid origin, in um.
    origin_y_um : float
        Y position of the grid origin, in um.
    step_x_um : float
        Step size in X direction, in um.
    step_y_um : float
        Step size in Y direction, in um.

    Returns
    -------
    Tuple[float, float]
        (x_um, y_um) physical position.
    """
    x_um = origin_x_um + col * step_x_um
    y_um = origin_y_um + row * step_y_um
    return (x_um, y_um)
