"""The .orcshot file container (task #123) - headless-testable like
ui/file_export.py's own save_image_to_file (GdkPixbuf-based, no X11
connection needed).
"""

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

import numpy as np
import pytest

from orcshot.core.drawing import Layer
from orcshot.core.geometry import Rect
from orcshot.core.shapes import RectangleShape, TextShape
from orcshot.ui.orcshot_file import (
    InvalidOrcshotFileError,
    load_objects_file,
    load_orcshot_file,
    save_objects_file,
    save_orcshot_file,
)


def _solid_image(width=8, height=6, color=(30, 40, 50, 255)) -> np.ndarray:
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :] = color
    return image


class TestRoundTrip:
    def test_saves_and_loads_the_image_exactly(self, tmp_path):
        image = _solid_image()
        path = tmp_path / "shot.orcshot"

        save_orcshot_file(image, Layer(), path)
        loaded_image, _layer = load_orcshot_file(path)

        assert np.array_equal(loaded_image, image)

    def test_saves_and_loads_the_shape_layer(self, tmp_path):
        image = _solid_image()
        layer = Layer()
        layer.add(RectangleShape(bounds=Rect(1, 2, 3, 4)))
        layer.add(TextShape(bounds=Rect(5, 6, 50, 20), text="Hello"))
        path = tmp_path / "shot.orcshot"

        save_orcshot_file(image, layer, path)
        _image, loaded_layer = load_orcshot_file(path)

        assert list(loaded_layer) == list(layer)

    def test_empty_layer_round_trips_to_an_empty_layer(self, tmp_path):
        path = tmp_path / "shot.orcshot"
        save_orcshot_file(_solid_image(), Layer(), path)

        _image, loaded_layer = load_orcshot_file(path)

        assert len(loaded_layer) == 0

    def test_accepts_a_string_path_as_well_as_a_path_object(self, tmp_path):
        path = str(tmp_path / "shot.orcshot")
        save_orcshot_file(_solid_image(), Layer(), path)

        loaded_image, _layer = load_orcshot_file(path)

        assert loaded_image.shape[:2] == (6, 8)


class TestBackwardCompatibleAsAPlainPng:
    def test_a_saved_orcshot_file_still_opens_as_a_normal_png(self, tmp_path):
        # The trailer sits after PNG's own IEND chunk - any ordinary
        # PNG reader should just ignore it and see a normal image,
        # same trick real Windows' .greenshot format relies on.
        image = _solid_image(color=(10, 20, 30, 255))
        path = tmp_path / "shot.orcshot"
        save_orcshot_file(image, Layer(), path)

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
        assert pixbuf.get_width() == 8
        assert pixbuf.get_height() == 6


class TestInvalidFiles:
    def test_a_plain_png_with_no_trailer_raises(self, tmp_path):
        from orcshot.ui.file_export import save_image_to_file

        path = tmp_path / "plain.png"
        save_image_to_file(_solid_image(), path)

        with pytest.raises(InvalidOrcshotFileError):
            load_orcshot_file(path)

    def test_a_truncated_file_raises(self, tmp_path):
        path = tmp_path / "shot.orcshot"
        save_orcshot_file(_solid_image(), Layer(), path)
        truncated = path.read_bytes()[:5]
        path.write_bytes(truncated)

        with pytest.raises(InvalidOrcshotFileError):
            load_orcshot_file(path)

    def test_a_trailer_claiming_a_length_longer_than_the_file_raises(self, tmp_path):
        path = tmp_path / "shot.orcshot"
        save_orcshot_file(_solid_image(), Layer(), path)
        data = bytearray(path.read_bytes())
        # Corrupt the length field (the 16 bytes before the marker's
        # own 8) to claim an absurdly large shape-layer blob.
        import struct

        data[-16:-8] = struct.pack("<Q", 10**9)
        path.write_bytes(bytes(data))

        with pytest.raises(InvalidOrcshotFileError):
            load_orcshot_file(path)


class TestSaveLoadObjects:
    def test_round_trips_a_shape_layer_with_no_image_at_all(self, tmp_path):
        layer = Layer()
        layer.add(RectangleShape(bounds=Rect(1, 2, 3, 4)))
        layer.add(TextShape(bounds=Rect(5, 6, 50, 20), text="Hello"))
        path = tmp_path / "shapes.json"

        save_objects_file(layer, path)
        loaded = load_objects_file(path)

        assert list(loaded) == list(layer)

    def test_objects_file_has_no_orcshot_trailer(self, tmp_path):
        # Plain JSON, deliberately not framed like a full .orcshot file
        # - there's no image portion for a PNG reader to fall back to,
        # so pretending it's PNG-shaped would be misleading.
        path = tmp_path / "shapes.json"
        save_objects_file(Layer(), path)

        data = path.read_bytes()

        assert not data.endswith(b"ORCSHOT1")

    def test_load_objects_also_accepts_a_full_orcshot_file(self, tmp_path):
        # Real Windows' own Load Objects and Save-As-.greenshot files
        # aren't the same thing, but pulling a shape layer back out of
        # either is a reasonable thing to want - the image portion is
        # simply discarded.
        layer = Layer()
        layer.add(RectangleShape(bounds=Rect(1, 2, 3, 4)))
        path = tmp_path / "shot.orcshot"
        save_orcshot_file(_solid_image(), layer, path)

        loaded = load_objects_file(path)

        assert list(loaded) == list(layer)

    def test_an_invalid_objects_file_raises(self, tmp_path):
        path = tmp_path / "not-json.json"
        path.write_text("this is not json")

        with pytest.raises(InvalidOrcshotFileError):
            load_objects_file(path)
