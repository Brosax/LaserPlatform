"""
Affine calibration: pixel (u, v) <-> stage (x_um, y_um).

Solves an affine transform from 3+ corresponding point pairs using
ordinary least squares.  Provides forward (pixel->stage) and inverse
(stage->pixel) transforms, per-point reprojection error, RMSE, and
JSON save/load for persistent storage.

Math
----
    [x]   [a  b  tx] [u]
    [y] = [c  d  ty] [v]
                      [1]

    M is 2x3.  Solved via least-squares when n >= 3 point pairs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Data containers
# ------------------------------------------------------------------ #


@dataclass
class CalibrationPoint:
    """A single pixel <-> stage correspondence."""

    pixel_u: float
    pixel_v: float
    stage_x: float
    stage_y: float

    def pixel(self) -> Tuple[float, float]:
        return (self.pixel_u, self.pixel_v)

    def stage(self) -> Tuple[float, float]:
        return (self.stage_x, self.stage_y)


@dataclass
class CalibrationResult:
    """Stores the computed affine matrix and quality metrics."""

    matrix: np.ndarray  # shape (2, 3)
    inverse_matrix: np.ndarray  # shape (2, 3)
    rmse: float
    per_point_errors: List[float]
    num_points: int
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


# ------------------------------------------------------------------ #
#  Calibration engine
# ------------------------------------------------------------------ #


class AffineCalibration:
    """
    Manages calibration point collection and affine transform solving.

    Usage
    -----
    >>> cal = AffineCalibration()
    >>> cal.add_point(100, 200, 5000.0, 10000.0)
    >>> cal.add_point(800, 200, 20000.0, 10000.0)
    >>> cal.add_point(100, 600, 5000.0, 25000.0)
    >>> result = cal.solve()
    >>> x, y = cal.pixel_to_stage(450, 400)
    """

    def __init__(self):
        self._points: List[CalibrationPoint] = []
        self._result: Optional[CalibrationResult] = None

    # ---- Point management -------------------------------------------- #

    @property
    def points(self) -> List[CalibrationPoint]:
        return list(self._points)

    @property
    def num_points(self) -> int:
        return len(self._points)

    @property
    def is_solved(self) -> bool:
        return self._result is not None

    @property
    def result(self) -> Optional[CalibrationResult]:
        return self._result

    def add_point(
        self, pixel_u: float, pixel_v: float, stage_x: float, stage_y: float
    ) -> int:
        """
        Add a calibration point pair.

        Returns the index of the newly added point.
        """
        pt = CalibrationPoint(pixel_u, pixel_v, stage_x, stage_y)
        self._points.append(pt)
        self._result = None  # invalidate previous solution
        logger.info(
            f"Calibration point #{len(self._points)} added: "
            f"pixel=({pixel_u:.1f}, {pixel_v:.1f}) -> "
            f"stage=({stage_x:.1f}, {stage_y:.1f}) um"
        )
        return len(self._points) - 1

    def remove_point(self, index: int) -> None:
        """Remove a calibration point by index."""
        if 0 <= index < len(self._points):
            removed = self._points.pop(index)
            self._result = None
            logger.info(
                f"Calibration point removed: "
                f"pixel=({removed.pixel_u:.1f}, {removed.pixel_v:.1f})"
            )

    def clear_points(self) -> None:
        """Remove all calibration points."""
        self._points.clear()
        self._result = None

    # ---- Solve ------------------------------------------------------- #

    def solve(self) -> CalibrationResult:
        """
        Compute the affine transform from collected point pairs.

        Requires at least 3 non-collinear points.

        Returns
        -------
        CalibrationResult
            Contains the 2x3 affine matrix, inverse, RMSE, and
            per-point errors.

        Raises
        ------
        ValueError
            If fewer than 3 points or points are collinear.
        """
        n = len(self._points)
        if n < 3:
            raise ValueError(f"At least 3 calibration points required, got {n}.")

        # Build matrices:  stage = M * [u, v, 1]^T
        #   A (n x 3) = [[u1, v1, 1], [u2, v2, 1], ...]
        #   B (n x 2) = [[x1, y1], [x2, y2], ...]
        A = np.zeros((n, 3))
        B = np.zeros((n, 2))
        for i, pt in enumerate(self._points):
            A[i] = [pt.pixel_u, pt.pixel_v, 1.0]
            B[i] = [pt.stage_x, pt.stage_y]

        # Solve A * M^T = B  =>  M^T = pinv(A) * B  =>  M = (pinv(A)*B)^T
        # Using lstsq for numerical stability
        M_T, residuals, rank, sv = np.linalg.lstsq(A, B, rcond=None)

        if rank < 3:
            raise ValueError(
                "Calibration points are collinear or degenerate. "
                "Use non-collinear points."
            )

        M = M_T.T  # shape (2, 3)

        # Compute inverse: pixel = M_inv * [x, y, 1]^T
        # Extract 2x2 linear part and translation
        linear = M[:, :2]  # 2x2
        translation = M[:, 2]  # 2

        det = np.linalg.det(linear)
        if abs(det) < 1e-12:
            raise ValueError(
                "Affine transform is singular (determinant ~ 0). "
                "Check calibration points."
            )

        linear_inv = np.linalg.inv(linear)
        trans_inv = -linear_inv @ translation

        M_inv = np.zeros((2, 3))
        M_inv[:, :2] = linear_inv
        M_inv[:, 2] = trans_inv

        # Per-point reprojection errors
        errors = []
        for pt in self._points:
            predicted = M @ np.array([pt.pixel_u, pt.pixel_v, 1.0])
            err = np.sqrt(
                (predicted[0] - pt.stage_x) ** 2 + (predicted[1] - pt.stage_y) ** 2
            )
            errors.append(float(err))

        rmse = float(np.sqrt(np.mean(np.array(errors) ** 2)))

        self._result = CalibrationResult(
            matrix=M,
            inverse_matrix=M_inv,
            rmse=rmse,
            per_point_errors=errors,
            num_points=n,
        )

        logger.info(f"Affine calibration solved: {n} points, RMSE = {rmse:.2f} um")
        return self._result

    # ---- Transform --------------------------------------------------- #

    def pixel_to_stage(self, u: float, v: float) -> Tuple[float, float]:
        """
        Convert pixel coordinates to stage coordinates (um).

        Raises RuntimeError if calibration has not been solved.
        """
        if self._result is None:
            raise RuntimeError("Calibration not solved. Call solve() first.")
        p = np.array([u, v, 1.0])
        stage = self._result.matrix @ p
        return (float(stage[0]), float(stage[1]))

    def stage_to_pixel(self, x_um: float, y_um: float) -> Tuple[float, float]:
        """
        Convert stage coordinates (um) to pixel coordinates.

        Raises RuntimeError if calibration has not been solved.
        """
        if self._result is None:
            raise RuntimeError("Calibration not solved. Call solve() first.")
        s = np.array([x_um, y_um, 1.0])
        pixel = self._result.inverse_matrix @ s
        return (float(pixel[0]), float(pixel[1]))

    # ---- Persistence ------------------------------------------------- #

    def save(self, filepath: str | Path) -> None:
        """
        Save calibration data (points + result) to a JSON file.
        """
        filepath = Path(filepath)

        data = {
            "version": 1,
            "points": [
                {
                    "pixel_u": pt.pixel_u,
                    "pixel_v": pt.pixel_v,
                    "stage_x": pt.stage_x,
                    "stage_y": pt.stage_y,
                }
                for pt in self._points
            ],
        }

        if self._result is not None:
            data["result"] = {
                "matrix": self._result.matrix.tolist(),
                "inverse_matrix": self._result.inverse_matrix.tolist(),
                "rmse": self._result.rmse,
                "per_point_errors": self._result.per_point_errors,
                "num_points": self._result.num_points,
                "timestamp": self._result.timestamp,
            }

        filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info(f"Calibration saved to {filepath}")

    def load(self, filepath: str | Path) -> None:
        """
        Load calibration data from a JSON file.

        Restores both points and (if present) the solved result.
        """
        filepath = Path(filepath)
        data = json.loads(filepath.read_text(encoding="utf-8"))

        self._points.clear()
        for pt_data in data.get("points", []):
            self._points.append(
                CalibrationPoint(
                    pixel_u=pt_data["pixel_u"],
                    pixel_v=pt_data["pixel_v"],
                    stage_x=pt_data["stage_x"],
                    stage_y=pt_data["stage_y"],
                )
            )

        result_data = data.get("result")
        if result_data is not None:
            self._result = CalibrationResult(
                matrix=np.array(result_data["matrix"]),
                inverse_matrix=np.array(result_data["inverse_matrix"]),
                rmse=result_data["rmse"],
                per_point_errors=result_data["per_point_errors"],
                num_points=result_data["num_points"],
                timestamp=result_data.get("timestamp", ""),
            )
        else:
            self._result = None

        logger.info(
            f"Calibration loaded from {filepath}: "
            f"{len(self._points)} points, "
            f"solved={'yes' if self._result else 'no'}"
        )
