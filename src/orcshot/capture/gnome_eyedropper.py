"""D-Bus client for the bundled orcshot-clipboard extension's
interactive eyedropper capability - the color-picking counterpart to
gnome_region_select.py/gnome_window_picker.py (see gnome_region_select.py's
own docstring for the shared architecture/rationale, task #77).

Unlike region-select/window-picker, there's no destination picker
chained onto this one at all - the whole point of the eyedropper is to
hand a single sampled colour back to its caller (the colour dialog),
not to capture an image. The Shell-side overlay (frozen backdrop,
press-drag-release sampling, the magnifier loupe) runs entirely inside
the Shell/Mutter compositor process, same as the other two.
"""

from __future__ import annotations

import sys
import traceback

import gi


from orcshot.capture.shell_bridge import ShellRequestError, ShellUnavailable, get_bridge

CAPABILITY = "eyedropper"


def is_available() -> bool:
    return get_bridge().has(CAPABILITY)


def start_eyedropper(on_picked, on_cancelled=None) -> None:
    """Asks the Shell extension to run the interactive eyedropper.
    Returns immediately - ``on_picked(color)`` (an (r, g, b, a) tuple,
    each 0-255) or ``on_cancelled()`` fires later, once the user
    finishes or cancels the press-drag-release gesture."""
    def on_result(result: dict):
        try:
            on_picked((result["r"], result["g"], result["b"], result["a"]))
        except Exception:
            print("[gnome_eyedropper] exception in on_result:", file=sys.stderr, flush=True)
            traceback.print_exc()

    def on_error(_error):
        if on_cancelled is not None:
            on_cancelled()

    try:
        get_bridge().request_async(CAPABILITY, {}, on_result, on_error)
    except ShellUnavailable:
        on_error(None)
