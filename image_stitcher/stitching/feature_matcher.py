"""
Feature matcher for image alignment.

Provides feature detection and matching between overlapping image tiles
to compute precise sub-pixel offsets for accurate stitching.
Supports ORB (fast) and SIFT (accurate) methods, with automatic
fallback if matching fails.
"""

import logging
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class FeatureMatcher:
    """
    Feature-based image alignment for overlapping tiles.

    Detects keypoints in the overlap region between two adjacent tiles,
    matches them, and computes the precise translation offset using RANSAC.

    For NIR images which typically have sufficient texture, ORB provides
    a good speed/accuracy tradeoff. SIFT is available as a fallback for
    images with less distinctive features.
    """

    def __init__(self, method: str = "ORB", max_features: int = 2000):
        """
        Parameters
        ----------
        method : str
            Feature detection method: 'ORB' or 'SIFT'.
        max_features : int
            Maximum number of features to detect.
        """
        self._method = method.upper()
        self._max_features = max_features

        if self._method == "ORB":
            self._detector = cv2.ORB_create(nfeatures=max_features)
            self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        elif self._method == "SIFT":
            self._detector = cv2.SIFT_create(nfeatures=max_features)
            self._matcher = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
        else:
            raise ValueError(
                f"Unknown feature matching method: {method}. Use 'ORB' or 'SIFT'."
            )

    def compute_offset(
        self,
        img_ref: np.ndarray,
        img_new: np.ndarray,
        expected_offset: Tuple[float, float],
        overlap_pixels: Tuple[int, int],
        min_matches: int = 8,
        ransac_threshold: float = 5.0,
    ) -> Optional[Tuple[float, float]]:
        """
        Compute the precise pixel offset of img_new relative to img_ref.

        Only the overlapping region is analyzed for feature matching.

        Parameters
        ----------
        img_ref : np.ndarray
            Reference image (2D grayscale).
        img_new : np.ndarray
            New image to align (2D grayscale).
        expected_offset : Tuple[float, float]
            Expected (dx, dy) offset in pixels, from motor position data.
        overlap_pixels : Tuple[int, int]
            Expected overlap in (x, y) pixels between tiles.
        min_matches : int
            Minimum number of inlier matches required.
        ransac_threshold : float
            RANSAC inlier threshold in pixels.

        Returns
        -------
        Optional[Tuple[float, float]]
            Precise (dx, dy) offset in pixels, or None if matching failed.
        """
        try:
            # Extract overlapping regions
            roi_ref, roi_new = self._extract_overlap_rois(
                img_ref, img_new, expected_offset, overlap_pixels
            )

            if roi_ref is None or roi_new is None:
                logger.warning("Could not extract overlap ROIs.")
                return None

            # Convert to 8-bit for feature detection
            roi_ref_8 = self._to_uint8(roi_ref)
            roi_new_8 = self._to_uint8(roi_new)

            # Detect and match features
            kp1, des1 = self._detector.detectAndCompute(roi_ref_8, None)
            kp2, des2 = self._detector.detectAndCompute(roi_new_8, None)

            if (
                des1 is None
                or des2 is None
                or len(kp1) < min_matches
                or len(kp2) < min_matches
            ):
                logger.warning(
                    f"Insufficient features: ref={len(kp1) if kp1 else 0}, "
                    f"new={len(kp2) if kp2 else 0}"
                )
                return None

            # Match features using KNN
            matches = self._matcher.knnMatch(des1, des2, k=2)

            # Apply Lowe's ratio test
            good_matches = []
            for match_pair in matches:
                if len(match_pair) == 2:
                    m, n = match_pair
                    if m.distance < 0.75 * n.distance:
                        good_matches.append(m)

            if len(good_matches) < min_matches:
                logger.warning(
                    f"Insufficient good matches: {len(good_matches)} < {min_matches}"
                )
                return None

            # Extract matched point coordinates
            pts_ref = np.float32([kp1[m.queryIdx].pt for m in good_matches])
            pts_new = np.float32([kp2[m.trainIdx].pt for m in good_matches])

            # Estimate translation using RANSAC
            offset = self._estimate_translation(
                pts_ref, pts_new, ransac_threshold, min_matches
            )

            if offset is None:
                return None

            # Convert ROI-local offset to full-image offset
            dx_roi, dy_roi = offset
            dx = expected_offset[0] + dx_roi
            dy = expected_offset[1] + dy_roi

            logger.debug(
                f"Feature matching: expected=({expected_offset[0]:.1f}, {expected_offset[1]:.1f}), "
                f"measured=({dx:.1f}, {dy:.1f}), "
                f"correction=({dx_roi:.1f}, {dy_roi:.1f}), "
                f"matches={len(good_matches)}"
            )

            return (dx, dy)

        except Exception as e:
            logger.error(f"Feature matching failed: {e}")
            return None

    def _extract_overlap_rois(
        self,
        img_ref: np.ndarray,
        img_new: np.ndarray,
        expected_offset: Tuple[float, float],
        overlap_pixels: Tuple[int, int],
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Extract the overlapping regions from two adjacent tiles.

        Parameters
        ----------
        img_ref : np.ndarray
            Reference image.
        img_new : np.ndarray
            New image.
        expected_offset : Tuple[float, float]
            Expected (dx, dy) offset in pixels.
        overlap_pixels : Tuple[int, int]
            Expected overlap (width, height) in pixels.

        Returns
        -------
        Tuple[Optional[np.ndarray], Optional[np.ndarray]]
            (roi_ref, roi_new) overlapping regions, or (None, None) if invalid.
        """
        h, w = img_ref.shape[:2]
        dx, dy = expected_offset
        overlap_x, overlap_y = overlap_pixels

        # Determine overlap direction based on expected offset
        if abs(dx) > abs(dy):
            # Horizontal neighbor
            if dx > 0:
                # New tile is to the right
                roi_ref = img_ref[:, w - overlap_x :]
                roi_new = img_new[:, :overlap_x]
            else:
                # New tile is to the left
                roi_ref = img_ref[:, :overlap_x]
                roi_new = img_new[:, w - overlap_x :]
        else:
            # Vertical neighbor
            if dy > 0:
                # New tile is below
                roi_ref = img_ref[h - overlap_y :, :]
                roi_new = img_new[:overlap_y, :]
            else:
                # New tile is above
                roi_ref = img_ref[:overlap_y, :]
                roi_new = img_new[h - overlap_y :, :]

        # Validate ROI sizes
        if roi_ref.size == 0 or roi_new.size == 0:
            return (None, None)

        # Ensure same shape (crop to minimum)
        min_h = min(roi_ref.shape[0], roi_new.shape[0])
        min_w = min(roi_ref.shape[1], roi_new.shape[1])
        roi_ref = roi_ref[:min_h, :min_w]
        roi_new = roi_new[:min_h, :min_w]

        return (roi_ref, roi_new)

    def _estimate_translation(
        self,
        pts_ref: np.ndarray,
        pts_new: np.ndarray,
        ransac_threshold: float,
        min_inliers: int,
    ) -> Optional[Tuple[float, float]]:
        """
        Estimate a pure translation from matched point pairs using RANSAC.

        Parameters
        ----------
        pts_ref : np.ndarray
            Reference points (N, 2).
        pts_new : np.ndarray
            Matched points (N, 2).
        ransac_threshold : float
            RANSAC inlier distance threshold.
        min_inliers : int
            Minimum required inliers.

        Returns
        -------
        Optional[Tuple[float, float]]
            (dx, dy) translation, or None if estimation failed.
        """
        # Compute all pairwise translations
        translations = pts_new - pts_ref  # (N, 2)

        # Use RANSAC to find the dominant translation
        best_inliers = 0
        best_translation = None
        n_points = len(translations)

        # Adaptive number of iterations
        n_iterations = min(200, max(50, n_points * 3))

        rng = np.random.default_rng(seed=42)

        for _ in range(n_iterations):
            # Sample one translation
            idx = rng.integers(0, n_points)
            candidate = translations[idx]

            # Count inliers
            residuals = np.linalg.norm(translations - candidate, axis=1)
            inlier_mask = residuals < ransac_threshold
            n_inliers = int(np.sum(inlier_mask))

            if n_inliers > best_inliers:
                best_inliers = n_inliers
                # Refine: average of all inliers
                best_translation = np.mean(translations[inlier_mask], axis=0)

        if best_inliers < min_inliers:
            logger.warning(
                f"RANSAC: insufficient inliers {best_inliers} < {min_inliers}"
            )
            return None

        dx, dy = best_translation
        logger.debug(
            f"RANSAC: translation=({dx:.2f}, {dy:.2f}), inliers={best_inliers}/{n_points}"
        )
        return (float(dx), float(dy))

    @staticmethod
    def _to_uint8(image: np.ndarray) -> np.ndarray:
        """Convert image to uint8 for feature detection."""
        if image.dtype == np.uint8:
            return image
        if image.dtype == np.uint16:
            return (image >> 8).astype(np.uint8)
        if image.dtype in (np.float32, np.float64):
            return (np.clip(image, 0, 1) * 255).astype(np.uint8)
        # Fallback: normalize
        img_min, img_max = image.min(), image.max()
        if img_max == img_min:
            return np.zeros(image.shape, dtype=np.uint8)
        return ((image - img_min) / (img_max - img_min) * 255).astype(np.uint8)
