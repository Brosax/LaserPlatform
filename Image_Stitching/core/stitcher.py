from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .align import estimate_shift
from .blend import blend_tiles
from .exposure import apply_gain_offset, estimate_gain_offset
from .layout import compute_layout
from .loader import LoaderError, load_tiles
from .models import StitchConfig, StitchOutput


class StitchError(Exception):
    pass


def _read_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise StitchError(f"无法读取图像: {path}")
    return image


def stitch(
    config: StitchConfig,
    progress_callback: Callable[[int, str], None] | None = None,
) -> StitchOutput:
    def update_progress(percent: int, message: str) -> None:
        if progress_callback is not None:
            progress_callback(percent, message)

    update_progress(5, "扫描文件中")
    try:
        tiles, rows_count, cols_count = load_tiles(
            input_dir=config.input_dir,
            input_paths=config.input_paths,
            expected_rows=config.expected_rows,
            expected_cols=config.expected_cols,
        )
    except LoaderError as exc:
        raise StitchError(str(exc)) from exc

    update_progress(10, "读取图像中")
    first = _read_image(tiles[0].path)
    base_h, base_w = first.shape[:2]

    images: dict[tuple[int, int], np.ndarray] = {}
    source_sizes: list[tuple[int, int]] = []
    first_key = (tiles[0].row, tiles[0].col)
    first_processed = _normalize_size(first, base_w, base_h, config.resolution_mode)
    images[first_key] = first_processed
    source_sizes.append((base_w, base_h))

    for tile in tiles[1:]:
        image = _read_image(tile.path)
        src_h, src_w = image.shape[:2]
        source_sizes.append((src_w, src_h))
        if config.resolution_mode == "strict" and (src_h != base_h or src_w != base_w):
            raise StitchError(
                f"图像尺寸不一致: {tile.path.name} 为 {src_w}x{src_h}, 期望 {base_w}x{base_h}"
            )
        images[(tile.row, tile.col)] = _normalize_size(
            image,
            base_w,
            base_h,
            config.resolution_mode,
        )

    tile_h, tile_w = base_h, base_w
    source_summary = _build_source_size_summary(source_sizes, tile_w, tile_h, config.resolution_mode)

    update_progress(20, "计算布局中")
    rows = sorted({t.row for t in tiles})
    cols = sorted({t.col for t in tiles})
    layout = compute_layout(rows, cols, tile_w, tile_h, config.overlap_x, config.overlap_y)

    overlap_px_x = max(1, int(round(tile_w * config.overlap_x)))
    overlap_px_y = max(1, int(round(tile_h * config.overlap_y)))
    placed_images: list[tuple[np.ndarray, int, int]] = []

    stitched_row_col: dict[tuple[int, int], np.ndarray] = {}
    placement_map = {(p.row, p.col): (p.x, p.y) for p in layout.placements}

    total_tiles = len(layout.placements)
    for index, placement in enumerate(layout.placements, start=1):
        key = (placement.row, placement.col)
        image = images[key]
        x, y = placement_map[key]

        left_key = (placement.row, placement.col - 1)
        up_key = (placement.row - 1, placement.col)

        if config.enable_align:
            shifts: list[tuple[int, int]] = []

            if left_key in stitched_row_col:
                left_img = stitched_row_col[left_key]
                ref = left_img[:, -overlap_px_x:]
                cur = image[:, :overlap_px_x]
                dx, dy = estimate_shift(ref, cur, config.max_align_shift)
                shifts.append((dx, dy))

            if up_key in stitched_row_col:
                up_img = stitched_row_col[up_key]
                ref = up_img[-overlap_px_y:, :]
                cur = image[:overlap_px_y, :]
                dx, dy = estimate_shift(ref, cur, config.max_align_shift)
                shifts.append((dx, dy))

            if shifts:
                x += int(round(sum(s[0] for s in shifts) / len(shifts)))
                y += int(round(sum(s[1] for s in shifts) / len(shifts)))

        if config.enable_exposure:
            refs = []

            if left_key in stitched_row_col:
                ref = stitched_row_col[left_key][:, -overlap_px_x:]
                cur = image[:, :overlap_px_x]
                refs.append((ref, cur))

            if up_key in stitched_row_col:
                ref = stitched_row_col[up_key][-overlap_px_y:, :]
                cur = image[:overlap_px_y, :]
                refs.append((ref, cur))

            if refs:
                gains = []
                offsets = []
                for ref, cur in refs:
                    gain, offset = estimate_gain_offset(ref, cur)
                    gains.append(gain)
                    offsets.append(offset)
                image = apply_gain_offset(
                    image,
                    gain=float(np.mean(gains)),
                    offset=float(np.mean(offsets)),
                )

        stitched_row_col[key] = image
        placed_images.append((image, x, y))
        percent = 20 + int(60 * index / max(total_tiles, 1))
        update_progress(percent, f"拼接中 {index}/{total_tiles}")

    min_x = min(x for _, x, _ in placed_images)
    min_y = min(y for _, _, y in placed_images)
    if min_x < 0 or min_y < 0:
        shifted: list[tuple[np.ndarray, int, int]] = []
        for image, x, y in placed_images:
            shifted.append((image, x - min_x, y - min_y))
        placed_images = shifted

    max_x = max(x + img.shape[1] for img, x, _ in placed_images)
    max_y = max(y + img.shape[0] for img, _, y in placed_images)

    update_progress(85, "融合图像中")
    canvas = blend_tiles(max_y, max_x, placed_images)

    update_progress(95, "生成预览中")
    preview = _make_preview(canvas, max_dim=1400)
    update_progress(100, "完成")
    return StitchOutput(
        image=canvas,
        preview=preview,
        rows=rows_count,
        cols=cols_count,
        tile_width=tile_w,
        tile_height=tile_h,
        source_size_summary=source_summary,
    )


def _make_preview(image: np.ndarray, max_dim: int) -> np.ndarray:
    h, w = image.shape[:2]
    scale = min(max_dim / max(h, 1), max_dim / max(w, 1), 1.0)
    if scale >= 1.0:
        return image
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _normalize_size(image: np.ndarray, base_w: int, base_h: int, mode: str) -> np.ndarray:
    h, w = image.shape[:2]
    if mode == "strict":
        return image
    if mode == "resize_to_first":
        if (w, h) == (base_w, base_h):
            return image
        return cv2.resize(image, (base_w, base_h), interpolation=cv2.INTER_AREA)
    if mode == "pad_to_first":
        if (w, h) == (base_w, base_h):
            return image
        scale = min(base_w / max(w, 1), base_h / max(h, 1))
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((base_h, base_w, 3), dtype=np.uint8)
        x = (base_w - new_w) // 2
        y = (base_h - new_h) // 2
        canvas[y : y + new_h, x : x + new_w] = resized
        return canvas
    raise StitchError(f"不支持的分辨率模式: {mode}")


def _build_source_size_summary(
    source_sizes: list[tuple[int, int]],
    target_w: int,
    target_h: int,
    mode: str,
) -> str:
    unique = sorted(set(source_sizes))
    if len(unique) == 1:
        return f"原图: {target_w}x{target_h}"
    first = unique[0]
    last = unique[-1]
    return (
        f"原图范围: {first[0]}x{first[1]} ~ {last[0]}x{last[1]}, "
        f"处理模式: {mode}, 统一后: {target_w}x{target_h}"
    )
