"""
Image I/O utilities.

Provides functions for saving composite images in TIFF (16-bit) and PNG (8-bit) formats.
"""

import os
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def save_tiff_16bit(image: np.ndarray, filepath: str) -> bool:
    """
    Save an image as a 16-bit TIFF file.

    Parameters
    ----------
    image : np.ndarray
        Image array. Will be converted to uint16.
    filepath : str
        Output file path. Extension will be forced to .tiff.

    Returns
    -------
    bool
        True if save was successful, False otherwise.
    """
    try:
        import tifffile
    except ImportError:
        logger.error("tifffile is not installed. Install it with: pip install tifffile")
        return False

    try:
        # Ensure .tiff extension
        base, _ = os.path.splitext(filepath)
        filepath = base + ".tiff"

        # Ensure output directory exists
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

        # Convert to uint16
        img_16 = _normalize_to_uint16(image)

        tifffile.imwrite(filepath, img_16)
        logger.info(f"Saved 16-bit TIFF: {filepath} ({img_16.shape})")
        return True

    except Exception as e:
        logger.error(f"Failed to save TIFF: {e}")
        return False


def save_png_8bit(image: np.ndarray, filepath: str) -> bool:
    """
    Save an image as an 8-bit PNG file.

    Parameters
    ----------
    image : np.ndarray
        Image array. Will be normalized and converted to uint8.
    filepath : str
        Output file path. Extension will be forced to .png.

    Returns
    -------
    bool
        True if save was successful, False otherwise.
    """
    try:
        import cv2
    except ImportError:
        logger.error(
            "opencv-python is not installed. Install it with: pip install opencv-python"
        )
        return False

    try:
        # Ensure .png extension
        base, _ = os.path.splitext(filepath)
        filepath = base + ".png"

        # Ensure output directory exists
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

        # Convert to uint8
        img_8 = _normalize_to_uint8(image)

        cv2.imwrite(filepath, img_8)
        logger.info(f"Saved 8-bit PNG: {filepath} ({img_8.shape})")
        return True

    except Exception as e:
        logger.error(f"Failed to save PNG: {e}")
        return False


def save_both(image: np.ndarray, filepath_base: str) -> dict[str, bool]:
    """
    Save the image in both TIFF (16-bit) and PNG (8-bit) formats.

    Parameters
    ----------
    image : np.ndarray
        Image array.
    filepath_base : str
        Base file path (without extension).

    Returns
    -------
    dict[str, bool]
        Dictionary with 'tiff' and 'png' keys indicating success.
    """
    return {
        "tiff": save_tiff_16bit(image, filepath_base),
        "png": save_png_8bit(image, filepath_base),
    }


def _normalize_to_uint16(image: np.ndarray) -> np.ndarray:
    """
    Normalize an image to uint16 range [0, 65535].

    If the image is already uint16, return as-is.
    If float, assume [0, 1] range and scale.
    If other integer types, scale appropriately.
    """
    if image.dtype == np.uint16:
        return image

    if image.dtype == np.float32 or image.dtype == np.float64:
        # Assume [0, 1] range
        clipped = np.clip(image, 0.0, 1.0)
        return (clipped * 65535).astype(np.uint16)

    if image.dtype == np.uint8:
        return image.astype(np.uint16) * 257  # 255 -> 65535

    # Generic: scale from actual range to uint16
    img_min = float(np.min(image))
    img_max = float(np.max(image))
    if img_max == img_min:
        return np.zeros(image.shape, dtype=np.uint16)
    normalized = (image.astype(np.float64) - img_min) / (img_max - img_min)
    return (normalized * 65535).astype(np.uint16)


def _normalize_to_uint8(image: np.ndarray) -> np.ndarray:
    """
    Normalize an image to uint8 range [0, 255].

    If the image is already uint8, return as-is.
    If uint16, scale down by bit shift.
    If float, assume [0, 1] range and scale.
    """
    if image.dtype == np.uint8:
        return image

    if image.dtype == np.uint16:
        return (image >> 8).astype(np.uint8)

    if image.dtype == np.float32 or image.dtype == np.float64:
        clipped = np.clip(image, 0.0, 1.0)
        return (clipped * 255).astype(np.uint8)

    # Generic: scale from actual range to uint8
    img_min = float(np.min(image))
    img_max = float(np.max(image))
    if img_max == img_min:
        return np.zeros(image.shape, dtype=np.uint8)
    normalized = (image.astype(np.float64) - img_min) / (img_max - img_min)
    return (normalized * 255).astype(np.uint8)
