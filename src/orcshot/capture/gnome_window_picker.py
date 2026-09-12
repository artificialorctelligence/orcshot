"""D-Bus client for the bundled orcshot-clipboard extension's
interactive window-picker capability - the window-picker counterpart
to gnome_region_select.py (see that module's own docstring for the
shared architecture/rationale, task #77). Mirrors it closely: the
*entire* interaction (frozen backdrop, hover-highlight over real
window geometry, click-to-select + raise, and the post-capture
destination picker) runs inside the Shell/Mutter compositor process as
one continuous flow, using the exact same StartWindowPicker reply
shape and pickDestinationAsync as region-select does.

Real window geometry/content comes straight from Shell's own native
`global.get_window_actors()`/`Meta.Window` API now that the caller is
Shell-side too, not the bundled window-calls extension's own D-Bus
interface - the "worth checking during implementation" note in
REQUIREMENTS.md's original plan panned out.
"""

from __future__ import annotations

import sys
import traceback

import gi


from orcshot.capture.shell_bridge import ShellRequestError, ShellUnavailable, get_bridge
from orcshot.capture.gnome_region_select import decode_png
from orcshot.core.geometry import Rect

CAPABILITY = "window-picker"


def is_available() -> bool:
    return get_bridge().has(CAPABILITY)


def start_window_picker(on_selected, on_cancelled=None) -> None:
    """Asks the Shell extension to run the whole interactive window-
    picker-through-destination-choice flow. Returns immediately -
    ``on_selected(image, absolute_rect, destination, title)`` or
    ``on_cancelled()`` fires later, once the user finishes the entire
    interaction (click a window, then pick a destination) or cancels
    out of it at any point.

    ``title`` (task #139) - the picked window's title, straight from
    extension.js's own Meta.Window.get_title() - fills in
    core/filename_pattern.py's ``${title}`` token.
    """
    def on_result(result: dict):
        try:
            image = decode_png(bytes(result["pngBytes"]))
            x, y, w, h = result["x"], result["y"], result["width"], result["height"]
            on_selected(image, Rect(x, y, x + w, y + h), result["destination"], result["title"])
        except Exception:
            print("[gnome_window_picker] exception in on_result:", file=sys.stderr, flush=True)
            traceback.print_exc()

    def on_error(_error):
        if on_cancelled is not None:
            on_cancelled()

    try:
        get_bridge().request_async(CAPABILITY, {}, on_result, on_error)
    except ShellUnavailable:
        on_error(None)
