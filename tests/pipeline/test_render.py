import pymupdf
import pytest

from app.pipeline.render import RenderConfig, TileBox, compute_tiles, render_pages

MM = 72 / 25.4


def _pdf(width_mm: float, height_mm: float) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=width_mm * MM, height=height_mm * MM)
    page.insert_text((50, 50), "Plan")
    return bytes(doc.tobytes())


def test_default_dpi_200() -> None:
    page = render_pages(_pdf(210, 297))[0]
    assert page.dpi == 200
    assert page.width_px == round(210 / 25.4 * 200)
    assert page.png.startswith(b"\x89PNG")


def test_dpi_per_plantyp() -> None:
    config = RenderConfig(dpi_by_plantyp={"Situationsplan": 300})
    pages = render_pages(_pdf(210, 297), config, {1: "Situationsplan"})
    assert pages[0].dpi == 300
    assert render_pages(_pdf(210, 297), config, {1: "Grundriss"})[0].dpi == 200


def test_a4_has_no_tiles() -> None:
    page = render_pages(_pdf(210, 297))[0]
    assert not page.is_large_format
    assert page.tiles == [] and page.tile_boxes == []


def test_a1_is_tiled_with_geometric_count() -> None:
    config = RenderConfig(tile_size_px=2000, tile_overlap_px=200)
    page = render_pages(_pdf(594, 841), config)[0]
    assert page.is_large_format
    assert (page.width_px, page.height_px) == (4678, 6623)
    # Stride 1800: x-Starts 0,1800,2678 -> 3; y-Starts 0,1800,3600,4623 -> 4
    assert len(page.tile_boxes) == 12
    assert len(page.tiles) == 12
    assert all(t.startswith(b"\x89PNG") for t in page.tiles)


def test_tile_overlap_and_coverage() -> None:
    boxes = compute_tiles(4678, 6623, 2000, 200)
    row = [b for b in boxes if b.y0 == 0]
    for a, b in zip(row, row[1:], strict=False):
        assert a.x1 - b.x0 >= 200
    col = [b for b in boxes if b.x0 == 0]
    for a, b in zip(col, col[1:], strict=False):
        assert a.y1 - b.y0 >= 200
    assert max(b.x1 for b in boxes) == 4678
    assert max(b.y1 for b in boxes) == 6623
    assert all(b.x1 - b.x0 <= 2000 and b.y1 - b.y0 <= 2000 for b in boxes)


def test_exact_fit_and_small_image() -> None:
    assert compute_tiles(100, 100, 2000, 200) == [TileBox(0, 0, 100, 100)]
    assert len(compute_tiles(3800, 2000, 2000, 200)) == 2


def test_tile_pixel_size_matches_box() -> None:
    page = render_pages(_pdf(594, 841), RenderConfig(tile_size_px=2500, tile_overlap_px=0))[0]
    box = page.tile_boxes[-1]
    tile = pymupdf.Pixmap(page.tiles[-1])
    assert (tile.width, tile.height) == (box.x1 - box.x0, box.y1 - box.y0)


def test_invalid_config() -> None:
    with pytest.raises(ValueError):
        RenderConfig(tile_overlap_px=2000)
    with pytest.raises(ValueError):
        RenderConfig(dpi=0)
