from __future__ import annotations

import cv2
import numpy as np


def estimate_shift(
    base_img: np.ndarray,
    target_img: np.ndarray,
    max_shift: int,
) -> tuple[int, int]:
    base_gray = cv2.cvtColor(base_img, cv2.COLOR_BGR2GRAY)
    target_gray = cv2.cvtColor(target_img, cv2.COLOR_BGR2GRAY)
    shift, _ = cv2.phaseCorrelate(base_gray.astype(np.float32), target_gray.astype(np.float32))
    dx = int(round(np.clip(shift[0], -max_shift, max_shift)))
    dy = int(round(np.clip(shift[1], -max_shift, max_shift)))
    return dx, dy
