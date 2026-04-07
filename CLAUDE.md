# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Applications

```bash
# Unified workflow app (primary entry point)
python -m app

# Standalone scanner only
python -m image_stitcher

# Standalone chip navigator only
python -m chip_navigator

# Legacy standalone image stitching tool
python Image_Stitching/main.py
```

## Running Tests

```bash
# Run calibration unit tests (the only test suite)
python chip_navigator/tests/test_calibration.py

# Or with pytest from repo root
pytest chip_navigator/tests/test_calibration.py
```

## Dependencies

```bash
pip install PySide6 numpy opencv-python pyserial
# vmbpy (Allied Vision VimbaX SDK) must be installed separately from Allied Vision website
```

## Architecture Overview

The repo contains one unified app and three reusable Python packages that can also run standalone.

### Unified App (`app/`)

`AppMainWindow` orchestrates a 3-stage linear workflow via a `QStackedWidget`:

1. **ScanStage** — wraps `image_stitcher`'s scan GUI for grid acquisition
2. **StitchStage** — wraps `image_stitcher`'s stitch GUI for panorama assembly
3. **NavigateStage** — wraps `chip_navigator`'s navigation GUI for chip targeting

`AppSession` (`app/session.py`) is a shared dataclass holding `xy_table`, `camera`, `scan_output_dir`, and `panorama_path`. It is passed to all stages so hardware connections are shared. Stage transitions automatically pass the scan output directory into the stitch stage and the exported panorama into the navigate stage.

`HardwarePanel` (`app/gui/hardware_panel.py`) is a logic-only `QObject` (no widgets). Hardware connect/disconnect is triggered from menu actions; status is emitted as signals. XY position is polled every 500 ms via a `_PositionWorker` QThread to keep the UI unblocked.

### `image_stitcher/` Package

Handles both **acquisition** and **stitching**:

- `acquisition/camera_adapter.py` — `CameraAdapter` wraps VmbPy for single-frame capture; `LiveFeedWorker` is a `QThread` for continuous streaming. The live feed and `capture_single()` share the same camera handle and **cannot run concurrently** — always stop the live feed before capturing.
- `acquisition/xy_table.py` — `XYTable` wraps two `SMC100Axis` instances (+ optional Z). All moves are blocking.
- `acquisition/smc100_axis.py` — Speaks Newport ASCII protocol over serial. Shared serial port with reference counting for daisy-chained controllers. Wire protocol uses mm; all public API uses µm.
- `acquisition/mlj250_axis.py` — Thorlabs MLJ250 Z-axis driver.
- `scanner/grid_scanner.py` — Computes serpentine (boustrophedon) scan paths from `ScanConfig`.
- `scanner/scan_coordinator.py` — Manages scan lifecycle (pause/resume/abort), emits `confirm_capture_requested` signal so the GUI can show a live preview before each tile capture.
- `config.py` — `ScanConfig` dataclass; all spatial units in µm.
- `gui/main_window.py` — Standalone scanner window + `XYConnectDialog` (also reused by `app/`). Default COM ports: XY on COM11 (addresses 1 & 2), Z on COM12.

### `chip_navigator/` Package

- `mapping/calibration.py` — `AffineCalibration` collects pixel↔stage point pairs and solves a 2×3 affine matrix via least-squares (`numpy.linalg.lstsq`). Requires ≥3 non-collinear points. Provides `pixel_to_stage()`, `stage_to_pixel()`, and JSON save/load.
- `gui/calibration_widget.py` — UI for adding/removing calibration points, switching between calibration and navigation modes.
- `gui/panorama_map_widget.py` — Clickable panorama viewer that emits `point_clicked(u, v)`.

### `Image_Stitching/` Package (Legacy Standalone)

A separate older stitching tool (`Image_Stitching/ui/main_window.py`) that reads a grid of images named by row/column (`11.png` → `88.png`) and stitches them. Not integrated into the unified app.

## Key Patterns

**Threading:** Every blocking hardware operation (move, position read, camera frame) runs in a `QThread` worker. Workers emit signals; slots update the UI. Never call hardware APIs directly from the main thread.

**Live feed lifecycle:** The `LiveFeedWorker` must be stopped (`.stop()` + `.wait(3000)`) before the camera is used for single-frame capture. The main window handles this in `_on_confirm_capture_requested`.

**Internationalization:** All user-visible strings go through `tr(key)` (`app/i18n.py`). Translations for `en`, `zh`, and `es` are defined in the `_TRANSLATIONS` dict. Adding a new string requires entries in all three languages.

**Stage enter/leave:** `AppMainWindow._on_stage_switched()` calls `on_stage_leave()` on all stages, then `on_stage_enter()` on the newly active one. This is where live feeds are started/stopped. Stages must implement both methods.
