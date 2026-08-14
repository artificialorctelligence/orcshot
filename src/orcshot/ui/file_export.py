"""Saving a composited image to a file.

Format is inferred from the path's extension via GdkPixbuf's own save
types, defaulting to PNG - lossless, matching what a screenshot tool
needs by default - for anything unrecognized.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from orcshot.ui.gdk_convert import numpy_to_pixbuf

_EXTENSION_TO_TYPE = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".bmp": "bmp",
    ".tif": "tiff",
    ".tiff": "tiff",
    ".ico": "ico",
}


def save_image_to_file(image: np.ndarray, path, jpeg_quality: int = None) -> None:
    """``jpeg_quality`` (0-100, faithful port of Windows' own
    OutputFileJpegQuality - task #95's Output tab, settings.
    OutputSettings) is only meaningful for JPEG output and ignored
    otherwise, matching GdkPixbuf's own savev - passing a "quality"
    option to a format that doesn't recognize it is silently a no-op,
    not an error.
    """
    path = Path(path)
    file_type = _EXTENSION_TO_TYPE.get(path.suffix.lower(), "png")
    option_keys, option_values = [], []
    if jpeg_quality is not None and file_type == "jpeg":
        option_keys, option_values = ["quality"], [str(jpeg_quality)]
    numpy_to_pixbuf(image).savev(str(path), file_type, option_keys, option_values)


def orcshot_cache_dir() -> Path:
    """$XDG_CACHE_HOME/orcshot - the shared home for temp image
    exports handed to another process (an external editor, an external
    command), *not* system /tmp. Originally established in
    ui/editor_window.py's own "Open in External Editor" button (see
    EditorWindow._external_editor_cache_dir's full writeup for why):
    a Flatpak-sandboxed target app's /tmp is its own private tmpfs
    regardless of filesystem permissions, confirmed live, so a file
    written to the real /tmp is invisible inside the sandbox even
    though it exists on the host - $XDG_CACHE_HOME (under home) is
    genuinely shared instead. Same reasoning applies to any external
    process this app hands a temp file to, not just the editor button,
    so this is the one shared implementation both use.

    mode=0o700 rather than relying on umask: these temp files can
    contain sensitive screen content, and while callers typically
    force 0600 on the individual file regardless of umask, the
    *directory* itself would otherwise inherit whatever the umask
    allows (typically 0755 - world-listable) - restricting it too
    means even filenames/mtimes in here aren't enumerable by another
    local user. Only takes effect on first creation.
    """
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    directory = cache_home / "orcshot"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory
