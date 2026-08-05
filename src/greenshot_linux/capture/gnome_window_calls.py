"""Window enumeration and activation under GNOME/Wayland, via the
bundled "window-calls" GNOME Shell extension (see THIRD_PARTY_NOTICES.md
and this file's own extension.js for what it is and why it's needed -
Wayland has no portable window-enumeration API, confirmed via research
documented in REQUIREMENTS.md's Wayland window-picker section).

Implements both WindowEnumerator and WindowActivator from
capture/window.py: List() gives real per-window bounds for hover-
highlighting, and Activate() (patched to also call raise()) lets
window_picker.py force the clicked window to the front before doing a
fresh grab - live-verified this is necessary and sufficient to get
correct captured content even though the extension's own stacking data
('layer') is too coarse to tell overlapping windows apart on its own.

GNOME's Meta.WindowType enum, used to map List()'s integer window_type
into the same lowercase strings x11_window.py already produces (so
is_capturable's exclusion set applies identically to both backends):
ordering per Mutter's public Meta.WindowType enum, values mapped to
match window.py's _CHROME_WINDOW_TYPES vocabulary rather than Mutter's
own member names (e.g. SPLASHSCREEN -> "splash"). Index 0 (NORMAL) is
live-confirmed against real test output; the rest follow the same
stable, long-published enum ordering but weren't independently
re-verified index by index.
"""

from __future__ import annotations

import json

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from greenshot_linux.capture.window import WindowInfo, is_capturable
from greenshot_linux.core.geometry import Rect

BUS_NAME = "org.gnome.Shell"
OBJECT_PATH = "/org/gnome/Shell/Extensions/Windows"
INTERFACE = "org.gnome.Shell.Extensions.Windows"

_META_WINDOW_TYPE_NAMES = (
    "normal", "desktop", "dock", "dialog", "modal_dialog", "toolbar",
    "menu", "utility", "splash", "dropdown_menu", "popup_menu",
    "tooltip", "notification", "combo", "dnd", "override_other",
)


class GnomeWindowCallsUnavailable(RuntimeError):
    """The extension isn't installed, enabled, or responding - callers
    should fall back to disabling window-picker rather than raising
    this up to the user as an error."""


def _window_type_name(value) -> str:
    if isinstance(value, int) and 0 <= value < len(_META_WINDOW_TYPE_NAMES):
        return _META_WINDOW_TYPE_NAMES[value]
    return "unknown"


def parse_window_info(raw: dict) -> WindowInfo:
    """Pure: List()'s per-window JSON dict -> WindowInfo. Split out from
    the D-Bus call itself so this mapping has unit coverage that
    doesn't need a real GNOME Shell session to exercise."""
    return WindowInfo(
        window_id=raw["id"],
        title=raw.get("title") or "",
        class_name=raw.get("wm_class") or "",
        bounds=Rect(raw["x"], raw["y"], raw["x"] + raw["width"], raw["y"] + raw["height"]),
        is_minimized=bool(raw.get("minimized")),
        window_type=_window_type_name(raw.get("window_type")),
        process_id=raw.get("pid"),
    )


class GnomeWindowCallsBackend:
    """Real D-Bus adapter. Implements both WindowEnumerator and
    WindowActivator - naturally the same underlying extension, so one
    object plays both roles rather than splitting into two for no
    reason."""

    def __init__(self):
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def _call(self, method: str, arg_variant=None, arg_type="()"):
        args = arg_variant if arg_variant is not None else GLib.Variant(arg_type, ())
        try:
            reply = self._bus.call_sync(
                BUS_NAME, OBJECT_PATH, INTERFACE, method, args,
                None, Gio.DBusCallFlags.NONE, -1, None,
            )
        except GLib.Error as error:
            raise GnomeWindowCallsUnavailable(
                f"window-calls extension call {method} failed: {error.message}"
            ) from error
        return reply.unpack()

    def _list_raw(self) -> list[dict]:
        (raw,) = self._call("List")
        return json.loads(raw)

    def list_windows(self):
        windows = [parse_window_info(w) for w in self._list_raw()]
        return [w for w in windows if is_capturable(w)]

    def active_window(self):
        for raw in self._list_raw():
            if raw.get("focus"):
                return parse_window_info(raw)
        return None

    def activate(self, window_id: int) -> None:
        self._call("Activate", GLib.Variant("(u)", (window_id,)))


def is_available() -> bool:
    """Empirical check, matching this project's established pattern
    (see hotkey_setup.cinnamon_keybindings_available) of probing real
    behavior rather than assuming from desktop/session name alone - a
    GNOME session with the extension not installed, not enabled, or an
    incompatible Shell version all look the same from the outside
    (window-picker should just be unavailable, not crash)."""
    try:
        GnomeWindowCallsBackend().list_windows()
        return True
    except GnomeWindowCallsUnavailable:
        return False
