# laser_platform.spec — PyInstaller specification
# Build: pyinstaller laser_platform.spec --noconfirm
# Output: dist\LaserPlatform\LaserPlatform.exe  (one-dir mode)
#
# To produce a release build (no console window), change:
#   console=True  →  console=False

from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "launch.py")],

    # Project root must be on pathex so all top-level packages are importable
    pathex=[str(ROOT)],

    binaries=[],
    datas=[],

    # ---- Hidden imports -----------------------------------------------
    # PyInstaller can trace most imports automatically, but lazy imports
    # (inside methods) and sub-packages without explicit __init__ usage
    # need to be listed here.
    hiddenimports=[
        # tifffile: lazy import in image_stitcher/utils/image_io.py
        "tifffile",

        # pyserial exposes itself as 'serial' but pip package is 'pyserial'
        "serial",
        "serial.tools",
        "serial.tools.list_ports",

        # Local packages (guarantee all sub-packages are collected)
        "app",
        "app.main",
        "app.frozen",
        "app.session",
        "app.i18n",
        "app.gui",
        "app.gui.main_window",
        "app.gui.hardware_panel",
        "app.gui.step_indicator",
        "app.gui.stages",
        "app.gui.stages.scan_stage",
        "app.gui.stages.stitch_stage",
        "app.gui.stages.navigate_stage",

        "image_stitcher",
        "image_stitcher.config",
        "image_stitcher.main",
        "image_stitcher.acquisition",
        "image_stitcher.acquisition.camera_adapter",
        "image_stitcher.acquisition.smc100_axis",
        "image_stitcher.acquisition.xy_table",
        "image_stitcher.acquisition.mlj250_axis",
        "image_stitcher.scanner",
        "image_stitcher.scanner.grid_scanner",
        "image_stitcher.scanner.scan_coordinator",
        "image_stitcher.gui",
        "image_stitcher.gui.main_window",
        "image_stitcher.gui.preview_widget",
        "image_stitcher.gui.progress_widget",
        "image_stitcher.gui.scan_config_widget",
        "image_stitcher.gui.xy_control_widget",
        "image_stitcher.utils",
        "image_stitcher.utils.image_io",
        "image_stitcher.utils.coordinate",

        "chip_navigator",
        "chip_navigator.main",
        "chip_navigator.mapping",
        "chip_navigator.mapping.calibration",
        "chip_navigator.gui",
        "chip_navigator.gui.calibration_widget",
        "chip_navigator.gui.panorama_map_widget",
        "chip_navigator.gui.chip_navigator_window",

        # Image_Stitching.core is imported by app/gui/stages/stitch_stage.py
        "Image_Stitching",
        "Image_Stitching.core",
        "Image_Stitching.core.models",
        "Image_Stitching.core.stitcher",
        "Image_Stitching.core.exporter",
        "Image_Stitching.core.loader",
        "Image_Stitching.core.layout",
        "Image_Stitching.core.blend",
        "Image_Stitching.core.exposure",
        "Image_Stitching.core.align",

        # xyz_table.thorlabs.driver is imported by image_stitcher/acquisition/mlj250_axis.py
        "xyz_table",
        "xyz_table.thorlabs",
        "xyz_table.thorlabs.driver",
    ],

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],

    # ---- Excludes --------------------------------------------------------
    # vmbpy is a system-level SDK (VimbaX) — cannot be bundled.
    # The user must have VimbaX installed separately for camera features.
    #
    # The legacy camera/ and xyz_table/ top-level files use analyzr2,
    # which is not used by the main app at all.
    excludes=[
        # System-level camera SDK — must be installed separately
        "vmbpy",

        # Legacy dependencies not used by the main app
        "analyzr2",
        "xarray",
        "harvesters",
        "genicam",

        # Unused PySide6 modules (saves ~200-400 MB)
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel",
        "PySide6.QtWebSockets",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DExtras",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
        "PySide6.QtLocation",
        "PySide6.QtSensors",
        "PySide6.QtTest",
        "PySide6.QtSql",
        "PySide6.QtXml",
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtRemoteObjects",
        "PySide6.QtSerialPort",
        "PySide6.QtSerialBus",
        "PySide6.QtNetworkAuth",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQml",

        # Unused stdlib
        "tkinter",
        "unittest",
        "doctest",
        "pydoc",
        "xmlrpc",
    ],

    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # one-dir mode (not one-file)
    name="LaserPlatform",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX can corrupt Qt/PySide6 DLLs — keep disabled
    console=True,            # Set to False for a release build (no terminal window)
    disable_windowed_traceback=False,
    # icon="app/resources/icon.ico",  # Uncomment when an .ico file is added
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LaserPlatform",
)
