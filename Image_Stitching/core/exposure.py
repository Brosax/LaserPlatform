from __future__ import annotations

import numpy as np


def apply_gain_offset(image: np.ndarray, gain: float, offset: float) -> np.ndarray:
    out = image.astype(np.float32) * gain + offset
    out = np.clip(out, 0, 255).astype(np.uint8)
    return out


def estimate_gain_offset(ref: np.ndarray, cur: np.ndarray) -> tuple[float, float]:
    ref_f = ref.astype(np.float32)
    cur_f = cur.astype(np.float32)
    ref_mean = float(ref_f.mean())
    cur_mean = float(cur_f.mean())
    ref_std = float(ref_f.std())
    cur_std = float(cur_f.std())

    gain = 1.0
    if cur_std > 1e-3:
        gain = ref_std / cur_std
    gain = float(np.clip(gain, 0.85, 1.15))

    offset = ref_mean - cur_mean * gain
    offset = float(np.clip(offset, -25.0, 25.0))
    return gain, offset
