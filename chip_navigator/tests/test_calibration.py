"""
Unit tests for AffineCalibration.

Tests the core affine solve, forward/inverse transform, error
computation, and JSON save/load roundtrip.
"""

import json
import math
import tempfile
from pathlib import Path

import numpy as np

# Adjust import path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chip_navigator.mapping.calibration import AffineCalibration


def test_exact_3_point_calibration():
    """3 non-collinear points should give a perfect fit (RMSE ~ 0)."""
    cal = AffineCalibration()

    # Known affine: x = 10*u + 5*v + 100, y = -3*u + 8*v + 200
    def ground_truth(u, v):
        return (10 * u + 5 * v + 100, -3 * u + 8 * v + 200)

    pts = [(0, 0), (100, 0), (0, 100)]
    for u, v in pts:
        sx, sy = ground_truth(u, v)
        cal.add_point(u, v, sx, sy)

    result = cal.solve()

    assert result.num_points == 3
    assert result.rmse < 1e-6, f"RMSE too high: {result.rmse}"

    # Test forward transform
    for u, v in [(50, 50), (25, 75), (80, 20)]:
        expected = ground_truth(u, v)
        actual = cal.pixel_to_stage(u, v)
        assert abs(actual[0] - expected[0]) < 1e-6
        assert abs(actual[1] - expected[1]) < 1e-6

    # Test inverse transform
    for u, v in [(50, 50), (25, 75)]:
        sx, sy = ground_truth(u, v)
        recovered = cal.stage_to_pixel(sx, sy)
        assert abs(recovered[0] - u) < 1e-6
        assert abs(recovered[1] - v) < 1e-6


def test_overdetermined_calibration():
    """5+ points with slight noise should yield small but nonzero RMSE."""
    cal = AffineCalibration()

    # True transform
    M_true = np.array([[20.0, -3.0, 500.0], [2.0, 15.0, 1000.0]])

    rng = np.random.RandomState(42)
    n_points = 7
    for _ in range(n_points):
        u = rng.uniform(0, 1000)
        v = rng.uniform(0, 1000)
        p = M_true @ np.array([u, v, 1.0])
        # Add small noise (simulate stage positioning error)
        noise = rng.normal(0, 0.5, 2)
        cal.add_point(u, v, p[0] + noise[0], p[1] + noise[1])

    result = cal.solve()

    assert result.num_points == n_points
    # RMSE should be small (dominated by noise level)
    assert result.rmse < 2.0, f"RMSE too high: {result.rmse}"

    # Forward transform should be close to true transform
    test_u, test_v = 500.0, 500.0
    expected = M_true @ np.array([test_u, test_v, 1.0])
    actual = cal.pixel_to_stage(test_u, test_v)
    assert abs(actual[0] - expected[0]) < 5.0
    assert abs(actual[1] - expected[1]) < 5.0


def test_too_few_points_raises():
    """Should raise ValueError with fewer than 3 points."""
    cal = AffineCalibration()
    cal.add_point(0, 0, 0, 0)
    cal.add_point(1, 0, 10, 0)

    try:
        cal.solve()
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "3" in str(e)


def test_collinear_points_raises():
    """Should raise ValueError for collinear points."""
    cal = AffineCalibration()
    cal.add_point(0, 0, 0, 0)
    cal.add_point(10, 0, 100, 0)
    cal.add_point(20, 0, 200, 0)

    try:
        cal.solve()
        assert False, "Should have raised ValueError"
    except ValueError:
        pass  # Expected


def test_save_load_roundtrip():
    """Save and load should preserve points and solution."""
    cal = AffineCalibration()
    cal.add_point(0, 0, 100, 200)
    cal.add_point(100, 0, 600, 200)
    cal.add_point(0, 100, 100, 700)
    cal.add_point(100, 100, 600, 700)
    cal.solve()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = f.name

    cal.save(tmp_path)

    # Verify JSON is valid
    data = json.loads(Path(tmp_path).read_text())
    assert len(data["points"]) == 4
    assert "result" in data

    # Load into new instance
    cal2 = AffineCalibration()
    cal2.load(tmp_path)

    assert cal2.num_points == 4
    assert cal2.is_solved

    # Transforms should match
    for u, v in [(50, 50), (25, 75)]:
        orig = cal.pixel_to_stage(u, v)
        loaded = cal2.pixel_to_stage(u, v)
        assert abs(orig[0] - loaded[0]) < 1e-6
        assert abs(orig[1] - loaded[1]) < 1e-6

    # Cleanup
    Path(tmp_path).unlink(missing_ok=True)


def test_remove_point():
    """Removing a point should invalidate the solution."""
    cal = AffineCalibration()
    cal.add_point(0, 0, 0, 0)
    cal.add_point(100, 0, 100, 0)
    cal.add_point(0, 100, 0, 100)
    cal.solve()
    assert cal.is_solved

    cal.remove_point(0)
    assert not cal.is_solved
    assert cal.num_points == 2


def test_clear_points():
    cal = AffineCalibration()
    cal.add_point(0, 0, 0, 0)
    cal.add_point(100, 0, 100, 0)
    cal.add_point(0, 100, 0, 100)
    cal.solve()

    cal.clear_points()
    assert cal.num_points == 0
    assert not cal.is_solved


if __name__ == "__main__":
    test_exact_3_point_calibration()
    print("PASS: test_exact_3_point_calibration")

    test_overdetermined_calibration()
    print("PASS: test_overdetermined_calibration")

    test_too_few_points_raises()
    print("PASS: test_too_few_points_raises")

    test_collinear_points_raises()
    print("PASS: test_collinear_points_raises")

    test_save_load_roundtrip()
    print("PASS: test_save_load_roundtrip")

    test_remove_point()
    print("PASS: test_remove_point")

    test_clear_points()
    print("PASS: test_clear_points")

    print("\nAll tests passed!")
