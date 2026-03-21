from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from image_stitcher.acquisition.camera_adapter import CameraAdapter
    from image_stitcher.acquisition.xy_table import XYTable


@dataclass
class AppSession:
    """Shared state across all stages of the unified application."""

    xy_table: XYTable | None = None
    camera: CameraAdapter | None = None
    scan_output_dir: Path | None = None
    panorama_path: Path | None = None
