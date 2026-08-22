"""Saving a composited image to a file.

Format is inferred from the path's extension via GdkPixbuf's own save
types, defaulting to PNG (lossless - what a screenshot tool needs by
default) for anything unrecognized. Headless-testable like the rest of
ui/gdk_convert.py - no X11 connection needed to write image files.
"""

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

import numpy as np

from orcshot.ui.file_export import orcshot_cache_dir, save_image_to_file
from orcshot.ui.gdk_convert import pixbuf_to_numpy


def solid_image(width=6, height=4, color=(40, 50, 60, 255)):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :] = color
    return image


def test_saves_a_png_that_round_trips_exactly(tmp_path):
    image = solid_image()
    path = tmp_path / "shot.png"

    save_image_to_file(image, path)

    assert path.exists()
    loaded = pixbuf_to_numpy(GdkPixbuf.Pixbuf.new_from_file(str(path)))
    assert np.array_equal(loaded, image)


def test_defaults_to_png_for_an_unrecognized_extension(tmp_path):
    image = solid_image()
    path = tmp_path / "shot.unknownext"

    save_image_to_file(image, path)

    # GdkPixbuf can still identify it as a PNG by content, regardless
    # of the odd extension on disk.
    loaded = GdkPixbuf.Pixbuf.new_from_file(str(path))
    assert loaded.get_width() == image.shape[1]


def test_infers_jpeg_from_extension(tmp_path):
    image = solid_image()
    path = tmp_path / "shot.jpg"

    save_image_to_file(image, path)

    loaded = GdkPixbuf.Pixbuf.new_from_file(str(path))
    assert loaded.get_width() == image.shape[1]
    assert loaded.get_height() == image.shape[0]


def test_accepts_a_string_path_as_well_as_a_path_object(tmp_path):
    image = solid_image()
    path = str(tmp_path / "shot.png")

    save_image_to_file(image, path)

    loaded = pixbuf_to_numpy(GdkPixbuf.Pixbuf.new_from_file(path))
    assert np.array_equal(loaded, image)


def noisy_image(width=64, height=64):
    # A flat solid color compresses too well under JPEG's DCT regardless
    # of quality to show a size difference - random noise doesn't.
    rng = np.random.default_rng(0)
    image = rng.integers(0, 256, size=(height, width, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    return image


def test_jpeg_quality_affects_output_file_size(tmp_path):
    image = noisy_image()

    save_image_to_file(image, tmp_path / "low.jpg", jpeg_quality=10)
    save_image_to_file(image, tmp_path / "high.jpg", jpeg_quality=95)

    assert (tmp_path / "low.jpg").stat().st_size < (tmp_path / "high.jpg").stat().st_size


def test_jpeg_export_flattens_transparency_to_a_genuine_rgb_pixbuf(tmp_path):
    """JPEG has no alpha channel - a naive RGBA-flagged pixbuf (even
    with every alpha byte set to 255) is accepted by this dev
    machine's own GdkPixbuf JPEG backend, but rejected outright by
    Ubuntu 26.04's newer glycin-based one ("does not support the color
    type Rgba8"), confirmed live via a real Launchpad PPA build
    failure. A regression here wouldn't be caught by this machine's
    own backend, so this asserts the *saved file itself* has no alpha
    channel at all, not just that saving didn't raise.
    """
    image = solid_image(color=(200, 50, 50, 128))  # half-transparent red
    path = tmp_path / "shot.jpg"

    save_image_to_file(image, path)

    loaded = GdkPixbuf.Pixbuf.new_from_file(str(path))
    assert loaded.get_n_channels() == 3
    assert not loaded.get_has_alpha()
    # Composited onto white at 50% alpha: red 200 -> ~228, green/blue
    # 50 -> ~152 - loose bounds since JPEG is lossy.
    pixel = pixbuf_to_numpy(loaded)[0, 0]
    assert 210 <= pixel[0] <= 245
    assert 135 <= pixel[1] <= 170


def test_jpeg_quality_is_ignored_for_non_jpeg_formats(tmp_path):
    image = solid_image()
    path = tmp_path / "shot.png"

    save_image_to_file(image, path, jpeg_quality=1)  # must not raise

    assert path.exists()


def test_cache_dir_is_under_xdg_cache_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    directory = orcshot_cache_dir()

    assert directory == tmp_path / "orcshot"
    assert directory.is_dir()


def test_cache_dir_is_created_with_restricted_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    directory = orcshot_cache_dir()

    assert (directory.stat().st_mode & 0o777) == 0o700
