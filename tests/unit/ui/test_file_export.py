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

from greenshot_linux.ui.file_export import save_image_to_file
from greenshot_linux.ui.gdk_convert import pixbuf_to_numpy


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
