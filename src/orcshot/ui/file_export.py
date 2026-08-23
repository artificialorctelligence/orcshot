"""Saving a composited image to a file.

Format is inferred from the path's extension via GdkPixbuf's own save
types, defaulting to PNG - lossless, matching what a screenshot tool
needs by default - for anything unrecognized.
"""

from __future__ import annotations

import os
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib

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


def _flatten_to_rgb_pixbuf(image: np.ndarray) -> GdkPixbuf.Pixbuf:
    """JPEG has no alpha channel at all - real Windows' own JPEG
    encoder (System.Drawing) has the same constraint, so this isn't a
    new design question, just one this port hadn't hit yet. Composites
    onto white first (matching every other major image editor's
    default flatten background - GIMP, Photoshop, etc. - when
    exporting to a non-alpha format), then builds a genuine 3-channel,
    has_alpha=False pixbuf.

    Confirmed live (task #149-adjacent, PPA build failure on Ubuntu
    26.04/"resolute"): just zeroing the array's alpha channel while
    keeping it 4-channel via numpy_to_pixbuf isn't enough - Ubuntu
    24.04's older GdkPixbuf JPEG backend silently discarded alpha, but
    26.04's newer glycin-based one rejects an RGBA-flagged pixbuf
    outright ("does not support the color type Rgba8"), evidently
    checking the pixbuf's own declared color type rather than the
    actual alpha values.
    """
    rgb = image[:, :, :3].astype(np.float64)
    alpha = image[:, :, 3:4].astype(np.float64) / 255.0
    flattened = np.round(rgb * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)
    height, width = flattened.shape[:2]
    rowstride = width * 3
    data = np.ascontiguousarray(flattened).tobytes()
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(data), GdkPixbuf.Colorspace.RGB, False, 8, width, height, rowstride
    )


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
    if file_type == "jpeg":
        _flatten_to_rgb_pixbuf(image).savev(str(path), file_type, option_keys, option_values)
        return
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


def orcshot_visible_temp_dir(home: Path = None) -> Path:
    """~/Orcshot - task #166: orcshot_cache_dir above isn't enough for
    every sandboxed target. A Flatpak-confined app typically gets
    access to ~/.cache/* (the commonly-granted xdg-cache permission,
    which is *why* orcshot_cache_dir works for Flatpak targets) - but
    a Snap-confined app's "home" interface grants the opposite: plain,
    non-hidden paths under $HOME, explicitly excluding any path with a
    hidden (dot-prefixed) ancestor. Every XDG convention (~/.cache,
    ~/.config, ~/.local) is hidden by definition, so satisfying Snap
    needs a real, visible top-level folder instead - confirmed live
    (direflail, task #166): a Snap-confined Krita reproducibly failed
    to read a file under ~/.cache/orcshot/ with the exact same error
    both through Orcshot and run standalone against a manually-placed
    file, ruling out a race/timing cause.

    Used only for Snap-confined external commands (see
    external_commands.py's own _is_snap_command) - orcshot_cache_dir
    remains the default for everything else, so this new visible
    folder only appears at all when it's actually needed.

    mode=0o700, same reasoning as orcshot_cache_dir - visible in a
    file manager doesn't mean readable by other local users; Snap's
    AppArmor confinement is enforced on top of normal Unix permissions,
    not instead of them, so restricting this to the owning user is
    still safe and doesn't defeat the Snap-visibility fix (Snap's
    confined process runs as this same Unix user).
    """
    if home is None:
        home = Path.home()
    directory = home / "Orcshot"
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory
