from __future__ import annotations

import numpy as np


def make_weight_map(h: int, w: int) -> np.ndarray:
    x = np.linspace(0.0, 1.0, w, dtype=np.float32)
    y = np.linspace(0.0, 1.0, h, dtype=np.float32)
    wx = 1.0 - np.abs(2.0 * x - 1.0)
    wy = 1.0 - np.abs(2.0 * y - 1.0)
    weight = np.outer(wy, wx)
    weight = np.maximum(weight, 1e-3)
    return weight


def blend_tiles(
    canvas_h: int,
    canvas_w: int,
    placed_images: list[tuple[np.ndarray, int, int]],
) -> np.ndarray:
    acc = np.zeros((canvas_h, canvas_w, 3), dtype=np.float32)
    wsum = np.zeros((canvas_h, canvas_w, 1), dtype=np.float32)

    for image, x, y in placed_images:
        h, w = image.shape[:2]
        weight = make_weight_map(h, w)[..., None]
        patch = image.astype(np.float32)

        acc[y : y + h, x : x + w] += patch * weight
        wsum[y : y + h, x : x + w] += weight

    out = acc / np.maximum(wsum, 1e-6)
    out = np.clip(out, 0, 255).astype(np.uint8)
    return out
