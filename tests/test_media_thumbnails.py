"""Unit tests for the thumbnail generator -- pure function, no DB."""

import io

from PIL import Image

from miya_server.media.thumbnails import (
    THUMBNAIL_MAX_EDGE,
    generate_thumbnail_bytes,
    thumbnail_relative_path_for,
)


def _write_image(path, size, mode="RGB"):
    # PNG can't hold CMYK; JPEG can't hold RGBA/P/L-with-alpha. Pick per mode.
    fmt = "JPEG" if mode == "CMYK" else "PNG"
    Image.new(mode, size).save(path, format=fmt)
    return path


def test_downscales_large_landscape_preserving_aspect(tmp_path):
    src = _write_image(tmp_path / "big.png", (1600, 900))
    data, w, h = generate_thumbnail_bytes(src)
    assert max(w, h) == THUMBNAIL_MAX_EDGE
    assert (w, h) == (512, 288)  # 16:9 preserved
    assert Image.open(io.BytesIO(data)).format == "WEBP"


def test_never_upscales_small_source(tmp_path):
    src = _write_image(tmp_path / "small.png", (300, 200))
    _, w, h = generate_thumbnail_bytes(src)
    assert (w, h) == (300, 200)


def test_portrait_orientation_clamps_height(tmp_path):
    src = _write_image(tmp_path / "tall.png", (900, 1600))
    _, w, h = generate_thumbnail_bytes(src)
    assert (w, h) == (288, 512)


def test_non_rgb_modes_encode_without_error(tmp_path):
    for mode in ("RGBA", "P", "L", "CMYK"):
        ext = "jpg" if mode == "CMYK" else "png"
        src = _write_image(tmp_path / f"{mode}.{ext}", (800, 600), mode=mode)
        data, _, _ = generate_thumbnail_bytes(src)
        assert Image.open(io.BytesIO(data)).format == "WEBP"


def test_undecodable_source_raises(tmp_path):
    src = tmp_path / "bogus.png"
    src.write_bytes(b"not actually a png")
    try:
        generate_thumbnail_bytes(src)
    except Exception:  # noqa: BLE001 -- exact exception type is Pillow's business
        return
    raise AssertionError("expected generate_thumbnail_bytes to raise on garbage input")


def test_thumbnail_relative_path_keeps_dir_and_stem():
    assert (
        thumbnail_relative_path_for("photos/abc-123.jpg") == "photos/abc-123_thumb.webp"
    )
    assert (
        thumbnail_relative_path_for("authors/de-ad.png") == "authors/de-ad_thumb.webp"
    )
