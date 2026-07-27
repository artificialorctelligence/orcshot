"""Saving a composited image to a file.

Format is inferred from the path's extension via GdkPixbuf's own save
types, defaulting to PNG - lossless, matching what a screenshot tool
needs by default - for anything unrecognized.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from greenshot_linux.ui.gdk_convert import numpy_to_pixbuf

_EXTENSION_TO_TYPE = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".bmp": "bmp",
    ".tif": "tiff",
    ".tiff": "tiff",
    ".ico": "ico",
}


def save_image_to_file(image: np.ndarray, path) -> None:
    path = Path(path)
    file_type = _EXTENSION_TO_TYPE.get(path.suffix.lower(), "png")
    numpy_to_pixbuf(image).savev(str(path), file_type, [], [])
