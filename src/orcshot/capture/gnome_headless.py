"""Headless capture on GNOME Wayland, through the Shell extension
(BACKLOG #225).

The extension is the only route, not the preferred one. This project's
own SpikePortalGnome established that xdg-desktop-portal's Screenshot
answers `response_code=2`, "Only the focused app is allowed to show a
system access dialog", to any process with no focused GUI window - which
a headless CLI can never have. An extension runs inside the compositor
and does not have to ask.

The request is bounded, unlike every interactive capture kind: those end
in a human choosing a destination, so they use request_async with no
timeout. This one returns as soon as the Shell has composited, so the
blocking request() with a real timeout is right.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from orcshot.capture.gnome_region_select import decode_png
from orcshot.capture.gnome_window_calls import parse_window_info
from orcshot.capture.modes import HeadlessCaptureError, resolve_window_for_headless_capture
from orcshot.capture.window import is_capturable
from orcshot.ui.file_export import save_image_to_file

CAPABILITY = "capture-rect-headless"

# Bounded, unlike the interactive kinds: the Shell composites and
# answers, with no human in between.
_TIMEOUT_MS = 10000


def is_available() -> bool:
    from orcshot.capture.shell_bridge import get_bridge

    return get_bridge().has(CAPABILITY)


def capture_png_to(path: str, window_title: Optional[str], session=None) -> None:
    """Capture through the Shell extension and write ``path``.

    Raises HeadlessCaptureError if the extension cannot do it - the
    capability is missing, or the named window cannot be captured
    correctly.
    """
    if session is None:
        from orcshot.capture.shell_bridge import HeadlessShellSession

        session = HeadlessShellSession()

    try:
        bridge = session.open()
        if not bridge.has(CAPABILITY):
            # Fails closed, deliberately (#225 decision 3): until
            # extensions.gnome.org accepts a version carrying this
            # handler, say so rather than assume.
            raise HeadlessCaptureError(
                "the installed Orcshot GNOME Shell extension cannot capture headlessly - "
                "it predates this feature, or the session is still running a cached older copy"
            )
        region = _region_for(bridge, window_title)
        result = bridge.request(CAPABILITY, region, timeout_ms=_TIMEOUT_MS)
        _write(result["pngBytes"], path)
    finally:
        session.close()


def _region_for(bridge, window_title: Optional[str]) -> dict:
    if window_title is None:
        # No enumeration for a full-screen capture: the Shell already
        # knows the stage's own size, and a whole-screen grab has no
        # need to know what windows exist.
        return {}

    raw_windows = json.loads(bridge.request("list-windows", {}, timeout_ms=_TIMEOUT_MS)["windows"])
    windows = [window for window in map(parse_window_info, raw_windows) if is_capturable(window)]
    # GNOME answers the workspace question itself - list-windows already
    # carries in_current_workspace, so unlike X11 nothing is derived.
    on_current_workspace = {raw["id"]: bool(raw.get("in_current_workspace", True)) for raw in raw_windows}

    target = resolve_window_for_headless_capture(
        windows, lambda window: on_current_workspace.get(window.window_id, True), window_title
    )
    bounds = target.bounds
    return {"x": bounds.left, "y": bounds.top, "width": bounds.width, "height": bounds.height}


def _write(png_bytes: bytes, path: str) -> None:
    """The Shell already produced a PNG. When that is what was asked
    for, write it through: decoding it to an array and re-encoding it
    would be real work with nothing consuming the pixels in between.
    """
    if path.lower().endswith(".png"):
        Path(path).write_bytes(bytes(png_bytes))
        return
    save_image_to_file(decode_png(bytes(png_bytes)), path)
