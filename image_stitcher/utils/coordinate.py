"""
Coordinate transformation utilities.

Provides conversion between physical coordinates (um) and pixel coordinates,
and grid index calculations.
"""

from typing import Tuple


def um_to_pixel(position_um: float, origin_um: float, pixel_size_um: float) -> float:
    """
    Convert a physical position (um) to pixel coordinate.

    Parameters
    ----------
    position_um : float
        Physical position in micrometers.
    origin_um : float
        Origin position in micrometers (maps to pixel 0).
    pixel_size_um : float
        Size of one pixel in micrometers.

    Returns
    -------
    float
        Position in pixel coordinates.
    """
    return (position_um - origin_um) / pixel_size_um


def pixel_to_um(pixel: float, origin_um: float, pixel_size_um: float) -> float:
    """
    Convert a pixel coordinate to physical position (um).

    Parameters
    ----------
    pixel : float
        Position in pixel coordinates.
    origin_um : float
        Origin position in micrometers (pixel 0 maps here).
    pixel_size_um : float
        Size of one pixel in micrometers.

    Returns
    -------
    float
        Physical position in micrometers.
    """
    return pixel * pixel_size_um + origin_um


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


def grid_index_to_canvas_pixel(
    row: int, col: int, image_width: int, image_height: int, overlap_ratio: float
) -> Tuple[int, int]:
    """
    Convert grid indices to the top-left pixel position on the canvas
    (nominal position without feature-matching correction).

    Parameters
    ----------
    row : int
        Row index (0-based).
    col : int
        Column index (0-based).
    image_width : int
        Width of a single tile in pixels.
    image_height : int
        Height of a single tile in pixels.
    overlap_ratio : float
        Overlap ratio between adjacent tiles.

    Returns
    -------
    Tuple[int, int]
        (x_pixel, y_pixel) top-left corner on the canvas.
    """
    effective_width = int(image_width * (1.0 - overlap_ratio))
    effective_height = int(image_height * (1.0 - overlap_ratio))
    x_pixel = col * effective_width
    y_pixel = row * effective_height
    return (x_pixel, y_pixel)


def compute_overlap_region(
    pos1: Tuple[int, int],
    size1: Tuple[int, int],
    pos2: Tuple[int, int],
    size2: Tuple[int, int],
) -> Tuple[int, int, int, int]:
    """
    Compute the overlapping rectangle between two tiles on the canvas.

    Parameters
    ----------
    pos1 : Tuple[int, int]
        (x, y) top-left corner of tile 1 on canvas.
    size1 : Tuple[int, int]
        (width, height) of tile 1.
    pos2 : Tuple[int, int]
        (x, y) top-left corner of tile 2 on canvas.
    size2 : Tuple[int, int]
        (width, height) of tile 2.

    Returns
    -------
    Tuple[int, int, int, int]
        (x, y, width, height) of the overlapping region.
        Returns (0, 0, 0, 0) if there is no overlap.
    """
    x1_start, y1_start = pos1
    x1_end = x1_start + size1[0]
    y1_end = y1_start + size1[1]

    x2_start, y2_start = pos2
    x2_end = x2_start + size2[0]
    y2_end = y2_start + size2[1]

    # Intersection
    x_start = max(x1_start, x2_start)
    y_start = max(y1_start, y2_start)
    x_end = min(x1_end, x2_end)
    y_end = min(y1_end, y2_end)

    width = max(0, x_end - x_start)
    height = max(0, y_end - y_start)

    if width == 0 or height == 0:
        return (0, 0, 0, 0)

    return (x_start, y_start, width, height)
