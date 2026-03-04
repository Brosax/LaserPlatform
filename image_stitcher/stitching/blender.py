"""
Blending strategies for overlapping image tiles.

Provides weight mask generation for smooth blending in overlap regions,
avoiding hard seams in the composite image.
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)


class LinearBlender:
    """
    Linear gradient blending for overlap regions.

    Creates a linear ramp weight mask that transitions smoothly
    from 1.0 to 0.0 across the overlap width. This is the fastest
    blending method and works well for most cases with uniform illumination.
    """

    @staticmethod
    def create_weight_mask(
        image_height: int, image_width: int, overlap_x: int, overlap_y: int
    ) -> np.ndarray:
        """
        Create a 2D weight mask with linear fade at edges where overlap occurs.

        The mask has value 1.0 in the center and linearly fades to 0.0
        at the edges within the overlap region.

        Parameters
        ----------
        image_height : int
            Height of the image tile.
        image_width : int
            Width of the image tile.
        overlap_x : int
            Horizontal overlap width in pixels.
        overlap_y : int
            Vertical overlap height in pixels.

        Returns
        -------
        np.ndarray
            Float32 weight mask of shape (image_height, image_width).
        """
        mask = np.ones((image_height, image_width), dtype=np.float32)

        # Horizontal fade (left and right edges)
        if overlap_x > 0:
            ramp_x = np.linspace(0.0, 1.0, overlap_x, dtype=np.float32)
            # Left edge fade-in
            mask[:, :overlap_x] *= ramp_x[np.newaxis, :]
            # Right edge fade-out
            mask[:, -overlap_x:] *= ramp_x[np.newaxis, ::-1]

        # Vertical fade (top and bottom edges)
        if overlap_y > 0:
            ramp_y = np.linspace(0.0, 1.0, overlap_y, dtype=np.float32)
            # Top edge fade-in
            mask[:overlap_y, :] *= ramp_y[:, np.newaxis]
            # Bottom edge fade-out
            mask[-overlap_y:, :] *= ramp_y[::-1, np.newaxis]

        return mask

    @staticmethod
    def create_directional_weight_mask(
        image_height: int,
        image_width: int,
        fade_left: int = 0,
        fade_right: int = 0,
        fade_top: int = 0,
        fade_bottom: int = 0,
    ) -> np.ndarray:
        """
        Create a weight mask with directional fading.

        Allows specifying which edges should have fading independently,
        useful for edge/corner tiles that don't have neighbors on all sides.

        Parameters
        ----------
        image_height : int
            Height of the image tile.
        image_width : int
            Width of the image tile.
        fade_left : int
            Fade width at left edge.
        fade_right : int
            Fade width at right edge.
        fade_top : int
            Fade height at top edge.
        fade_bottom : int
            Fade height at bottom edge.

        Returns
        -------
        np.ndarray
            Float32 weight mask.
        """
        mask = np.ones((image_height, image_width), dtype=np.float32)

        if fade_left > 0:
            ramp = np.linspace(0.0, 1.0, fade_left, dtype=np.float32)
            mask[:, :fade_left] *= ramp[np.newaxis, :]

        if fade_right > 0:
            ramp = np.linspace(1.0, 0.0, fade_right, dtype=np.float32)
            mask[:, -fade_right:] *= ramp[np.newaxis, :]

        if fade_top > 0:
            ramp = np.linspace(0.0, 1.0, fade_top, dtype=np.float32)
            mask[:fade_top, :] *= ramp[:, np.newaxis]

        if fade_bottom > 0:
            ramp = np.linspace(1.0, 0.0, fade_bottom, dtype=np.float32)
            mask[-fade_bottom:, :] *= ramp[:, np.newaxis]

        return mask


class MultiBandBlender:
    """
    Multi-band (Laplacian pyramid) blending for overlap regions.

    More computationally expensive than linear blending, but handles
    brightness differences and vignetting much better by blending
    at multiple frequency scales.
    """

    def __init__(self, num_levels: int = 4):
        """
        Parameters
        ----------
        num_levels : int
            Number of pyramid levels. More levels = smoother blending
            but higher computation cost.
        """
        self._num_levels = num_levels

    def blend(self, img1: np.ndarray, img2: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """
        Blend two images using Laplacian pyramid multi-band blending.

        Parameters
        ----------
        img1 : np.ndarray
            First image (float32, same shape as img2).
        img2 : np.ndarray
            Second image (float32, same shape as img1).
        mask : np.ndarray
            Blend mask (float32, 0.0 = img2, 1.0 = img1).

        Returns
        -------
        np.ndarray
            Blended result (float32).
        """
        # Convert to float if needed
        img1_f = img1.astype(np.float32) if img1.dtype != np.float32 else img1
        img2_f = img2.astype(np.float32) if img2.dtype != np.float32 else img2
        mask_f = mask.astype(np.float32) if mask.dtype != np.float32 else mask

        # Build Laplacian pyramids for both images
        lap1 = self._build_laplacian_pyramid(img1_f)
        lap2 = self._build_laplacian_pyramid(img2_f)

        # Build Gaussian pyramid for the mask
        mask_pyr = self._build_gaussian_pyramid(mask_f)

        # Blend at each level
        blended_pyramid = []
        for l1, l2, m in zip(lap1, lap2, mask_pyr):
            blended = l1 * m + l2 * (1.0 - m)
            blended_pyramid.append(blended)

        # Reconstruct from blended pyramid
        return self._reconstruct_from_pyramid(blended_pyramid)

    def _build_gaussian_pyramid(self, image: np.ndarray) -> list:
        """Build a Gaussian pyramid."""
        import cv2

        pyramid = [image]
        current = image
        for _ in range(self._num_levels - 1):
            current = cv2.pyrDown(current)
            pyramid.append(current)
        return pyramid

    def _build_laplacian_pyramid(self, image: np.ndarray) -> list:
        """Build a Laplacian pyramid."""
        import cv2

        gaussian = self._build_gaussian_pyramid(image)
        laplacian = []
        for i in range(len(gaussian) - 1):
            size = (gaussian[i].shape[1], gaussian[i].shape[0])
            expanded = cv2.pyrUp(gaussian[i + 1], dstsize=size)
            lap = gaussian[i] - expanded
            laplacian.append(lap)
        # Last level is the low-frequency residual
        laplacian.append(gaussian[-1])
        return laplacian

    def _reconstruct_from_pyramid(self, pyramid: list) -> np.ndarray:
        """Reconstruct image from a Laplacian pyramid."""
        import cv2

        current = pyramid[-1]
        for i in range(len(pyramid) - 2, -1, -1):
            size = (pyramid[i].shape[1], pyramid[i].shape[0])
            current = cv2.pyrUp(current, dstsize=size)
            current = current + pyramid[i]
        return current
