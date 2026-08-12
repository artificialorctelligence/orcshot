"""X11 window enumeration via EWMH properties.

_NET_CLIENT_LIST_STACKING (falling back to plain _NET_CLIENT_LIST if a
WM doesn't advertise it) is maintained by the window manager itself and
already excludes child windows and desktop/panel chrome — unlike
Windows' EnumWindows, which returns every window and leaves the caller
to filter by parentage and class name. That's why this adapter has no
equivalent of WindowDetails' HasParent / IgnoreClasses checks: the WM
did that work already. What's left to filter is window type (see
window.py).

list_windows() specifically needs the *stacking* variant, not just
"a" client list: it returns windows bottom-to-top, so the topmost
(actually-visible) window among several overlapping/maximized ones on
the same monitor is reliably the *last* entry - what the window-picker
overlay (ui/window_picker.py) relies on to resolve overlaps correctly.
Plain _NET_CLIENT_LIST has no such ordering guarantee (commonly
initial-mapping order); this was a real bug caught via live testing
(see test_window_enumerator_contract.py's
test_active_window_is_last_in_list_windows_stacking_order) - the
active window landed second in _NET_CLIENT_LIST's order on this
machine, not last, causing the picker to highlight a completely
different, occluded window depending on which pixel row the cursor
was over.

Requires an EWMH-compliant window manager (Cinnamon/Muffin, GNOME/Mutter,
KDE/KWin all qualify).
"""

from __future__ import annotations

from typing import Optional, Sequence

from Xlib import X
from Xlib.display import Display

from orcshot.capture.window import WindowInfo, is_capturable
from orcshot.core.geometry import Rect

_WINDOW_TYPE_ATOM_SUFFIX = "_NET_WM_WINDOW_TYPE_"


class X11WindowEnumerationUnavailable(RuntimeError):
    pass


class X11WindowEnumerator:
    def __init__(self):
        self._display = Display()
        self._root = self._display.screen().root
        if self._get_property(self._root, "_NET_CLIENT_LIST") is None:
            raise X11WindowEnumerationUnavailable(
                "the window manager does not support _NET_CLIENT_LIST "
                "(EWMH); window enumeration requires an EWMH-compliant "
                "window manager"
            )

    def _get_property(self, window, atom_name):
        atom = self._display.get_atom(atom_name)
        return window.get_full_property(atom, X.AnyPropertyType)

    def _window_info(self, window_id: int) -> Optional[WindowInfo]:
        window = self._display.create_resource_object("window", window_id)

        try:
            geometry = window.get_geometry()
            offset = window.translate_coords(self._root, 0, 0)
        except Exception:
            # The window can vanish between reading _NET_CLIENT_LIST and
            # querying it (closed mid-enumeration).
            return None

        left = -offset.x
        top = -offset.y
        bounds = Rect(left, top, left + geometry.width, top + geometry.height)

        title_prop = self._get_property(window, "_NET_WM_NAME") or self._get_property(
            window, "WM_NAME"
        )
        title = _decode_text(title_prop.value) if title_prop else ""

        class_prop = self._get_property(window, "WM_CLASS")
        class_name = _decode_wm_class(class_prop.value) if class_prop else ""

        type_prop = self._get_property(window, "_NET_WM_WINDOW_TYPE")
        window_type = self._decode_window_type(type_prop.value) if type_prop else "unknown"

        state_prop = self._get_property(window, "_NET_WM_STATE")
        states = {self._display.get_atom_name(a) for a in state_prop.value} if state_prop else set()
        is_minimized = "_NET_WM_STATE_HIDDEN" in states

        pid_prop = self._get_property(window, "_NET_WM_PID")
        process_id = pid_prop.value[0] if pid_prop else None

        return WindowInfo(
            window_id=window_id,
            title=title,
            class_name=class_name,
            bounds=bounds,
            is_minimized=is_minimized,
            window_type=window_type,
            process_id=process_id,
        )

    def _decode_window_type(self, atom_ids) -> str:
        for atom_id in atom_ids:
            name = self._display.get_atom_name(atom_id)
            if name.startswith(_WINDOW_TYPE_ATOM_SUFFIX):
                return name[len(_WINDOW_TYPE_ATOM_SUFFIX):].lower()
        return "unknown"

    def list_windows(self) -> Sequence[WindowInfo]:
        client_list = self._get_property(self._root, "_NET_CLIENT_LIST_STACKING") or self._get_property(
            self._root, "_NET_CLIENT_LIST"
        )
        if client_list is None:
            return []
        windows = (self._window_info(wid) for wid in client_list.value)
        return [w for w in windows if w is not None and is_capturable(w)]

    def active_window(self) -> Optional[WindowInfo]:
        active_prop = self._get_property(self._root, "_NET_ACTIVE_WINDOW")
        if not active_prop or not active_prop.value or active_prop.value[0] == 0:
            return None
        window = self._window_info(active_prop.value[0])
        if window is None or not is_capturable(window):
            return None
        return window


def _decode_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _decode_wm_class(value) -> str:
    # WM_CLASS is "instance\x00class\x00"; the class (second part) is the
    # closer analogue of Greenshot's ClassName.
    if isinstance(value, bytes):
        parts = value.decode("latin-1", "replace").split("\x00")
        return parts[1] if len(parts) > 1 and parts[1] else parts[0]
    return str(value)
