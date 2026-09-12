"""Clipboard support under GNOME/Wayland, via Orcshot's GNOME Shell
extension (orcshot@orcshot.org - this project's own, wholly original
code; see its capture.js docstring for why it exists and
REQUIREMENTS.md's "Clipboard under Wayland" section for the full
write-up). Since the 2026-09-11 spec the app never calls the Shell:
this asks through capture/shell_bridge.py (a request the extension
picks up and answers), which is what makes it work identically under
a strict snap, a Flatpak, and the .deb.

Preferred over wayland_clipboard.py's invisible-window/focus-wait
technique when available: this calls into St.Clipboard's privileged,
Shell-side access directly, with no client-side focus requirement to
satisfy at all, and no brief window (and its window-list reflow) to
show. Falls back to that technique when the extension isn't installed,
enabled, or responding - same "probe real behavior, never assume from
session/desktop name alone" pattern this project already uses for
window-calls (see capture/gnome_window_calls.py).
"""

from __future__ import annotations

import gi

import numpy as np

from orcshot.ui.gdk_convert import numpy_to_pixbuf

from orcshot.capture.shell_bridge import ShellRequestError, get_bridge

CAPABILITY = "set-clipboard-image"


class GnomeClipboardUnavailable(RuntimeError):
    """The extension isn't installed, enabled, or responding - callers
    should fall back to wayland_clipboard.py's technique rather than
    raising this up to the user as an error."""


def _encode_png(image: np.ndarray) -> bytes:
    pixbuf = numpy_to_pixbuf(image)
    success, buffer = pixbuf.save_to_bufferv("png", [], [])
    if not success:
        raise ValueError("failed to encode image as PNG")
    return bytes(buffer)


class GnomeClipboardBackend:
    def set_image(self, image: np.ndarray) -> None:
        try:
            get_bridge().request(CAPABILITY, {"pngBytes": _encode_png(image)}, timeout_ms=5000)
        except ShellRequestError as error:
            raise GnomeClipboardUnavailable(f"Shell extension {CAPABILITY} failed: {error}") from error


def is_available() -> bool:
    """A capability the extension announced in Hello - a dictionary
    lookup, no probe, and no side effect on the user's clipboard."""
    return get_bridge().has(CAPABILITY)
