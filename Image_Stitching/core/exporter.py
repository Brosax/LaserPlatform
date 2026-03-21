from pathlib import Path

import cv2


class ExportError(Exception):
    pass


def export_image(output_path: Path, image) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(output_path), image)
    if not ok:
        raise ExportError(f"导出失败: {output_path}")
