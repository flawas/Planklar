"""Seiten rendern (200 dpi) und Grossformate (A1/A0) in überlappende Kacheln schneiden."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.pipeline.preprocess import _open

MM_PER_INCH = 25.4
POINTS_PER_INCH = 72.0


@dataclass(frozen=True)
class RenderConfig:
    dpi: int = 200
    dpi_by_plantyp: Mapping[str, int] = field(default_factory=dict)
    tile_size_px: int = 2000
    tile_overlap_px: int = 200
    # Eine Seite mit längerer Kante ab diesem Wert (mm) gilt als Grossformat (A1 = 841 mm).
    large_format_min_mm: float = 780.0

    def __post_init__(self) -> None:
        if self.dpi <= 0 or any(v <= 0 for v in self.dpi_by_plantyp.values()):
            raise ValueError("dpi muss positiv sein")
        if self.tile_size_px <= 0:
            raise ValueError("tile_size_px muss positiv sein")
        if not 0 <= self.tile_overlap_px < self.tile_size_px:
            raise ValueError("tile_overlap_px muss in [0, tile_size_px) liegen")

    def dpi_for(self, plantyp: str | None) -> int:
        if plantyp is None:
            return self.dpi
        return self.dpi_by_plantyp.get(plantyp, self.dpi)


@dataclass(frozen=True)
class TileBox:
    """Rechteck in Pixeln (x1/y1 exklusiv)."""

    x0: int
    y0: int
    x1: int
    y1: int


@dataclass(frozen=True)
class RenderedPage:
    number: int  # 1-basiert
    dpi: int
    width_px: int
    height_px: int
    png: bytes
    is_large_format: bool
    tiles: list[bytes]
    tile_boxes: list[TileBox]


def _starts(length: int, size: int, overlap: int) -> list[int]:
    """Starts einer Achse; letzte Kachel bündig am Rand, Überlappung mind. `overlap`."""
    if length <= size:
        return [0]
    stride = size - overlap
    starts = list(range(0, length - size, stride))
    starts.append(length - size)
    return starts


def compute_tiles(width: int, height: int, size: int, overlap: int) -> list[TileBox]:
    """Kachelraster zeilenweise; deckt das Bild vollständig ab."""
    return [
        TileBox(x, y, min(x + size, width), min(y + size, height))
        for y in _starts(height, size, overlap)
        for x in _starts(width, size, overlap)
    ]


def is_large_format(page: pymupdf.Page, config: RenderConfig) -> bool:
    long_side_mm = max(page.rect.width, page.rect.height) / POINTS_PER_INCH * MM_PER_INCH
    return bool(long_side_mm >= config.large_format_min_mm)


def render_pages(
    source: Path | bytes,
    config: RenderConfig | None = None,
    plantyp_by_page: Mapping[int, str] | None = None,
) -> list[RenderedPage]:
    """Jede Seite mit konfiguriertem dpi rendern; Grossformate zusätzlich in Kacheln."""
    config = config or RenderConfig()
    plantyp_by_page = plantyp_by_page or {}
    result: list[RenderedPage] = []
    with _open(source) as doc:
        for index, page in enumerate(doc):
            number = index + 1
            dpi = config.dpi_for(plantyp_by_page.get(number))
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            large = is_large_format(page, config)
            boxes: list[TileBox] = []
            tiles: list[bytes] = []
            if large:
                boxes = compute_tiles(
                    pix.width, pix.height, config.tile_size_px, config.tile_overlap_px
                )
                for box in boxes:
                    clip = pymupdf.IRect(box.x0, box.y0, box.x1, box.y1)  # type: ignore[no-untyped-call]
                    tiles.append(_crop(pix, clip))
            result.append(
                RenderedPage(
                    number, dpi, pix.width, pix.height, pix.tobytes("png"), large, tiles, boxes
                )
            )
    return result


def _crop(pix: pymupdf.Pixmap, clip: pymupdf.IRect) -> bytes:
    tile = pymupdf.Pixmap(pix.colorspace, clip, pix.alpha)  # type: ignore[no-untyped-call]
    tile.copy(pix, clip)  # type: ignore[no-untyped-call]
    return bytes(tile.tobytes("png"))  # type: ignore[no-untyped-call]
