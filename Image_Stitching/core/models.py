from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class TileMeta:
    path: Path
    row: int
    col: int


@dataclass
class StitchConfig:
    input_dir: Path | None
    overlap_x: float
    overlap_y: float
    resolution_mode: str = "resize_to_first"
    input_paths: list[Path] | None = None
    expected_rows: int | None = None
    expected_cols: int | None = None
    enable_exposure: bool = True
    enable_align: bool = False
    max_align_shift: int = 20


@dataclass
class StitchOutput:
    image: np.ndarray
    preview: np.ndarray
    rows: int
    cols: int
    tile_width: int
    tile_height: int
    source_size_summary: str
