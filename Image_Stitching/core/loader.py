import re
from collections import defaultdict
from pathlib import Path

from .models import TileMeta

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
NAME_PATTERN = re.compile(r"^(\d+)_(\d+)$")
EXTENSION_PRIORITY = {".tiff": 0, ".tif": 1, ".png": 2, ".jpg": 3, ".jpeg": 4}


class LoaderError(Exception):
    pass


def load_tiles(
    input_dir: Path | None,
    input_paths: list[Path] | None = None,
    expected_rows: int | None = None,
    expected_cols: int | None = None,
) -> tuple[list[TileMeta], int, int]:
    candidates = _collect_candidates(input_dir, input_paths)

    grouped: dict[tuple[int, int], Path] = {}
    duplicates: dict[tuple[int, int], list[Path]] = defaultdict(list)

    for path in candidates:
        row, col = _parse_row_col(path)
        if row is None or col is None:
            continue
        key = (row, col)
        if key in grouped:
            duplicates[key].append(path)
            continue
        grouped[key] = path

    if not grouped:
        raise LoaderError("没有找到符合规则的图像文件（例如 1_1.png, 1_2.jpg）。")

    if duplicates:
        msgs = []
        for (row, col), paths in sorted(duplicates.items()):
            names = ", ".join(p.name for p in paths)
            msgs.append(f"{row}_{col}: {names}")
        raise LoaderError("发现重复编号文件，无法继续:\n" + "\n".join(msgs))

    rows = sorted({r for r, _ in grouped.keys()})
    cols = sorted({c for _, c in grouped.keys()})

    if expected_rows is not None and expected_rows <= 0:
        raise LoaderError("期望行数必须大于 0")
    if expected_cols is not None and expected_cols <= 0:
        raise LoaderError("期望列数必须大于 0")

    if expected_rows is not None and len(rows) != expected_rows:
        raise LoaderError(f"行数不匹配: 检测到 {len(rows)} 行, 期望 {expected_rows} 行")
    if expected_cols is not None and len(cols) != expected_cols:
        raise LoaderError(f"列数不匹配: 检测到 {len(cols)} 列, 期望 {expected_cols} 列")

    expected = {(r, c) for r in rows for c in cols}
    missing = sorted(expected - set(grouped.keys()))
    if missing:
        missing_str = ", ".join(f"{r}_{c}" for r, c in missing)
        raise LoaderError(f"缺少图像，停止导出。缺失编号: {missing_str}")

    tiles = [
        TileMeta(path=grouped[(r, c)], row=r, col=c)
        for r in rows
        for c in cols
    ]
    return tiles, len(rows), len(cols)


def _collect_candidates(input_dir: Path | None, input_paths: list[Path] | None) -> list[Path]:
    if input_paths:
        files = [p for p in input_paths if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS]
        if not files:
            raise LoaderError("未选择有效图像文件。")
        return _dedup_by_stem(sorted(files))

    if input_dir is None:
        raise LoaderError("请先选择输入目录或图像文件。")
    if not input_dir.is_dir():
        raise LoaderError(f"输入目录不存在: {input_dir}")
    all_files = sorted(
        p
        for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    return _dedup_by_stem(all_files)


def _dedup_by_stem(files: list[Path]) -> list[Path]:
    """When multiple files share the same stem, keep only the one with highest priority extension (TIFF > PNG > JPG)."""
    best: dict[str, Path] = {}
    for p in files:
        stem = p.stem
        ext = p.suffix.lower()
        if stem not in best:
            best[stem] = p
        else:
            current_prio = EXTENSION_PRIORITY.get(best[stem].suffix.lower(), 99)
            new_prio = EXTENSION_PRIORITY.get(ext, 99)
            if new_prio < current_prio:
                best[stem] = p
    return sorted(best.values())


def _parse_row_col(path: Path) -> tuple[int | None, int | None]:
    stem = path.stem.strip()
    m = NAME_PATTERN.match(stem)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))
