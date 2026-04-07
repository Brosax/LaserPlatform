# Laser Platform — Unified Workflow

A desktop GUI application for automated laser chip scanning, image stitching, and panorama-based chip navigation. Built with PySide6 and designed for Windows.

---

## Overview

The application provides a three-stage linear workflow:

```
① Scan & Acquire  →  ② Image Stitching  →  ③ Chip Navigation
```

**Stage ① — Scan & Acquire**
Moves the XY stage across a user-defined grid in a serpentine (boustrophedon) pattern. At each grid position, the live camera feed is shown and the user confirms the frame before capture. Images are saved as numbered PNGs (`row-col.png`).

**Stage ② — Image Stitching**
Takes the scanned image directory and assembles tiles into a full panorama. Supports configurable overlap, brightness normalization, and sub-pixel auto-alignment. Exports PNG or TIFF.

**Stage ③ — Chip Navigation**
Loads the stitched panorama and lets the user click any pixel to move the physical stage to the corresponding location. Uses an affine calibration (≥3 point pairs) to map pixel coordinates to stage coordinates. Calibration data can be saved and reloaded as JSON.

---

## Hardware Requirements

| Hardware | Model | Interface |
|---|---|---|
| XY Stage | Newport SMC100 (daisy-chained) | Serial (default COM11, addresses 1 & 2) |
| Z Stage (optional) | Thorlabs MLJ250 **or** Newport SMC100 | Serial (default COM12) |
| Camera | Allied Vision (VimbaX-compatible) | USB / GigE |

The camera requires the **Allied Vision VimbaX SDK** installed system-wide. Download from the Allied Vision website. Without it, the camera features are disabled (all other features work normally).

---

## Installation

### Requirements

- Python 3.12+
- Windows 10/11 (64-bit)
- Allied Vision VimbaX SDK (for camera support)

### Python dependencies

```bash
pip install PySide6 numpy opencv-python-headless pyserial
pip install tifffile          # optional — only needed for 16-bit TIFF export
```

> **Important:** Use `opencv-python-headless`, not `opencv-python`. The non-headless variant ships its own Qt libraries that conflict with PySide6.

---

## Running from Source

```bash
# Unified workflow (recommended)
python -m app

# Standalone scanner only
python -m image_stitcher

# Standalone chip navigator only
python -m chip_navigator
```

---

## Building a Standalone Executable

PyInstaller is used to produce a one-directory Windows executable that runs without a Python installation.

### Prerequisites

```bash
pip install "pyinstaller>=6.0"
```

### Build

```bat
build.bat
```

Output: `dist\LaserPlatform\LaserPlatform.exe`

The build script cleans previous outputs, runs PyInstaller with `laser_platform.spec`, and reports success or failure.

### Notes on the bundle

- **vmbpy (Allied Vision SDK) is not bundled.** The VimbaX SDK must be installed on the target machine for camera features to work. Without it, camera connect will show a clear error dialog.
- **UPX is disabled** to avoid corrupting Qt/PySide6 DLLs.
- **Console window** is enabled by default for debugging. To produce a silent release build, change `console=True` → `console=False` in `laser_platform.spec` and rebuild.
- `build/` and `dist/` are excluded from version control.

---

## Project Structure

```
laser_platform/
├── app/                        # Unified workflow app (primary entry point)
│   ├── __main__.py
│   ├── main.py                 # QApplication setup + dark palette
│   ├── session.py              # Shared state (AppSession dataclass)
│   ├── i18n.py                 # EN / ZH / ES translations
│   ├── frozen.py               # PyInstaller frozen-app utilities
│   └── gui/
│       ├── main_window.py      # AppMainWindow: 3-stage QStackedWidget
│       ├── hardware_panel.py   # Hardware connect/disconnect logic (no widgets)
│       ├── step_indicator.py   # Step progress bar at the top
│       └── stages/
│           ├── scan_stage.py   # Stage ①: grid scan with live preview
│           ├── stitch_stage.py # Stage ②: stitching UI + zoomable preview
│           └── navigate_stage.py # Stage ③: panorama navigation + calibration
│
├── image_stitcher/             # Scanner + acquisition package
│   ├── acquisition/
│   │   ├── camera_adapter.py   # Allied Vision camera (vmbpy) + LiveFeedWorker
│   │   ├── smc100_axis.py      # Newport SMC100 serial driver
│   │   ├── mlj250_axis.py      # Thorlabs MLJ250 serial driver
│   │   └── xy_table.py         # XYTable: wraps X/Y(/Z) axes
│   ├── scanner/
│   │   ├── grid_scanner.py     # Serpentine grid path computation
│   │   └── scan_coordinator.py # Scan lifecycle: pause/resume/abort
│   ├── gui/                    # Standalone scanner GUI widgets
│   ├── utils/
│   │   ├── image_io.py         # PNG/TIFF save helpers
│   │   └── coordinate.py
│   └── config.py               # ScanConfig dataclass (all units in µm)
│
├── chip_navigator/             # Panorama navigation package
│   ├── mapping/
│   │   └── calibration.py      # AffineCalibration: pixel ↔ stage (least-squares)
│   └── gui/
│       ├── calibration_widget.py
│       ├── panorama_map_widget.py
│       └── chip_navigator_window.py  # Standalone navigator window
│
├── Image_Stitching/            # Image stitching engine
│   └── core/
│       ├── stitcher.py         # Main stitch() function
│       ├── loader.py           # Grid image loader (rowcol.ext naming)
│       ├── layout.py           # Tile placement geometry
│       ├── blend.py            # Multi-band blending
│       ├── exposure.py         # Brightness normalization
│       ├── align.py            # Sub-pixel alignment (OpenCV)
│       ├── exporter.py         # PNG / TIFF export
│       └── models.py           # StitchConfig, StitchOutput dataclasses
│
├── xyz_table/                  # Motion controller drivers
│   └── thorlabs/driver/        # MLJ250 low-level protocol
│
├── camera/                     # Legacy camera plugin layer (analyzr2-based)
│   └── thorlabs/dlls/64_lib/   # Thorlabs SDK DLLs (not used by main app)
│
├── launch.py                   # Entry point for PyInstaller builds
├── laser_platform.spec         # PyInstaller build specification
├── build.bat                   # One-click build script
└── CLAUDE.md                   # Notes for AI-assisted development
```

---

## Key Architecture Notes

### Shared state

`AppSession` (`app/session.py`) is a dataclass holding `xy_table`, `camera`, `scan_output_dir`, and `panorama_path`. It is passed to every stage so hardware connections are shared across the workflow.

### Threading model

All blocking hardware operations (XY moves, position reads, camera frame grabs) run in `QThread` workers. Workers emit Qt signals; slots update the UI. The main thread never blocks.

**Important:** The `LiveFeedWorker` and `CameraAdapter.capture_single()` both call `cam.get_frame()` and **cannot run concurrently**. The live feed is always stopped before single-frame capture and restarted afterwards.

### Affine calibration

The chip navigator uses an affine transform (2×3 matrix, solved by `numpy.linalg.lstsq`) to map panorama pixel coordinates (u, v) to physical stage coordinates (x_µm, y_µm). A minimum of 3 non-collinear calibration points is required. The solved calibration can be saved to JSON and reloaded between sessions.

### Language support

All user-visible strings go through `tr(key)` (`app/i18n.py`). Supported languages: English, 中文, Español. Switching language at runtime re-translates all open windows live via Qt signals.

### Scan image naming

The scanner saves tiles as `{row}{col}.png` (e.g. `11.png`, `12.png`, …, `88.png`). The stitching engine expects this naming convention to determine grid layout.

---

## Running Tests

```bash
# Calibration unit tests (no hardware required)
pytest chip_navigator/tests/test_calibration.py
```
