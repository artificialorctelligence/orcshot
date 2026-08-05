"""The window enumeration port: what every platform adapter must provide.

Behavioral port of WindowDetails.GetTopLevelWindows / IsTopLevel from the
Windows source, needed for the active-window and window-picker capture
modes. X11's _NET_CLIENT_LIST is already curated by the window manager to
exclude child windows and desktop/panel chrome, so this port has no
equivalent of Windows' HasParent / IgnoreClasses checks; what remains is
the window-type exclusion below.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence, runtime_checkable

from greenshot_linux.core.geometry import Rect

# _NET_WM_WINDOW_TYPE values that identify desktop/panel chrome rather
# than an application window a user would want to capture — the X11
# analogue of Greenshot's WS_EX_TOOLWINDOW + IgnoreClasses(Progman/Dwm).
_CHROME_WINDOW_TYPES = frozenset(
    {
        "desktop",
        "dock",
        "toolbar",
        "utility",
        "splash",
        "notification",
        "tooltip",
        "menu",
        "dropdown_menu",
        "popup_menu",
        "combo",
        "dnd",
    }
)


@dataclass(frozen=True)
class WindowInfo:
    window_id: int
    title: str
    class_name: str
    bounds: Rect
    is_minimized: bool
    window_type: str
    process_id: Optional[int]


def is_capturable(window: WindowInfo) -> bool:
    """Whether ``window`` belongs in a window-picker list.

    Behavioral port of WindowDetails.IsTopLevel: rejects windows with no
    title or zero area, and windows identified as desktop/panel chrome.
    Minimized windows are kept, matching Greenshot's "Visible OR Iconic".
    """
    if not window.title:
        return False
    if window.bounds.width <= 0 or window.bounds.height <= 0:
        return False
    if window.window_type in _CHROME_WINDOW_TYPES:
        return False
    return True


@runtime_checkable
class WindowEnumerator(Protocol):
    """A source of window information for one display protocol."""

    def list_windows(self) -> Sequence[WindowInfo]:
        """Capturable top-level windows, already filtered by is_capturable."""

    def active_window(self) -> Optional[WindowInfo]:
        """The currently focused window, or None if none is focused."""


@runtime_checkable
class WindowActivator(Protocol):
    """Raises a specific window to the front, by window_id.

    X11's window-picker never needs this: it crops the picked window's
    rect out of a single frozen full-screen grab taken when the overlay
    opened, so whichever window is actually on top at that moment is
    already baked into the pixels, occlusion and all. Wayland has no
    equivalent of that frozen-crop trick's correctness guarantee (no
    portable API tells a picker which window is really topmost - see
    REQUIREMENTS.md's Wayland window-picker section) - the answer there
    is to activate the *clicked* window first, then grab it fresh, so
    the captured pixels are correct regardless of what was visible (or
    guessed) during hover.
    """

    def activate(self, window_id: int) -> None:
        """Raise and focus the given window. Best-effort: callers should
        still tolerate the window not actually coming to the front (a
        fresh grab afterwards is correct either way, just possibly of
        whatever ended up on top)."""
