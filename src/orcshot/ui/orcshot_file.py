"""The .orcshot file container (task #123): the real captured image,
PNG-encoded, followed by the shape layer as a JSON blob, followed by
an 8-byte little-endian length and an 8-byte ASCII marker - loosely
modeled on real Windows Greenshot's own .greenshot container shape
(PNG + trailing blob + Int64 length + ASCII version marker,
GreenshotFileFormatHandler.cs:49-133 in the reference clone: valid PNG
readers ignore trailing bytes after IEND, so the file opens fine as a
plain image in anything that doesn't know about the trailer) but not
byte-compatible with it - see core/orcshot_format.py's own module
docstring for why, and task #124 for the separate, narrower NRBF
writer that actually targets real Greenshot compatibility.

    [PNG bytes for the captured image]
    [UTF-8 JSON bytes for the shape layer - core/orcshot_format.py]
    [8 bytes: shape-layer JSON length, little-endian uint64]
    [8 bytes: b"ORCSHOT1" marker]

GdkPixbuf-based (not GTK-widget-based), so headless-testable like
ui/file_export.py's own save_image_to_file - no X11 connection or
live window needed, matching that module's own precedent for why this
lives in ui/ rather than core/ despite having real unit tests.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

import numpy as np

from orcshot.core.drawing import Layer
from orcshot.core.orcshot_format import deserialize_layer_into, serialize_layer
from orcshot.ui.gdk_convert import numpy_to_pixbuf, pixbuf_to_numpy

MARKER = b"ORCSHOT1"
_LENGTH_STRUCT = struct.Struct("<Q")  # little-endian uint64
_TRAILER_SIZE = _LENGTH_STRUCT.size + len(MARKER)


class InvalidOrcshotFileError(ValueError):
    pass


def save_orcshot_file(image: np.ndarray, layer: Layer, path) -> None:
    path = Path(path)
    ok, png_bytes = numpy_to_pixbuf(image).save_to_bufferv("png", [], [])
    if not ok:
        raise InvalidOrcshotFileError("Failed to encode the image as PNG")
    json_bytes = json.dumps(serialize_layer(layer)).encode("utf-8")
    with open(path, "wb") as f:
        f.write(bytes(png_bytes))
        f.write(json_bytes)
        f.write(_LENGTH_STRUCT.pack(len(json_bytes)))
        f.write(MARKER)


def load_orcshot_file(path) -> tuple[np.ndarray, Layer]:
    """Returns (image, layer). Raises InvalidOrcshotFileError if
    ``path`` isn't a file this function wrote - a plain PNG (no
    trailer at all) is the expected, common way this happens, not
    just a corrupted .orcshot file.
    """
    path = Path(path)
    data = path.read_bytes()
    if len(data) < _TRAILER_SIZE or data[-len(MARKER):] != MARKER:
        raise InvalidOrcshotFileError(f"{path} has no .orcshot trailer - not a file this format wrote")

    length = _LENGTH_STRUCT.unpack(data[-_TRAILER_SIZE:-len(MARKER)])[0]
    json_start = len(data) - _TRAILER_SIZE - length
    if json_start < 0:
        raise InvalidOrcshotFileError(f"{path}'s trailer claims a shape-layer length longer than the file itself")

    png_bytes = data[:json_start]
    json_bytes = data[json_start : json_start + length]

    loader = GdkPixbuf.PixbufLoader()
    try:
        loader.write(png_bytes)
        loader.close()
    except Exception as exc:
        raise InvalidOrcshotFileError(f"{path}'s image portion isn't a valid PNG") from exc
    image = pixbuf_to_numpy(loader.get_pixbuf())

    try:
        shape_data = json.loads(json_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidOrcshotFileError(f"{path}'s shape-layer blob isn't valid JSON") from exc

    layer = Layer()
    deserialize_layer_into(layer, shape_data)
    return image, layer


def save_objects_file(layer: Layer, path) -> None:
    """Object menu > Save Objects - faithful in shape to real Windows'
    own SaveElementsToStream (Surface.cs:729-751): the shape layer
    only, deliberately *without* an image at all, distinct from the
    full save_orcshot_file above. Plain JSON, no PNG/trailer framing -
    there's no image portion for a PNG reader to fall back to opening
    here the way there is for a full .orcshot file, so pretending this
    is PNG-shaped would be misleading, not backward-compatible.
    """
    path = Path(path)
    path.write_text(json.dumps(serialize_layer(layer)))


def load_objects_file(path) -> Layer:
    """Object menu > Load Objects - accepts either a plain Save-
    Objects file (see save_objects_file above) or a full .orcshot file
    (image discarded, only the shape layer used) transparently, since
    both are reasonable things to want to pull a shape layer back out
    of. Distinguishes them by the same trailer marker
    load_orcshot_file checks for.
    """
    path = Path(path)
    data = path.read_bytes()
    if len(data) >= _TRAILER_SIZE and data[-len(MARKER):] == MARKER:
        _image, layer = load_orcshot_file(path)
        return layer

    try:
        shape_data = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidOrcshotFileError(f"{path} isn't a valid Save Objects file or .orcshot file") from exc

    layer = Layer()
    deserialize_layer_into(layer, shape_data)
    return layer
