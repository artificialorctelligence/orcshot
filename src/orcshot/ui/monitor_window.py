"""Shared per-monitor overlay window for Wayland's multi-window capture
overlays (region-select, window-picker, eyedropper).

X11 uses a single Gtk.WindowType.POPUP spanning the whole virtual
screen, positioned via an absolute move() - see region_select.py's
module docstring for why POPUP beats a normal TOPLEVEL there (window
manager clamping). Wayland forbids clients from setting absolute
screen position at all (confirmed live: "temporary window without
parent, application will not be able to position it on screen"), so
that trick doesn't work - fullscreen_on_monitor() is the portable
Wayland-safe replacement, but it only fills *one* output, so getting
the same whole-virtual-screen coverage needs one TOPLEVEL window per
monitor instead of one POPUP spanning all of them.

Each MonitorWindow only knows its own monitor's global offset, and
translates event coordinates to/from the shared virtual-screen
coordinate space at that boundary - callers always work in global
coordinates and never need to know which physical window an event
actually arrived on. No cross-window pointer grab is used or needed
for this: whichever window is physically under the cursor naturally
receives its own motion/button events - guaranteed compositor
behavior (how every multi-window desktop works), not a Wayland-
specific mechanic to work around. Keyboard is different: grab_keyboard
targets one specific window's Gdk.Window, and the seat redirects *all*
key events there regardless of which monitor the pointer is over -
call it on exactly one of the windows, not all of them.

NOT independently live-verified for real cross-monitor handoff: the
only Wayland test hardware available (see
[[reference-virtualbox-vm-testing]]) has a single monitor. Built on
the compositor fundamentals above rather than anything Wayland-
specific/uncertain, but flagging this honestly per this project's
verification discipline - see REQUIREMENTS.md's Wayland overlay-
positioning section.
"""

from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

from orcshot.core.geometry import Rect


def _call_with_traceback(fn, *args):
    # PyGObject signal callbacks can swallow exceptions silently
    # depending on context (confirmed live: a click that should have
    # opened the destination picker instead just closed the overlay
    # with no visible error) - print a full traceback rather than lose
    # it, since these handlers drive real user-facing state changes.
    try:
        return fn(*args)
    except Exception:
        import sys
        import traceback

        print(f"[monitor_window] exception in {fn}:", file=sys.stderr, flush=True)
        traceback.print_exc()
        return None


class MonitorWindow(Gtk.Window):
    def __init__(
        self,
        monitor_bounds: Rect,
        monitor_index: int,
        on_draw: Callable[["MonitorWindow", object], None],
        on_motion: Optional[Callable[[int, int], None]] = None,
        on_button_press: Optional[Callable[[int, int], None]] = None,
        on_button_release: Optional[Callable[[int, int], None]] = None,
        on_key_press: Optional[Callable[[object], bool]] = None,
    ):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.monitor_bounds = monitor_bounds
        self._monitor_index = monitor_index
        self._on_draw = on_draw
        self._on_motion = on_motion
        self._on_button_press = on_button_press
        self._on_button_release = on_button_release
        self._on_key_press = on_key_press

        self.set_app_paintable(True)
        self.set_decorated(False)
        # Deliberately no RGBA-visual request here (task #84 follow-up)
        # - a previous version of this class requested one specifically
        # for the eyedropper's originally-attempted real per-pixel
        # transparency (without it, that overlay rendered solid black
        # instead of see-through). Since abandoned: eyedropper_wayland.py's
        # own module docstring documents that genuine transparency never
        # survives fullscreen_on_monitor() under this GNOME/Mutter
        # session at all - Mutter's own deliberate policy of forcing
        # fullscreen surfaces opaque for scanout-performance reasons,
        # not something fixable from client code - which is exactly why
        # every Wayland overlay (this one included) paints its own full
        # opaque backdrop bitmap instead of relying on transparency.
        # Requesting an RGBA visual anyway was pure unnecessary cost from
        # that point on: an alpha-channel visual typically forces a
        # compositor onto its slower alpha-blending-aware compositing
        # path even when every pixel painted is fully opaque, which
        # nothing here has needed since the frozen-backdrop redesign -
        # a real, if unconfirmed-by-measurement, candidate contributor
        # to task #84's directional tearing on fast drags (worse under
        # a software-rendered compositor specifically), and pure waste
        # for region-select/window-picker regardless, which never
        # requested this in the first place before it was added here.
        # No set_keep_above(True) here, unlike the X11 overlays this
        # mirrors: those are POPUP windows that need the hint to stay
        # on top at all. These are already inherently topmost via
        # fullscreen_on_monitor() - and keep_above risks hiding a
        # legitimate system dialog *behind* this window if one ever
        # needs to appear (e.g. a portal permission prompt triggered
        # mid-interaction), which a plain fullscreen window wouldn't do.
        self.set_can_focus(True)
        self.resize(monitor_bounds.width, monitor_bounds.height)

        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
        )
        self.connect("draw", self._handle_draw)
        self.connect("motion-notify-event", self._handle_motion)
        self.connect("button-press-event", self._handle_button_press)
        self.connect("button-release-event", self._handle_button_release)
        self.connect("key-press-event", self._handle_key_press)

    def to_global(self, x: float, y: float) -> tuple[int, int]:
        return int(x) + self.monitor_bounds.left, int(y) + self.monitor_bounds.top

    def to_local(self, global_x: int, global_y: int) -> tuple[int, int]:
        return global_x - self.monitor_bounds.left, global_y - self.monitor_bounds.top

    def show_fullscreen(self) -> None:
        self.show_all()
        screen = Gdk.Screen.get_default()
        self.fullscreen_on_monitor(screen, self._monitor_index)
        # region-select/window-picker are triggered from a global
        # hotkey or tray-menu click, and mapping alone was enough to
        # get real focus there (confirmed live). The eyedropper is
        # triggered from inside an already-focused, already-modal-ish
        # Gtk.Dialog - confirmed live that mapping alone was NOT
        # enough there: neither pointer nor keyboard events reached
        # this window at all, Escape fell straight through to the
        # dialog's own default close behavior. present() explicitly
        # requests focus/activation instead of relying on Mutter's
        # focus-stealing-prevention heuristics to grant it implicitly.
        # Harmless for the already-working callers, which are already
        # focused by the time this would run.
        self.present()

    def grab_keyboard(self) -> None:
        # Targets this specific window's Gdk.Window; the seat then
        # redirects *all* key events here regardless of which monitor
        # the pointer is physically over - call on one MonitorWindow
        # only, not once per monitor.
        Gdk.Display.get_default().get_default_seat().grab(
            self.get_window(), Gdk.SeatCapabilities.KEYBOARD, True, None, None, None, None,
        )

    def _handle_draw(self, widget, ctx):
        self._on_draw(self, ctx)
        return False

    def _handle_motion(self, widget, event):
        if self._on_motion is not None:
            gx, gy = self.to_global(event.x, event.y)
            self._on_motion(gx, gy)
        return True

    def _handle_button_press(self, widget, event):
        if self._on_button_press is not None:
            gx, gy = self.to_global(event.x, event.y)
            _call_with_traceback(self._on_button_press, gx, gy)
        return True

    def _handle_button_release(self, widget, event):
        if self._on_button_release is not None:
            gx, gy = self.to_global(event.x, event.y)
            _call_with_traceback(self._on_button_release, gx, gy)
        return True

    def _handle_key_press(self, widget, event):
        if self._on_key_press is not None:
            return _call_with_traceback(self._on_key_press, event)
        return False


def release_keyboard_grab() -> None:
    Gdk.Display.get_default().get_default_seat().ungrab()


def create_monitor_windows(
    monitors,
    on_draw: Callable[["MonitorWindow", object], None],
    on_motion: Optional[Callable[[int, int], None]] = None,
    on_button_press: Optional[Callable[[int, int], None]] = None,
    on_button_release: Optional[Callable[[int, int], None]] = None,
    on_key_press: Optional[Callable[[object], bool]] = None,
) -> list[MonitorWindow]:
    """One MonitorWindow per monitor, sharing the same callbacks - all
    of them call the same handlers with already-translated global
    coordinates, so a single set of drag/hover state updates every
    window's next redraw identically regardless of which one the event
    actually arrived on.
    """
    return [
        MonitorWindow(
            monitor.bounds, index, on_draw,
            on_motion=on_motion, on_button_press=on_button_press,
            on_button_release=on_button_release, on_key_press=on_key_press,
        )
        for index, monitor in enumerate(monitors)
    ]


def queue_draw_all(windows: list[MonitorWindow]) -> None:
    for window in windows:
        window.queue_draw()


def destroy_all(windows: list[MonitorWindow]) -> None:
    for window in windows:
        window.destroy()
