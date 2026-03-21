import sys
from pathlib import Path

# Allow running as standalone script: python Image_Stitching/main.py
_project_root = str(Path(__file__).resolve().parents[1])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from Image_Stitching.ui.main_window import run


if __name__ == "__main__":
    run()
