from dataclasses import dataclass


@dataclass(frozen=True)
class TilePlacement:
    row: int
    col: int
    x: int
    y: int


@dataclass(frozen=True)
class LayoutResult:
    placements: list[TilePlacement]
    canvas_width: int
    canvas_height: int
    step_x: int
    step_y: int


def compute_layout(
    rows: list[int],
    cols: list[int],
    tile_width: int,
    tile_height: int,
    overlap_x: float,
    overlap_y: float,
) -> LayoutResult:
    if not rows or not cols:
        raise ValueError("rows/cols 不能为空")
    if not (0.0 <= overlap_x < 1.0 and 0.0 <= overlap_y < 1.0):
        raise ValueError("重叠度必须在 [0, 1) 区间")

    step_x = max(1, int(round(tile_width * (1.0 - overlap_x))))
    step_y = max(1, int(round(tile_height * (1.0 - overlap_y))))

    row_min = min(rows)
    col_min = min(cols)
    placements: list[TilePlacement] = []

    canvas_width = 0
    canvas_height = 0
    for row in sorted(rows):
        for col in sorted(cols):
            x = int(round((col - col_min) * step_x))
            y = int(round((row - row_min) * step_y))
            placements.append(TilePlacement(row=row, col=col, x=x, y=y))
            canvas_width = max(canvas_width, x + tile_width)
            canvas_height = max(canvas_height, y + tile_height)

    return LayoutResult(
        placements=placements,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        step_x=step_x,
        step_y=step_y,
    )
