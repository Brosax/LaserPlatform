"""
Incremental image compositor.

Pre-allocates a large canvas and places tiles incrementally as they are
captured and aligned. Supports real-time preview generation and
weighted blending in overlap regions.
"""

import logging
from typing import Optional, Tuple

import cv2
import numpy as np

from ..config import ScanConfig
from .blender import LinearBlender

logger = logging.getLogger(__name__)


class Compositor:
    """
    Incremental tile compositor with weighted blending.

    Pre-allocates a canvas based on the expected grid dimensions,
    then places each tile at its computed position with linear
    weight blending in overlap regions.

    The canvas uses uint16 for preserving 14-bit NIR image depth,
    with a separate float32 weight accumulator for normalization.
    """

    def __init__(self, config: ScanConfig):
        """
        Parameters
        ----------
        config : ScanConfig
            Scan configuration.
        """
        self._config = config
        self._canvas_width = config.estimated_canvas_width
        self._canvas_height = config.estimated_canvas_height

        # Pre-allocate canvas and weight map
        # Use float64 accumulator for precision during blending
        self._canvas = np.zeros(
            (self._canvas_height, self._canvas_width), dtype=np.float64
        )
        self._weight_map = np.zeros(
            (self._canvas_height, self._canvas_width), dtype=np.float64
        )

        # Track which tiles have been placed
        self._tiles_placed = 0
        self._tile_positions: dict[Tuple[int, int], Tuple[int, int]] = {}

        # Pre-compute the base weight mask for a single tile
        self._base_weight = LinearBlender.create_weight_mask(
            config.image_height,
            config.image_width,
            config.overlap_pixels_x,
            config.overlap_pixels_y,
        ).astype(np.float64)

        logger.info(
            f"Compositor initialized: canvas={self._canvas_width}x{self._canvas_height}, "
            f"estimated memory={config.estimated_memory_mb:.1f} MB"
        )

    def add_tile(
        self,
        row: int,
        col: int,
        image: np.ndarray,
        precise_offset: Optional[Tuple[float, float]] = None,
    ):
        """
        Place a tile onto the canvas.

        Parameters
        ----------
        row : int
            Grid row index.
        col : int
            Grid column index.
        image : np.ndarray
            Tile image (2D, any dtype).
        precise_offset : Optional[Tuple[float, float]]
            If provided, (dx, dy) correction from feature matching in pixels.
            Added to the nominal grid position.
        """
        # Compute nominal pixel position on canvas
        cfg = self._config
        effective_w = int(cfg.image_width * (1.0 - cfg.overlap_ratio))
        effective_h = int(cfg.image_height * (1.0 - cfg.overlap_ratio))

        x_pos = col * effective_w
        y_pos = row * effective_h

        # Apply feature-matching correction
        if precise_offset is not None:
            x_pos += int(round(precise_offset[0]))
            y_pos += int(round(precise_offset[1]))

        # Clamp to canvas bounds
        x_pos = max(0, x_pos)
        y_pos = max(0, y_pos)

        # Compute actual placement region (handle edge clipping)
        tile_h, tile_w = image.shape[:2]

        # Source region (from the tile)
        src_x_start = max(0, -x_pos)
        src_y_start = max(0, -y_pos)
        src_x_end = min(tile_w, self._canvas_width - x_pos)
        src_y_end = min(tile_h, self._canvas_height - y_pos)

        # Destination region (on the canvas)
        dst_x_start = x_pos + src_x_start
        dst_y_start = y_pos + src_y_start
        dst_x_end = x_pos + src_x_end
        dst_y_end = y_pos + src_y_end

        if dst_x_start >= dst_x_end or dst_y_start >= dst_y_end:
            logger.warning(f"Tile ({row},{col}) is out of canvas bounds, skipping.")
            return

        # Extract the relevant portion of the tile and weight mask
        tile_region = image[src_y_start:src_y_end, src_x_start:src_x_end].astype(
            np.float64
        )
        weight_region = self._base_weight[src_y_start:src_y_end, src_x_start:src_x_end]

        # Compute directional weight mask for edge/corner tiles
        weight = self._compute_tile_weight(row, col, tile_h, tile_w)
        weight_region = weight[src_y_start:src_y_end, src_x_start:src_x_end]

        # Accumulate weighted tile and weights
        self._canvas[dst_y_start:dst_y_end, dst_x_start:dst_x_end] += (
            tile_region * weight_region
        )
        self._weight_map[dst_y_start:dst_y_end, dst_x_start:dst_x_end] += weight_region

        # Record placement
        self._tile_positions[(row, col)] = (x_pos, y_pos)
        self._tiles_placed += 1

        logger.debug(
            f"Tile ({row},{col}) placed at ({x_pos},{y_pos}), "
            f"tiles placed: {self._tiles_placed}/{self._config.total_tiles}"
        )

    def _compute_tile_weight(
        self, row: int, col: int, tile_h: int, tile_w: int
    ) -> np.ndarray:
        """
        Compute the weight mask for a tile based on its grid position.

        Edge and corner tiles have reduced fading on the outer edges
        since they don't overlap with neighbors there.
        """
        cfg = self._config
        num_rows = cfg.num_rows
        num_cols = cfg.num_cols

        fade_left = cfg.overlap_pixels_x if col > 0 else 0
        fade_right = cfg.overlap_pixels_x if col < num_cols - 1 else 0
        fade_top = cfg.overlap_pixels_y if row > 0 else 0
        fade_bottom = cfg.overlap_pixels_y if row < num_rows - 1 else 0

        return LinearBlender.create_directional_weight_mask(
            tile_h,
            tile_w,
            fade_left=fade_left,
            fade_right=fade_right,
            fade_top=fade_top,
            fade_bottom=fade_bottom,
        ).astype(np.float64)

    def get_current_preview(self, scale: float = 0.25) -> np.ndarray:
        """
        Get a scaled preview of the current composite state.

        Parameters
        ----------
        scale : float
            Scale factor for the preview (0.25 = quarter size).

        Returns
        -------
        np.ndarray
            uint8 preview image.
        """
        # Normalize canvas by weights
        with np.errstate(divide="ignore", invalid="ignore"):
            normalized = np.where(
                self._weight_map > 0, self._canvas / self._weight_map, 0
            )

        # Scale to uint8 for preview
        if normalized.max() > 0:
            preview = (normalized / normalized.max() * 255).astype(np.uint8)
        else:
            preview = np.zeros_like(normalized, dtype=np.uint8)

        # Resize for preview
        if scale != 1.0:
            new_w = max(1, int(self._canvas_width * scale))
            new_h = max(1, int(self._canvas_height * scale))
            preview = cv2.resize(preview, (new_w, new_h), interpolation=cv2.INTER_AREA)

        return preview

    def finalize(self) -> np.ndarray:
        """
        Finalize the composite image.

        Normalizes by the accumulated weights and converts to uint16.

        Returns
        -------
        np.ndarray
            Final composite image as uint16.
        """
        # Normalize canvas by weight map
        with np.errstate(divide="ignore", invalid="ignore"):
            result = np.where(self._weight_map > 0, self._canvas / self._weight_map, 0)

        # Crop to the actual content area (remove unused canvas border)
        result = self._crop_to_content(result)

        # Convert to uint16
        result_uint16 = np.clip(result, 0, 65535).astype(np.uint16)

        logger.info(
            f"Composite finalized: {result_uint16.shape}, tiles={self._tiles_placed}"
        )
        return result_uint16

    def _crop_to_content(self, image: np.ndarray) -> np.ndarray:
        """
        Crop the image to remove empty borders.

        Uses the weight map to determine which pixels have data.
        """
        # Find rows and columns with content
        row_has_data = np.any(self._weight_map > 0, axis=1)
        col_has_data = np.any(self._weight_map > 0, axis=0)

        if not np.any(row_has_data) or not np.any(col_has_data):
            return image

        row_indices = np.where(row_has_data)[0]
        col_indices = np.where(col_has_data)[0]

        y_start = row_indices[0]
        y_end = row_indices[-1] + 1
        x_start = col_indices[0]
        x_end = col_indices[-1] + 1

        return image[y_start:y_end, x_start:x_end]

    @property
    def tiles_placed(self) -> int:
        """Number of tiles placed so far."""
        return self._tiles_placed

    @property
    def canvas_shape(self) -> Tuple[int, int]:
        """Canvas dimensions (height, width)."""
        return (self._canvas_height, self._canvas_width)
