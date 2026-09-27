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


def capture_png_to(path: str, window_title: Optional[str], session=None, screen_layout=None) -> None:
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
        region = _region_for(bridge, window_title, screen_layout)
        result = bridge.request(CAPABILITY, region, timeout_ms=_TIMEOUT_MS)
        _write(result["pngBytes"], path)
    finally:
        session.close()


def _region_for(bridge, window_title: Optional[str], screen_layout=None) -> dict:
    if window_title is None:
        # An explicit rectangle, not an empty dict. The handler
        # destructures {x, y, width, height} and has no fallback, so
        # sending {} hands composite_to_stream four undefineds and fails
        # inside the Shell - on the commonest path this feature has.
        # (An earlier version did exactly that, on the strength of a
        # comment claiming "the Shell already knows the stage's own
        # size". It does not, and nobody had checked. Found in review,
        # 2026-09-27.)
        #
        # The geometry comes from GDK rather than from the Shell: it is
        # the same gdk_screen_layout WaylandCaptureBackend.screen_layout
        # already uses, it needs no portal and shows no prompt, and it
        # keeps the fix on this side of the D-Bus boundary - which
        # matters, because changing the extension means another
        # extensions.gnome.org review.
        #
        # No enumeration either way: a whole-screen grab has no need to
        # know what windows exist.
        layout = screen_layout if screen_layout is not None else _gdk_screen_layout()
        bounds = layout.virtual_bounds
        return {"x": bounds.left, "y": bounds.top, "width": bounds.width, "height": bounds.height}

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


def _gdk_screen_layout():
    """The whole virtual screen, spanning every monitor."""
    from gi.repository import Gdk

    from orcshot.capture.gdk_screen_layout import gdk_screen_layout

    display = Gdk.Display.get_default()
    if display is None:
        raise HeadlessCaptureError("no display: cannot work out the screen size to capture")
    return gdk_screen_layout(display)


def _write(png_bytes: bytes, path: str) -> None:
    """The Shell already produced a PNG. When that is what was asked
    for, write it through: decoding it to an array and re-encoding it
    would be real work with nothing consuming the pixels in between.
    """
    if path.lower().endswith(".png"):
        Path(path).write_bytes(bytes(png_bytes))
        return
    save_image_to_file(decode_png(bytes(png_bytes)), path)
