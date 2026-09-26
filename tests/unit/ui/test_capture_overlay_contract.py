"""The capture overlays' shared contracts, plus each one's own
specifics: region-select, window-picker and eyedropper, X11 and Wayland
and GNOME-Shell-native.

Eight files - region_select.py, region_select_wayland.py,
region_select_gnome_shell.py, window_picker.py, window_picker_wayland.py,
window_picker_gnome_shell.py, eyedropper.py, eyedropper_wayland.py -
that between them were at or near 0% coverage: every one of them says
in its own module docstring that it is "not unit tested" because it is
GTK glue, and every one was verified only by running it. They are not
eight separate problems, though. Two contracts run through them:

**The overlay contract** (TestOverlayContract), over the five non-X11
variant classes - WaylandRegionSelect, GnomeShellRegionSelect,
WaylandWindowPicker, GnomeShellWindowPicker, _WaylandEyedropperOverlay.
Each takes its callbacks in __init__ and has a show(); constructing one
delivers nothing and presents nothing, show() reaches that variant's own
presentation call exactly once, a completed interaction delivers its own
payload (a Rect, a window, or a colour) exactly once, and a cancelled
one delivers nothing and reports the cancel instead.

**The drag contract** (TestWaylandDragContract), over the Wayland
overlays that share ``_on_motion``/``_on_button_press``/
``_on_button_release`` in global coordinates.

Two things the plan for this file assumed that reading the sources
disproved, so they are tested as their own classes instead of bent into
a contract:

* ``WaylandWindowPicker`` has **no** ``_on_button_release`` at all - it
  commits on button *press*, because the destination picker's popup grab
  has to be requested inside the triggering event (see its module
  docstring). So the drag contract covers two classes, not three, and
  the window picker gets TestWaylandWindowPicker.
* the two eyedroppers and the two region-selects disagree about what a
  press-and-release with no drag means: a zero-area region is a cancel,
  a zero-area colour pick is a perfectly good pick. Pinned per class.

Nothing here makes a real D-Bus call, a real portal request, a real
subprocess call or a real capture: FakeCaptureBackend supplies the
pixels (its coordinate-pattern content makes every pixel's own absolute
position readable back out of a delivered image), and the two
Shell-native variants get their ``start_*`` D-Bus entry point and
``dispatch_destination`` replaced.
"""

import os
from dataclasses import dataclass
from typing import Callable

import cairo
import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"),
    reason="the overlays are real Gtk widgets - constructing one needs a display (CI: xvfb-run)",
)

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

from orcshot.capture import gnome_eyedropper, gnome_region_select, gnome_window_picker
from orcshot.capture.backend import Monitor
from orcshot.capture.cursor import CursorSnapshot
from orcshot.capture.fake import (
    FakeCaptureBackend,
    FakeCursorBackend,
    FakeWindowActivator,
    FakeWindowEnumerator,
)
from orcshot.capture.window import WindowInfo
from orcshot.core.geometry import Rect
from orcshot.core.magnifier import magnifier_diameter, magnifier_offset
from orcshot.ui import destination_picker, eyedropper, eyedropper_wayland, region_select
from orcshot.ui import region_select_gnome_shell, region_select_wayland as region_select_wayland_module
from orcshot.ui import window_picker, window_picker_gnome_shell
from orcshot.ui.eyedropper import _EyedropperOverlay, start_eyedropper
from orcshot.ui.eyedropper_wayland import _WaylandEyedropperOverlay
from orcshot.ui.monitor_window import MonitorWindow, destroy_all
from orcshot.ui.region_select import RegionSelectWindow, start_region_capture
from orcshot.ui.region_select_gnome_shell import GnomeShellRegionSelect
from orcshot.ui.region_select_wayland import WaylandRegionSelect
from orcshot.ui.window_picker import WindowPickerWindow, start_window_picker
from orcshot.ui.window_picker_gnome_shell import GnomeShellWindowPicker
from orcshot.ui.window_picker_wayland import WaylandWindowPicker

# Small monitors on purpose: every overlay slices and converts its whole
# frozen backdrop per monitor at construction time, and nothing here
# depends on a realistic resolution - only on realistic *content*, which
# FakeCaptureBackend's coordinate pattern gives at any size.
_ONE_MONITOR = (Monitor("FAKE-1", Rect(0, 0, 320, 200), is_primary=True),)
_TWO_MONITORS = (
    Monitor("FAKE-1", Rect(0, 0, 320, 200), is_primary=True),
    Monitor("FAKE-2", Rect(320, 0, 640, 200)),
)
# A layout whose origin is not (0, 0): the only way a test can tell a
# local coordinate from an absolute one apart at all.
_OFFSET_MONITOR = (Monitor("FAKE-1", Rect(-100, -50, 220, 150), is_primary=True),)


def _backend(monitors=_ONE_MONITOR) -> FakeCaptureBackend:
    return FakeCaptureBackend(monitors)


def _screen_color(backend: FakeCaptureBackend, x: int, y: int):
    """The colour the backend really has at absolute (x, y), read back
    through its own grab() rather than by re-deriving its coordinate
    pattern here - so an expectation can't agree with a wrong
    implementation just because the test copied the same formula.
    """
    return tuple(backend.grab(Rect(x, y, x + 1, y + 1))[0, 0])


def _cursor_backend(x: int = 40, y: int = 30) -> FakeCursorBackend:
    """A cursor snapshot with a real silhouette in it - varying colour
    and a partly transparent edge, not a uniform block, since the
    overlays hand this straight to the compositing path.
    """
    image = np.empty((8, 8, 4), dtype=np.uint8)
    columns = np.arange(8, dtype=np.uint8) * 30
    image[:, :, 0] = columns[None, :]
    image[:, :, 1] = columns[:, None]
    image[:, :, 2] = 90
    image[:, :, 3] = 255
    image[0, :, 3] = 0  # a transparent top row, as a real arrow cursor has
    return FakeCursorBackend(CursorSnapshot(image=image, x=x, y=y, hotspot_x=1, hotspot_y=1))


def _window(window_id: int = 7, title: str = "Terminal", bounds: Rect = None, minimized: bool = False) -> WindowInfo:
    return WindowInfo(
        window_id=window_id, title=title, class_name="org.example.App",
        bounds=bounds if bounds is not None else Rect(40, 30, 200, 150),
        is_minimized=minimized, window_type="normal", process_id=4242,
    )


@dataclass
class _Event:
    """The only three fields these handlers read off a Gdk event.
    Synthesising a real Gdk.EventButton/EventKey adds nothing: the
    handlers never touch anything else on it.
    """

    x: float = 0.0
    y: float = 0.0
    keyval: int = 0


@dataclass
class _Call:
    args: tuple
    kwargs: dict


class _Recorder:
    def __init__(self):
        self.calls: list[_Call] = []

    def __call__(self, *args, **kwargs):
        self.calls.append(_Call(args, kwargs))

    @property
    def count(self) -> int:
        return len(self.calls)


@pytest.fixture
def presented(monkeypatch):
    """Records every per-monitor presentation instead of really
    fullscreening. MonitorWindow.show_fullscreen() calls
    fullscreen_on_monitor(screen, index), which is meaningless for a
    fake layout's second monitor under a single-screen Xvfb - but
    show() still needs a realised Gdk window (WaylandRegionSelect's
    show() sets a cursor on it), so the spy maps the window first.
    """
    shown = []

    def spy(window):
        window.show_all()
        shown.append(window)

    monkeypatch.setattr(MonitorWindow, "show_fullscreen", spy)
    return shown


@dataclass
class _Destinations:
    dispatched: _Recorder
    shown: _Recorder
    menus: list


@pytest.fixture
def no_real_destination(monkeypatch):
    """Both halves of the destination layer replaced: the Shell-native
    overlays call dispatch_destination (which would really save/copy an
    image), and the X11/Wayland ones pop a real Gtk.Menu. The menus the
    stand-in hands back are kept, because the Wayland overlays connect
    to their "deactivate" to know when to drop the anchor window.
    """
    dispatched = _Recorder()
    monkeypatch.setattr(destination_picker, "dispatch_destination", dispatched)

    shown = _Recorder()
    menus = []

    def fake_picker(*args, **kwargs):
        shown(*args, **kwargs)
        menus.append(Gtk.Menu())
        return menus[-1]

    monkeypatch.setattr(destination_picker, "show_destination_picker", fake_picker)
    return _Destinations(dispatched, shown, menus)


@pytest.fixture
def seat_ungrab():
    """The X11 start_* entry points take a real keyboard grab on the
    seat, exactly as they do in the app. Released afterwards so it
    can't leak into another test.
    """
    yield
    Gdk.Display.get_default().get_default_seat().ungrab()


def _drawn(paint, width: int = 320, height: int = 200) -> cairo.ImageSurface:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    paint(cairo.Context(surface))
    surface.flush()
    return surface


def _pixel(surface: cairo.ImageSurface, x: int, y: int) -> tuple:
    offset = y * surface.get_stride() + x * 4
    return tuple(bytes(surface.get_data())[offset:offset + 4])


def _brightness(surface: cairo.ImageSurface, x: int, y: int) -> int:
    return sum(_pixel(surface, x, y)[:3])


# --------------------------------------------------------------------
# The overlay contract: __init__ + show(), over all five variants.
# --------------------------------------------------------------------


@dataclass
class _Variant:
    overlay: object
    delivered: _Recorder
    cancelled: _Recorder
    presentations: list
    expected_presentations: int
    complete: Callable[[], object]
    cancel: Callable[[], None]
    payload: Callable[[_Call], object]
    teardown: Callable[[], None]


def _region_select_wayland(monkeypatch, presented) -> _Variant:
    backend = _backend(_ONE_MONITOR)
    delivered, cancelled = _Recorder(), _Recorder()
    overlay = WaylandRegionSelect(backend, delivered, cancelled, capture_mouse_cursor=False)

    def complete():
        overlay._on_button_press(20, 30)
        overlay._on_motion(140, 90)
        overlay._on_button_release(140, 90)
        return Rect(20, 30, 140, 90)

    return _Variant(
        overlay=overlay, delivered=delivered, cancelled=cancelled,
        presentations=presented, expected_presentations=1,
        complete=complete,
        cancel=lambda: overlay._on_key_press(_Event(keyval=Gdk.KEY_Escape)),
        payload=lambda call: call.args[1],
        teardown=lambda: destroy_all(overlay._windows),
    )


def _window_picker_wayland(monkeypatch, presented) -> _Variant:
    backend = _backend(_ONE_MONITOR)
    delivered, cancelled = _Recorder(), _Recorder()
    picked = _window(bounds=Rect(40, 30, 200, 150))
    overlay = WaylandWindowPicker(
        backend, FakeWindowEnumerator([picked]), delivered, cancelled,
        capture_mouse_cursor=False, window_activator=FakeWindowActivator(),
    )

    def complete():
        overlay._on_motion(100, 100)
        overlay._on_button_press(100, 100)  # commits on press, not release
        return picked.bounds

    return _Variant(
        overlay=overlay, delivered=delivered, cancelled=cancelled,
        presentations=presented, expected_presentations=1,
        complete=complete,
        cancel=lambda: overlay._on_key_press(_Event(keyval=Gdk.KEY_Escape)),
        payload=lambda call: call.args[1].bounds,
        teardown=lambda: destroy_all(overlay._monitor_windows),
    )


def _eyedropper_wayland(monkeypatch, presented) -> _Variant:
    backend = _backend(_ONE_MONITOR)
    delivered, cancelled = _Recorder(), _Recorder()
    overlay = _WaylandEyedropperOverlay(backend, delivered, cancelled)

    def complete():
        # show() defers the backdrop grab onto the main loop; no test
        # runs one, so the deferred callback is invoked directly.
        overlay._load_backdrop()
        overlay._on_button_press(55, 65)
        overlay._on_motion(110, 130)
        overlay._on_button_release(110, 130)
        return _screen_color(backend, 110, 130)

    def teardown():
        overlay._alive = False  # so any still-pending idle backdrop load is a no-op
        destroy_all(overlay._monitor_windows)

    return _Variant(
        overlay=overlay, delivered=delivered, cancelled=cancelled,
        presentations=presented, expected_presentations=1,
        complete=complete,
        cancel=lambda: overlay._on_key_press(_Event(keyval=Gdk.KEY_Escape)),
        payload=lambda call: call.args[0],
        teardown=teardown,
    )


def _region_select_gnome_shell(monkeypatch, presented) -> _Variant:
    backend = _backend(_ONE_MONITOR)
    delivered, cancelled = _Recorder(), _Recorder()
    started = _Recorder()
    # The Shell-side interaction: replaced outright, so no D-Bus call
    # and no real Shell extension are involved.
    monkeypatch.setattr(region_select_gnome_shell, "start_region_select", started)
    dispatched = _Recorder()
    monkeypatch.setattr(destination_picker, "dispatch_destination", dispatched)

    overlay = GnomeShellRegionSelect(on_captured=delivered, on_cancelled=cancelled, capture_mouse_cursor=False)
    region = Rect(20, 30, 140, 90)

    def complete():
        on_selected = started.calls[0].args[0]
        on_selected(backend.grab(region), region, "clipboard")
        return region

    def cancel():
        on_cancelled = started.calls[0].args[1]
        on_cancelled()

    return _Variant(
        overlay=overlay, delivered=delivered, cancelled=cancelled,
        presentations=started.calls, expected_presentations=1,
        complete=complete, cancel=cancel,
        payload=lambda call: call.args[0],
        teardown=lambda: None,
    )


def _window_picker_gnome_shell(monkeypatch, presented) -> _Variant:
    backend = _backend(_ONE_MONITOR)
    delivered, cancelled = _Recorder(), _Recorder()
    started = _Recorder()
    monkeypatch.setattr(window_picker_gnome_shell, "start_window_picker", started)
    dispatched = _Recorder()
    monkeypatch.setattr(destination_picker, "dispatch_destination", dispatched)

    overlay = GnomeShellWindowPicker(on_captured=delivered, on_cancelled=cancelled, capture_mouse_cursor=False)
    region = Rect(40, 30, 200, 150)

    def complete():
        on_selected = started.calls[0].args[0]
        on_selected(backend.grab(region), region, "clipboard", "Terminal")
        return region

    def cancel():
        on_cancelled = started.calls[0].args[1]
        on_cancelled()

    return _Variant(
        overlay=overlay, delivered=delivered, cancelled=cancelled,
        presentations=started.calls, expected_presentations=1,
        complete=complete, cancel=cancel,
        payload=lambda call: call.args[0],
        teardown=lambda: None,
    )


_VARIANTS = {
    "region_select_wayland": _region_select_wayland,
    "region_select_gnome_shell": _region_select_gnome_shell,
    "window_picker_wayland": _window_picker_wayland,
    "window_picker_gnome_shell": _window_picker_gnome_shell,
    "eyedropper_wayland": _eyedropper_wayland,
}


@pytest.fixture(params=sorted(_VARIANTS))
def variant(request, monkeypatch, presented):
    built = _VARIANTS[request.param](monkeypatch, presented)
    yield built
    built.teardown()


class TestOverlayContract:
    """One contract over all five variant classes - see this module's
    docstring.
    """

    def test_constructing_one_presents_nothing_and_delivers_nothing(self, variant):
        assert variant.presentations == []
        assert variant.delivered.count == 0
        assert variant.cancelled.count == 0

    def test_show_reaches_its_own_presentation_exactly_once(self, variant):
        variant.overlay.show()

        assert len(variant.presentations) == variant.expected_presentations

    def test_a_completed_interaction_delivers_its_payload_exactly_once(self, variant):
        variant.overlay.show()

        expected = variant.complete()

        assert variant.delivered.count == 1
        assert variant.payload(variant.delivered.calls[0]) == expected
        assert variant.cancelled.count == 0

    def test_a_cancelled_interaction_delivers_nothing_and_reports_the_cancel(self, variant):
        variant.overlay.show()

        variant.cancel()

        assert variant.delivered.count == 0
        assert variant.cancelled.count == 1


# --------------------------------------------------------------------
# The drag contract: press/motion/release in global coordinates.
# --------------------------------------------------------------------


@dataclass
class _DragVariant:
    overlay: object
    delivered: _Recorder
    cancelled: _Recorder
    payload_for: Callable[[tuple, tuple], object]
    payload: Callable[[_Call], object]
    teardown: Callable[[], None]


def _drag_region_select(presented) -> _DragVariant:
    backend = _backend(_ONE_MONITOR)
    delivered, cancelled = _Recorder(), _Recorder()
    overlay = WaylandRegionSelect(backend, delivered, cancelled, capture_mouse_cursor=False)
    return _DragVariant(
        overlay=overlay, delivered=delivered, cancelled=cancelled,
        payload_for=lambda start, end: Rect.from_points(*start, *end),
        payload=lambda call: call.args[1],
        teardown=lambda: destroy_all(overlay._windows),
    )


def _drag_eyedropper(presented) -> _DragVariant:
    backend = _backend(_ONE_MONITOR)
    delivered, cancelled = _Recorder(), _Recorder()
    overlay = _WaylandEyedropperOverlay(backend, delivered, cancelled)
    overlay._load_backdrop()

    def teardown():
        overlay._alive = False
        destroy_all(overlay._monitor_windows)

    return _DragVariant(
        overlay=overlay, delivered=delivered, cancelled=cancelled,
        payload_for=lambda start, end: _screen_color(backend, *end),
        payload=lambda call: call.args[0],
        teardown=teardown,
    )


_DRAG_VARIANTS = {
    "region_select_wayland": _drag_region_select,
    "eyedropper_wayland": _drag_eyedropper,
}


@pytest.fixture(params=sorted(_DRAG_VARIANTS))
def drag_variant(request, presented):
    built = _DRAG_VARIANTS[request.param](presented)
    yield built
    built.teardown()


class TestWaylandDragContract:
    """The two Wayland overlays driven by a press-drag-release gesture,
    both taking global (virtual-screen) coordinates. WaylandWindowPicker
    is deliberately absent: it has no _on_button_release at all, see this
    module's docstring.
    """

    def test_motion_with_no_button_held_delivers_nothing(self, drag_variant):
        drag_variant.overlay._on_motion(90, 70)

        assert drag_variant.delivered.count == 0
        assert drag_variant.cancelled.count == 0

    def test_the_gesture_endpoint_decides_the_payload(self, drag_variant):
        drag_variant.overlay._on_button_press(30, 40)
        drag_variant.overlay._on_motion(150, 120)
        drag_variant.overlay._on_button_release(150, 120)

        assert drag_variant.delivered.count == 1
        payload = drag_variant.payload(drag_variant.delivered.calls[0])
        assert payload == drag_variant.payload_for((30, 40), (150, 120))
        # and is genuinely a function of where the gesture ended, not
        # of anything constant.
        assert payload != drag_variant.payload_for((30, 40), (200, 60))

    def test_escape_cancels_without_delivering(self, drag_variant):
        drag_variant.overlay._on_button_press(30, 40)

        handled = drag_variant.overlay._on_key_press(_Event(keyval=Gdk.KEY_Escape))

        assert handled is True
        assert drag_variant.delivered.count == 0
        assert drag_variant.cancelled.count == 1

    def test_an_unrelated_key_is_left_for_someone_else(self, drag_variant):
        assert drag_variant.overlay._on_key_press(_Event(keyval=Gdk.KEY_F5)) is False


# --------------------------------------------------------------------
# The cursor-sampling contract, over all six capture overlays (both
# eyedroppers are absent on purpose: they never capture the cursor).
# --------------------------------------------------------------------


_CURSOR_SAMPLERS = {
    "RegionSelectWindow": lambda backend, kw: RegionSelectWindow(backend, _Recorder(), **kw),
    "WaylandRegionSelect": lambda backend, kw: WaylandRegionSelect(backend, _Recorder(), **kw),
    "GnomeShellRegionSelect": lambda backend, kw: GnomeShellRegionSelect(**kw),
    "WindowPickerWindow": lambda backend, kw: WindowPickerWindow(
        backend, FakeWindowEnumerator([_window()]), _Recorder(), **kw,
    ),
    "WaylandWindowPicker": lambda backend, kw: WaylandWindowPicker(
        backend, FakeWindowEnumerator([_window()]), _Recorder(), **kw,
    ),
    "GnomeShellWindowPicker": lambda backend, kw: GnomeShellWindowPicker(**kw),
}


def _dispose(overlay) -> None:
    # Gtk.Window first: WindowPickerWindow's own ``_windows`` is its list
    # of WindowInfo, not of windows to destroy.
    if isinstance(overlay, Gtk.Window):
        overlay.destroy()
        return
    for attribute in ("_windows", "_monitor_windows"):
        if hasattr(overlay, attribute):
            destroy_all(getattr(overlay, attribute))
            return


@pytest.fixture(params=sorted(_CURSOR_SAMPLERS))
def cursor_sampler(request):
    built = []

    def build(**cursor_kwargs):
        overlay = _CURSOR_SAMPLERS[request.param](_backend(), cursor_kwargs)
        built.append(overlay)
        return overlay

    yield build
    for overlay in built:
        _dispose(overlay)


class TestCursorSamplingContract:
    """Every capture overlay samples the mouse cursor once, at
    construction - matching CaptureHelper.cs, which samples before the
    interactive form is even shown, not wherever the gesture ends. All
    six say so in their own __init__ comments; this is that comment,
    asserted.
    """

    def test_the_cursor_is_sampled_at_construction_time(self, cursor_sampler):
        cursors = _cursor_backend()

        overlay = cursor_sampler(capture_mouse_cursor=True, cursor_backend=cursors)

        assert overlay._cursor_snapshot is cursors.cursor_snapshot()

    def test_the_default_cursor_backend_is_used_when_none_is_handed_in(self, cursor_sampler, monkeypatch):
        # The default is resolved lazily, inside __init__, so importing
        # these modules never needs a cursor source at all.
        from orcshot.capture import cursor as cursor_module

        cursors = _cursor_backend()
        monkeypatch.setattr(cursor_module, "default_cursor_backend", lambda: cursors)

        overlay = cursor_sampler(capture_mouse_cursor=True)

        assert overlay._cursor_snapshot is cursors.cursor_snapshot()

    def test_a_platform_with_no_cursor_backend_at_all_samples_nothing(self, cursor_sampler, monkeypatch):
        from orcshot.capture import cursor as cursor_module

        monkeypatch.setattr(cursor_module, "default_cursor_backend", lambda: None)

        overlay = cursor_sampler(capture_mouse_cursor=True)

        assert overlay._cursor_snapshot is None

    def test_the_per_call_override_wins_over_the_preference(self, cursor_sampler):
        # capture_mouse_cursor=False is app.py's tray-menu path: never
        # show the cursor regardless of the Preferences setting, because
        # by then the pointer is over the menu, not the content.
        overlay = cursor_sampler(capture_mouse_cursor=False, cursor_backend=_cursor_backend())

        assert overlay._cursor_snapshot is None

    def test_the_preference_being_off_beats_the_per_call_default(self, cursor_sampler, monkeypatch):
        from orcshot.ui import capture_modes

        monkeypatch.setattr(capture_modes, "get_capture_mouse_cursor", lambda: False)

        overlay = cursor_sampler(capture_mouse_cursor=True, cursor_backend=_cursor_backend())

        assert overlay._cursor_snapshot is None


# --------------------------------------------------------------------
# Per-class specifics.
# --------------------------------------------------------------------


class TestWaylandRegionSelect:
    def test_a_click_with_no_drag_is_a_cancel_not_a_zero_area_capture(self, presented):
        delivered, cancelled = _Recorder(), _Recorder()
        overlay = WaylandRegionSelect(_backend(), delivered, cancelled, capture_mouse_cursor=False)

        overlay._on_button_press(60, 60)
        overlay._on_button_release(60, 60)

        assert delivered.count == 0
        assert cancelled.count == 1

    def test_a_release_with_no_press_is_ignored(self, presented):
        delivered, cancelled = _Recorder(), _Recorder()
        overlay = WaylandRegionSelect(_backend(), delivered, cancelled, capture_mouse_cursor=False)

        overlay._on_button_release(60, 60)

        assert delivered.count == 0
        assert cancelled.count == 0
        destroy_all(overlay._windows)

    def test_a_selection_dragged_off_screen_is_clamped_to_the_virtual_bounds(self, presented):
        delivered = _Recorder()
        overlay = WaylandRegionSelect(_backend(_ONE_MONITOR), delivered, capture_mouse_cursor=False)

        overlay._on_button_press(200, 100)
        overlay._on_button_release(9000, 9000)

        assert delivered.calls[0].args[1] == Rect(200, 100, 320, 200)

    def test_the_delivered_pixels_are_the_selected_region_of_the_screen(self, presented):
        backend = _backend(_ONE_MONITOR)
        delivered = _Recorder()
        overlay = WaylandRegionSelect(backend, delivered, capture_mouse_cursor=False)

        overlay._on_button_press(40, 25)
        overlay._on_button_release(140, 105)

        # FakeCaptureBackend's content encodes each pixel's own absolute
        # position, so this compares *where* the pixels came from, not
        # just the shape.
        assert np.array_equal(delivered.calls[0].args[0], backend.grab(Rect(40, 25, 140, 105)))

    def test_the_window_under_the_release_anchors_the_picker_and_the_others_are_destroyed(self, presented):
        delivered = _Recorder()
        overlay = WaylandRegionSelect(_backend(_TWO_MONITORS), delivered, capture_mouse_cursor=False)
        first, second = overlay._windows

        overlay._on_button_press(60, 60)
        overlay._on_button_release(400, 120)  # on the second monitor

        call = delivered.calls[0]
        assert call.kwargs["anchor_monitor_window"] is second
        # local to that monitor, not global - Wayland popups are placed
        # relative to their parent surface.
        assert call.kwargs["anchor_local_pos"] == (80, 120)
        assert first.get_visible() is False
        second.destroy()

    def test_the_m_key_drops_the_captured_cursor_from_the_next_capture(self, presented, monkeypatch):
        monkeypatch.setattr(region_select_wayland_module, "get_show_magnifier_while_selecting", lambda: False)
        delivered = _Recorder()
        overlay = WaylandRegionSelect(
            _backend(), delivered, capture_mouse_cursor=True, cursor_backend=_cursor_backend(x=60, y=60),
        )
        assert overlay._cursor_visible is True

        assert overlay._on_key_press(_Event(keyval=Gdk.KEY_m)) is True
        overlay._on_button_press(20, 20)
        overlay._on_button_release(160, 140)

        assert overlay._cursor_visible is False
        assert delivered.calls[0].args[2] is None  # no cursor shape handed on

    def test_the_captured_cursor_is_delivered_with_the_region_when_visible(self, presented):
        delivered = _Recorder()
        overlay = WaylandRegionSelect(
            _backend(), delivered, capture_mouse_cursor=True, cursor_backend=_cursor_backend(x=60, y=60),
        )

        overlay._on_button_press(20, 20)
        overlay._on_button_release(160, 140)

        cursor_shape = delivered.calls[0].args[2]
        assert cursor_shape is not None
        # placed relative to the captured region's own origin
        assert cursor_shape.bounds == Rect(60 - 1 - 20, 60 - 1 - 20, 60 - 1 - 20 + 8, 60 - 1 - 20 + 8)

    def test_the_selection_is_an_undimmed_hole_in_the_dim_overlay(self, presented, monkeypatch):
        monkeypatch.setattr(region_select_wayland_module, "get_show_magnifier_while_selecting", lambda: False)
        backend = _backend(_ONE_MONITOR)
        dimmed = WaylandRegionSelect(backend, _Recorder(), capture_mouse_cursor=False)
        selecting = WaylandRegionSelect(backend, _Recorder(), capture_mouse_cursor=False)
        selecting._on_button_press(40, 40)
        selecting._on_motion(160, 120)

        without = _drawn(lambda ctx: dimmed._on_draw(dimmed._windows[0], ctx))
        with_selection = _drawn(lambda ctx: selecting._on_draw(selecting._windows[0], ctx))

        assert _brightness(with_selection, 60, 60) > _brightness(without, 60, 60)
        destroy_all(dimmed._windows)
        destroy_all(selecting._windows)

    def test_the_magnifier_setting_reaches_what_is_actually_drawn(self, presented, monkeypatch):
        backend = _backend(_ONE_MONITOR)
        monkeypatch.setattr(region_select_wayland_module, "get_show_magnifier_while_selecting", lambda: False)
        without = WaylandRegionSelect(backend, _Recorder(), capture_mouse_cursor=False)
        monkeypatch.setattr(region_select_wayland_module, "get_show_magnifier_while_selecting", lambda: True)
        with_loupe = WaylandRegionSelect(backend, _Recorder(), capture_mouse_cursor=False)
        for overlay in (without, with_loupe):
            overlay._on_motion(160, 100)

        plain = _drawn(lambda ctx: without._on_draw(without._windows[0], ctx))
        loupe = _drawn(lambda ctx: with_loupe._on_draw(with_loupe._windows[0], ctx))

        assert bytes(plain.get_data()) != bytes(loupe.get_data())
        destroy_all(without._windows)
        destroy_all(with_loupe._windows)


class TestWaylandWindowPicker:
    def test_hovering_highlights_the_window_under_the_cursor(self, presented):
        picked = _window(bounds=Rect(40, 30, 200, 150))
        overlay = WaylandWindowPicker(
            _backend(), FakeWindowEnumerator([picked]), _Recorder(), capture_mouse_cursor=False,
        )

        overlay._on_motion(100, 100)

        assert overlay._hovered is picked
        destroy_all(overlay._monitor_windows)

    def test_overlapping_windows_resolve_to_the_topmost_one(self, presented):
        # list_windows() is bottom-to-top (window_picker.py's own
        # stacking contract), so the last match wins.
        below = _window(window_id=1, title="Below", bounds=Rect(0, 0, 200, 200))
        above = _window(window_id=2, title="Above", bounds=Rect(50, 50, 150, 150))
        overlay = WaylandWindowPicker(
            _backend(), FakeWindowEnumerator([below, above]), _Recorder(), capture_mouse_cursor=False,
        )

        overlay._on_motion(100, 100)

        assert overlay._hovered is above
        destroy_all(overlay._monitor_windows)

    def test_a_minimized_window_is_not_pickable(self, presented):
        overlay = WaylandWindowPicker(
            _backend(), FakeWindowEnumerator([_window(minimized=True)]), _Recorder(), capture_mouse_cursor=False,
        )

        overlay._on_motion(100, 100)

        assert overlay._hovered is None
        destroy_all(overlay._monitor_windows)

    def test_clicking_where_no_window_is_cancels(self, presented):
        delivered, cancelled = _Recorder(), _Recorder()
        overlay = WaylandWindowPicker(
            _backend(), FakeWindowEnumerator([_window()]), delivered, cancelled, capture_mouse_cursor=False,
        )

        overlay._on_motion(5, 5)
        overlay._on_button_press(5, 5)

        assert delivered.count == 0
        assert cancelled.count == 1

    def test_the_click_delivers_the_frozen_backdrop_as_a_placeholder(self, presented):
        backend = _backend(_ONE_MONITOR)
        picked = _window(bounds=Rect(40, 30, 200, 150))
        delivered = _Recorder()
        overlay = WaylandWindowPicker(
            backend, FakeWindowEnumerator([picked]), delivered, capture_mouse_cursor=False,
        )

        overlay._on_motion(100, 100)
        overlay._on_button_press(100, 100)

        assert np.array_equal(delivered.calls[0].args[0], backend.grab(picked.bounds))

    def test_refresh_image_raises_the_window_first_then_grabs_it_fresh(self, presented):
        backend = _backend(_ONE_MONITOR)
        activator = FakeWindowActivator()
        picked = _window(window_id=99, bounds=Rect(40, 30, 200, 150))
        delivered = _Recorder()
        overlay = WaylandWindowPicker(
            backend, FakeWindowEnumerator([picked]), delivered,
            capture_mouse_cursor=False, window_activator=activator,
        )
        overlay._on_motion(100, 100)
        overlay._on_button_press(100, 100)
        grabs_before = len(backend.grabs)

        refreshed = delivered.calls[0].kwargs["refresh_image"]()

        assert activator.activated == [99]
        assert backend.grabs[grabs_before:] == [picked.bounds]
        assert np.array_equal(refreshed, backend.grab(picked.bounds))

    def test_without_an_activator_there_is_nothing_to_refresh(self, presented):
        # No WindowActivator means no way to raise the window, so the
        # picker is handed no refresh callback at all and keeps the
        # frozen placeholder.
        delivered = _Recorder()
        overlay = WaylandWindowPicker(
            _backend(), FakeWindowEnumerator([_window()]), delivered, capture_mouse_cursor=False,
        )

        overlay._on_motion(100, 100)
        overlay._on_button_press(100, 100)

        assert delivered.calls[0].kwargs["refresh_image"] is None

    def test_the_captured_cursor_is_delivered_with_the_window_and_drawn_on_the_overlay(self, presented):
        delivered = _Recorder()
        backend = _backend(_ONE_MONITOR)
        overlay = WaylandWindowPicker(
            backend, FakeWindowEnumerator([_window(bounds=Rect(40, 30, 200, 150))]), delivered,
            capture_mouse_cursor=True, cursor_backend=_cursor_backend(x=100, y=100),
        )
        try:
            with_cursor = _drawn(lambda ctx: overlay._on_draw(overlay._monitor_windows[0], ctx))
            overlay._on_motion(100, 100)
            overlay._on_button_press(100, 100)

            assert delivered.calls[0].args[2] is not None
            # the live cursor preview sits at its one sampled position
            bare = WaylandWindowPicker(
                backend, FakeWindowEnumerator([_window()]), _Recorder(), capture_mouse_cursor=False,
            )
            without = _drawn(lambda ctx: bare._on_draw(bare._monitor_windows[0], ctx))
            assert _pixel(with_cursor, 102, 102) != _pixel(without, 102, 102)
            destroy_all(bare._monitor_windows)
        finally:
            destroy_all(overlay._monitor_windows)

    def test_the_hovered_window_is_an_undimmed_hole_in_the_dim_overlay(self, presented):
        backend = _backend(_ONE_MONITOR)
        idle = WaylandWindowPicker(backend, FakeWindowEnumerator([_window()]), _Recorder(), capture_mouse_cursor=False)
        hovering = WaylandWindowPicker(
            backend, FakeWindowEnumerator([_window()]), _Recorder(), capture_mouse_cursor=False,
        )
        hovering._on_motion(100, 100)

        without = _drawn(lambda ctx: idle._on_draw(idle._monitor_windows[0], ctx))
        with_hover = _drawn(lambda ctx: hovering._on_draw(hovering._monitor_windows[0], ctx))

        assert _brightness(with_hover, 100, 100) > _brightness(without, 100, 100)
        destroy_all(idle._monitor_windows)
        destroy_all(hovering._monitor_windows)


class TestWaylandEyedropper:
    def test_a_press_before_the_backdrop_arrives_samples_nothing(self, presented):
        # show()'s backdrop grab is deferred onto the main loop, so the
        # first events of a fast gesture can arrive before it exists.
        picked, cancelled = _Recorder(), _Recorder()
        overlay = _WaylandEyedropperOverlay(_backend(), picked, cancelled)

        overlay._on_button_press(60, 60)

        assert overlay._current_color is None
        overlay._on_button_release(60, 60)
        assert picked.count == 0
        assert cancelled.count == 1

    def test_a_press_with_no_drag_still_picks_the_colour_under_it(self, presented):
        # Unlike region-select, where a zero-area gesture is a cancel: a
        # click is a perfectly good colour pick.
        backend = _backend(_ONE_MONITOR)
        picked, cancelled = _Recorder(), _Recorder()
        overlay = _WaylandEyedropperOverlay(backend, picked, cancelled)
        overlay._load_backdrop()

        overlay._on_button_press(77, 88)
        overlay._on_button_release(77, 88)

        assert picked.calls[0].args[0] == _screen_color(backend, 77, 88)
        assert cancelled.count == 0

    def test_the_release_coordinates_are_ignored_in_favour_of_the_last_sample(self, presented):
        # Pinned rather than fixed: _on_button_release takes global_x/
        # global_y and never reads them - the colour is whatever the
        # last press/motion sampled. Harmless in practice (a real
        # release lands where the last motion did) but it is the actual
        # behaviour, so a test should say so.
        backend = _backend(_ONE_MONITOR)
        picked = _Recorder()
        overlay = _WaylandEyedropperOverlay(backend, picked)
        overlay._load_backdrop()

        overlay._on_button_press(40, 50)
        overlay._on_motion(120, 130)
        overlay._on_button_release(300, 20)

        assert picked.calls[0].args[0] == _screen_color(backend, 120, 130)

    def test_motion_without_a_press_samples_nothing(self, presented):
        backend = _backend(_ONE_MONITOR)
        overlay = _WaylandEyedropperOverlay(backend, _Recorder())
        overlay._load_backdrop()

        overlay._on_motion(120, 130)

        assert overlay._current_color is None
        destroy_all(overlay._monitor_windows)

    def test_a_backdrop_load_after_the_overlay_is_gone_does_nothing(self, presented):
        # The idle callback is not scoped to the main loop that
        # scheduled it, so it can still fire after a fast pick tore the
        # overlay down - guarded by _alive, see the module docstring.
        overlay = _WaylandEyedropperOverlay(_backend(), _Recorder())
        overlay._on_button_release(10, 10)

        assert overlay._alive is False
        assert overlay._load_backdrop() is False
        assert overlay._frozen_image is None

    def test_the_loupe_is_only_painted_on_the_monitor_holding_the_cursor(self, presented):
        backend = _backend(_TWO_MONITORS)
        overlay = _WaylandEyedropperOverlay(backend, _Recorder())
        overlay._load_backdrop()
        overlay._on_button_press(60, 60)  # on the first monitor

        on_cursor = _drawn(lambda ctx: overlay._on_draw(overlay._monitor_windows[0], ctx))
        elsewhere = _drawn(lambda ctx: overlay._on_draw(overlay._monitor_windows[1], ctx))

        # The second monitor shows its own backdrop slice and nothing
        # else; the first also carries the loupe and its hex swatch.
        assert np.array_equal(
            np.frombuffer(bytes(elsewhere.get_data()), dtype=np.uint8),
            np.frombuffer(bytes(_drawn(lambda ctx: _blit(ctx, backend, Rect(320, 0, 640, 200))).get_data()), np.uint8),
        )
        assert bytes(on_cursor.get_data()) != bytes(elsewhere.get_data())
        overlay._alive = False
        destroy_all(overlay._monitor_windows)

    def test_a_backdrop_grab_that_fails_leaves_the_overlay_usable(self, presented, capsys):
        # The deferred grab is a real portal round trip in the app, and
        # it can fail; the overlay must survive it rather than take the
        # session's whole main loop down with it.
        class FailingBackend:
            def __init__(self, real):
                self._real = real

            def screen_layout(self):
                return self._real.screen_layout()

            def grab(self, rect):
                raise RuntimeError("portal said no")

        overlay = _WaylandEyedropperOverlay(FailingBackend(_backend()), _Recorder())

        assert overlay._load_backdrop() is False
        assert overlay._frozen_image is None
        assert "portal said no" in capsys.readouterr().err
        overlay._alive = False
        destroy_all(overlay._monitor_windows)

    def test_crossing_onto_another_monitor_clears_the_loupe_it_left_behind(self, presented):
        overlay = _WaylandEyedropperOverlay(_backend(_TWO_MONITORS), _Recorder())
        overlay._load_backdrop()
        first, second = overlay._monitor_windows

        overlay._on_button_press(60, 60)  # loupe drawn on the first monitor
        assert overlay._last_draw_rect[first] is not None
        overlay._on_motion(400, 60)  # ... then the cursor crosses over

        assert overlay._last_draw_rect[first] is None
        assert overlay._last_draw_rect[second] is not None
        overlay._alive = False
        destroy_all(overlay._monitor_windows)

    def test_before_any_sample_only_the_backdrop_is_painted(self, presented):
        backend = _backend(_ONE_MONITOR)
        overlay = _WaylandEyedropperOverlay(backend, _Recorder())
        overlay._load_backdrop()
        try:
            drawn = _drawn(lambda ctx: overlay._on_draw(overlay._monitor_windows[0], ctx))

            assert bytes(drawn.get_data()) == bytes(
                _drawn(lambda ctx: _blit(ctx, backend, Rect(0, 0, 320, 200))).get_data()
            )
        finally:
            overlay._alive = False
            destroy_all(overlay._monitor_windows)

    def test_the_sampled_region_is_clamped_at_a_screen_edge(self, presented):
        # A naive centred patch around a cursor in the corner would run
        # off the virtual screen; the colour must still be the pixel
        # actually under the cursor.
        backend = _backend(_ONE_MONITOR)
        picked = _Recorder()
        overlay = _WaylandEyedropperOverlay(backend, picked)
        overlay._load_backdrop()

        overlay._on_button_press(1, 1)
        overlay._on_button_release(1, 1)

        assert picked.calls[0].args[0] == _screen_color(backend, 1, 1)


def _blit(ctx, backend: FakeCaptureBackend, region: Rect) -> None:
    """Paints just ``region`` of the fake screen onto ``ctx`` - the
    reference image for "this window drew its backdrop and nothing
    else".
    """
    from orcshot.ui.cairo_convert import numpy_to_cairo_surface

    ctx.set_source_surface(numpy_to_cairo_surface(backend.grab(region)), 0, 0)
    ctx.paint()


class TestRegionSelectWindow:
    """The X11 overlay: one POPUP window over the whole virtual screen,
    driven by Gdk events rather than pre-translated global coordinates.
    """

    def test_a_drag_delivers_the_absolute_rect_not_the_window_local_one(self):
        backend = _backend(_OFFSET_MONITOR)
        delivered = _Recorder()
        window = RegionSelectWindow(backend, delivered, capture_mouse_cursor=False)
        try:
            window._on_button_press(window, _Event(x=10, y=20))
            window._on_motion(window, _Event(x=50, y=70))
            window._on_button_release(window, _Event(x=50, y=70))
        finally:
            pass

        image, absolute, _cursor = delivered.calls[0].args
        assert absolute == Rect(-90, -30, -50, 20)
        assert np.array_equal(image, backend.grab(absolute))

    def test_a_click_with_no_drag_cancels(self):
        delivered, cancelled = _Recorder(), _Recorder()
        window = RegionSelectWindow(_backend(), delivered, cancelled, capture_mouse_cursor=False)

        window._on_button_press(window, _Event(x=30, y=30))
        window._on_button_release(window, _Event(x=30, y=30))

        assert delivered.count == 0
        assert cancelled.count == 1

    def test_a_release_with_no_press_is_ignored(self):
        delivered, cancelled = _Recorder(), _Recorder()
        window = RegionSelectWindow(_backend(), delivered, cancelled, capture_mouse_cursor=False)
        try:
            assert window._on_button_release(window, _Event(x=30, y=30)) is False
            assert delivered.count == 0
            assert cancelled.count == 0
        finally:
            window.destroy()

    def test_escape_cancels(self):
        delivered, cancelled = _Recorder(), _Recorder()
        window = RegionSelectWindow(_backend(), delivered, cancelled, capture_mouse_cursor=False)

        assert window._on_key_press(window, _Event(keyval=Gdk.KEY_Escape)) is True
        assert delivered.count == 0
        assert cancelled.count == 1

    def test_the_m_key_only_toggles_when_there_is_a_cursor_to_toggle(self):
        window = RegionSelectWindow(_backend(), _Recorder(), capture_mouse_cursor=False)
        try:
            assert window._cursor_snapshot is None
            # unhandled, so the keystroke is left for someone else
            assert window._on_key_press(window, _Event(keyval=Gdk.KEY_M)) is False
        finally:
            window.destroy()

    def test_the_captured_cursor_is_delivered_with_the_region(self):
        delivered = _Recorder()
        window = RegionSelectWindow(
            _backend(), delivered, capture_mouse_cursor=True, cursor_backend=_cursor_backend(x=60, y=60),
        )

        window._on_button_press(window, _Event(x=20, y=20))
        window._on_button_release(window, _Event(x=160, y=140))

        assert delivered.calls[0].args[2] is not None

    def test_the_selection_is_an_undimmed_hole_in_the_dim_overlay(self, monkeypatch):
        monkeypatch.setattr(region_select, "get_show_magnifier_while_selecting", lambda: False)
        backend = _backend(_ONE_MONITOR)
        dimmed = RegionSelectWindow(backend, _Recorder(), capture_mouse_cursor=False)
        selecting = RegionSelectWindow(backend, _Recorder(), capture_mouse_cursor=False)
        selecting._on_button_press(selecting, _Event(x=40, y=40))
        selecting._on_motion(selecting, _Event(x=160, y=120))
        try:
            without = _drawn(lambda ctx: dimmed._on_draw(dimmed, ctx))
            with_selection = _drawn(lambda ctx: selecting._on_draw(selecting, ctx))

            assert _brightness(with_selection, 60, 60) > _brightness(without, 60, 60)
        finally:
            dimmed.destroy()
            selecting.destroy()

    def test_the_sampled_cursor_and_the_magnifier_are_both_painted(self, monkeypatch):
        # The X11 overlay sizes its loupe from the monitor under the
        # cursor, not the whole virtual desktop, and paints the sampled
        # cursor at its one sampled position - both only reachable
        # through a draw with a cursor position set.
        monkeypatch.setattr(region_select, "get_show_magnifier_while_selecting", lambda: True)
        backend = _backend(_ONE_MONITOR)
        window = RegionSelectWindow(
            backend, _Recorder(), capture_mouse_cursor=True, cursor_backend=_cursor_backend(x=100, y=100),
        )
        bare = RegionSelectWindow(backend, _Recorder(), capture_mouse_cursor=False)
        try:
            window._on_motion(window, _Event(x=160, y=100))
            painted = _drawn(lambda ctx: window._on_draw(window, ctx))
            plain = _drawn(lambda ctx: bare._on_draw(bare, ctx))

            assert _pixel(painted, 102, 102) != _pixel(plain, 102, 102)  # the cursor preview

            # The loupe's own placement comes from core/magnifier.py, so
            # the probe asks it where the circle ended up rather than
            # hard-coding a pixel.
            diameter = magnifier_diameter(320, 200)
            offset_x, offset_y = magnifier_offset((160, 100), Rect(0, 0, 320, 200), None, diameter)
            centre = (160 + offset_x + diameter // 2, 100 + offset_y + diameter // 2)
            assert _pixel(painted, *centre) != _pixel(plain, *centre)
        finally:
            window.destroy()
            bare.destroy()

    def test_the_aiming_crosshair_is_drawn_before_a_drag_and_gone_during_one(self, monkeypatch):
        monkeypatch.setattr(region_select, "get_show_magnifier_while_selecting", lambda: False)
        backend = _backend(_ONE_MONITOR)
        aiming = RegionSelectWindow(backend, _Recorder(), capture_mouse_cursor=False)
        dragging = RegionSelectWindow(backend, _Recorder(), capture_mouse_cursor=False)
        aiming._on_motion(aiming, _Event(x=160, y=100))
        dragging._on_button_press(dragging, _Event(x=60, y=40))
        dragging._on_motion(dragging, _Event(x=160, y=100))
        try:
            before = _drawn(lambda ctx: aiming._on_draw(aiming, ctx))
            during = _drawn(lambda ctx: dragging._on_draw(dragging, ctx))

            # The crosshair runs the full width of the screen through the
            # cursor row, far from the selection rect's own border.
            assert _pixel(before, 4, 100) != _pixel(during, 4, 100)
        finally:
            aiming.destroy()
            dragging.destroy()


class TestWindowPickerWindow:
    def test_clicking_a_hovered_window_delivers_it_with_the_frozen_pixels(self):
        backend = _backend(_ONE_MONITOR)
        picked = _window(bounds=Rect(40, 30, 200, 150))
        delivered = _Recorder()
        window = WindowPickerWindow(
            backend, FakeWindowEnumerator([picked]), delivered, capture_mouse_cursor=False,
        )

        window._on_motion(window, _Event(x=100, y=100))
        window._on_button_press(window, _Event(x=100, y=100))

        image, info, _cursor = delivered.calls[0].args
        assert info is picked
        assert np.array_equal(image, backend.grab(picked.bounds))

    def test_an_activator_raises_the_window_and_regrabs_it_live(self):
        backend = _backend(_ONE_MONITOR)
        activator = FakeWindowActivator()
        picked = _window(window_id=99, bounds=Rect(40, 30, 200, 150))
        delivered = _Recorder()
        window = WindowPickerWindow(
            backend, FakeWindowEnumerator([picked]), delivered,
            capture_mouse_cursor=False, window_activator=activator,
        )

        window._on_motion(window, _Event(x=100, y=100))
        window._on_button_press(window, _Event(x=100, y=100))

        assert activator.activated == [99]
        assert backend.grabs[-1] == picked.bounds

    def test_hover_resolves_window_local_coordinates_against_an_offset_screen(self):
        # The window lives in absolute coordinates, the pointer arrives
        # in coordinates local to an overlay whose origin is not (0, 0).
        picked = _window(bounds=Rect(-60, -20, 20, 40))
        window = WindowPickerWindow(
            _backend(_OFFSET_MONITOR), FakeWindowEnumerator([picked]), _Recorder(), capture_mouse_cursor=False,
        )
        try:
            window._on_motion(window, _Event(x=50, y=40))  # absolute (-50, -10)

            assert window._hovered is picked
        finally:
            window.destroy()

    def test_clicking_where_no_window_is_cancels(self):
        delivered, cancelled = _Recorder(), _Recorder()
        window = WindowPickerWindow(
            _backend(), FakeWindowEnumerator([_window()]), delivered, cancelled, capture_mouse_cursor=False,
        )

        window._on_motion(window, _Event(x=5, y=5))
        window._on_button_press(window, _Event(x=5, y=5))

        assert delivered.count == 0
        assert cancelled.count == 1

    def test_escape_cancels(self):
        delivered, cancelled = _Recorder(), _Recorder()
        window = WindowPickerWindow(
            _backend(), FakeWindowEnumerator([_window()]), delivered, cancelled, capture_mouse_cursor=False,
        )

        assert window._on_key_press(window, _Event(keyval=Gdk.KEY_Escape)) is True
        assert delivered.count == 0
        assert cancelled.count == 1

    def test_the_captured_cursor_is_delivered_with_the_window(self):
        delivered = _Recorder()
        window = WindowPickerWindow(
            _backend(), FakeWindowEnumerator([_window(bounds=Rect(40, 30, 200, 150))]), delivered,
            capture_mouse_cursor=True, cursor_backend=_cursor_backend(x=100, y=100),
        )

        window._on_motion(window, _Event(x=100, y=100))
        window._on_button_press(window, _Event(x=100, y=100))

        assert delivered.calls[0].args[2] is not None

    def test_the_sampled_cursor_is_painted_on_the_overlay(self):
        backend = _backend(_ONE_MONITOR)
        window = WindowPickerWindow(
            backend, FakeWindowEnumerator([_window()]), _Recorder(),
            capture_mouse_cursor=True, cursor_backend=_cursor_backend(x=100, y=100),
        )
        bare = WindowPickerWindow(
            backend, FakeWindowEnumerator([_window()]), _Recorder(), capture_mouse_cursor=False,
        )
        try:
            painted = _drawn(lambda ctx: window._on_draw(window, ctx))
            plain = _drawn(lambda ctx: bare._on_draw(bare, ctx))

            assert _pixel(painted, 102, 102) != _pixel(plain, 102, 102)
        finally:
            window.destroy()
            bare.destroy()

    def test_the_m_key_drops_the_captured_cursor_from_the_next_capture(self):
        delivered = _Recorder()
        window = WindowPickerWindow(
            _backend(), FakeWindowEnumerator([_window(bounds=Rect(40, 30, 200, 150))]), delivered,
            capture_mouse_cursor=True, cursor_backend=_cursor_backend(x=100, y=100),
        )

        assert window._on_key_press(window, _Event(keyval=Gdk.KEY_M)) is True
        window._on_motion(window, _Event(x=100, y=100))
        window._on_button_press(window, _Event(x=100, y=100))

        assert window._cursor_visible is False
        assert delivered.calls[0].args[2] is None

    def test_the_hovered_window_is_an_undimmed_hole_in_the_dim_overlay(self):
        backend = _backend(_ONE_MONITOR)
        idle = WindowPickerWindow(backend, FakeWindowEnumerator([_window()]), _Recorder(), capture_mouse_cursor=False)
        hovering = WindowPickerWindow(
            backend, FakeWindowEnumerator([_window()]), _Recorder(), capture_mouse_cursor=False,
        )
        hovering._on_motion(hovering, _Event(x=100, y=100))
        try:
            without = _drawn(lambda ctx: idle._on_draw(idle, ctx))
            with_hover = _drawn(lambda ctx: hovering._on_draw(hovering, ctx))

            assert _brightness(with_hover, 100, 100) > _brightness(without, 100, 100)
        finally:
            idle.destroy()
            hovering.destroy()


class TestEyedropperOverlay:
    def test_a_press_samples_the_colour_under_the_cursor(self):
        backend = _backend(_ONE_MONITOR)
        picked = _Recorder()
        overlay = _EyedropperOverlay(backend, picked)

        overlay._on_button_press(overlay, _Event(x=90, y=110))
        overlay._on_button_release(overlay, _Event(x=90, y=110))

        assert picked.calls[0].args[0] == _screen_color(backend, 90, 110)

    def test_the_sample_is_a_live_grab_of_a_patch_around_the_cursor(self):
        # X11's version re-grabs per motion event, unlike Wayland's
        # frozen slice - the patch is clamped to stay on screen.
        backend = _backend(_ONE_MONITOR)
        overlay = _EyedropperOverlay(backend, _Recorder())
        try:
            overlay._on_button_press(overlay, _Event(x=1, y=1))

            assert backend.grabs == [Rect(0, 0, 25, 25)]
            assert overlay._current_color == _screen_color(backend, 1, 1)
        finally:
            overlay.destroy()

    def test_the_local_cursor_is_converted_to_absolute_before_grabbing(self):
        backend = _backend(_OFFSET_MONITOR)
        overlay = _EyedropperOverlay(backend, _Recorder())
        try:
            overlay._on_button_press(overlay, _Event(x=110, y=70))  # absolute (10, 20)

            assert overlay._current_color == _screen_color(backend, 10, 20)
        finally:
            overlay.destroy()

    def test_motion_without_a_press_samples_nothing(self):
        backend = _backend(_ONE_MONITOR)
        overlay = _EyedropperOverlay(backend, _Recorder())
        try:
            overlay._on_motion(overlay, _Event(x=90, y=110))

            assert backend.grabs == []
            assert overlay._current_color is None
        finally:
            overlay.destroy()

    def test_the_drag_keeps_resampling_and_the_last_sample_wins(self):
        backend = _backend(_ONE_MONITOR)
        picked = _Recorder()
        overlay = _EyedropperOverlay(backend, picked)

        overlay._on_button_press(overlay, _Event(x=30, y=40))
        overlay._on_motion(overlay, _Event(x=120, y=130))
        overlay._on_button_release(overlay, _Event(x=120, y=130))

        assert len(backend.grabs) == 2
        assert picked.calls[0].args[0] == _screen_color(backend, 120, 130)

    def test_a_release_with_nothing_sampled_cancels(self):
        picked, cancelled = _Recorder(), _Recorder()
        overlay = _EyedropperOverlay(_backend(), picked, cancelled)

        overlay._on_button_release(overlay, _Event(x=10, y=10))

        assert picked.count == 0
        assert cancelled.count == 1

    def test_escape_cancels(self):
        picked, cancelled = _Recorder(), _Recorder()
        overlay = _EyedropperOverlay(_backend(), picked, cancelled)

        assert overlay._on_key_press(overlay, _Event(keyval=Gdk.KEY_Escape)) is True
        assert picked.count == 0
        assert cancelled.count == 1

    def test_any_other_key_is_left_for_someone_else(self):
        # No "M" cursor toggle here, unlike the two capture overlays -
        # the eyedropper never captures the cursor at all.
        overlay = _EyedropperOverlay(_backend(), _Recorder())
        try:
            assert overlay._on_key_press(overlay, _Event(keyval=Gdk.KEY_m)) is False
        finally:
            overlay.destroy()

    def test_nothing_is_painted_until_something_has_been_sampled(self):
        backend = _backend(_ONE_MONITOR)
        overlay = _EyedropperOverlay(backend, _Recorder())
        try:
            blank = _drawn(lambda ctx: overlay._on_draw(overlay, ctx))
            overlay._on_button_press(overlay, _Event(x=90, y=110))
            sampled = _drawn(lambda ctx: overlay._on_draw(overlay, ctx))

            # The overlay itself is transparent: an untouched surface is
            # all it draws before a sample exists.
            assert set(bytes(blank.get_data())) == {0}
            assert bytes(sampled.get_data()) != bytes(blank.get_data())
        finally:
            overlay.destroy()


class TestGnomeShellVariants:
    """The two Shell-native entry points: the whole interaction runs
    inside the compositor, so all Python does is remember the region and
    execute the destination the Shell already chose.
    """

    def test_region_select_dispatches_the_chosen_destination_with_the_sampled_cursor(
        self, monkeypatch, no_real_destination,
    ):
        started = _Recorder()
        monkeypatch.setattr(region_select_gnome_shell, "start_region_select", started)
        backend = _backend(_ONE_MONITOR)
        region = Rect(20, 30, 140, 90)
        overlay = GnomeShellRegionSelect(
            capture_mouse_cursor=True, cursor_backend=_cursor_backend(x=60, y=60),
        )

        overlay.show()
        started.calls[0].args[0](backend.grab(region), region, "editor")

        dispatched = no_real_destination.dispatched
        assert dispatched.calls[0].args[0] == "editor"
        # placed relative to the region the Shell reported, not the screen
        assert dispatched.calls[0].args[2].bounds == Rect(60 - 1 - 20, 60 - 1 - 30, 60 - 1 - 20 + 8, 60 - 1 - 30 + 8)

    def test_window_picker_passes_the_window_title_on_for_the_filename(self, monkeypatch, no_real_destination):
        started = _Recorder()
        monkeypatch.setattr(window_picker_gnome_shell, "start_window_picker", started)
        backend = _backend(_ONE_MONITOR)
        region = Rect(40, 30, 200, 150)
        overlay = GnomeShellWindowPicker(
            capture_mouse_cursor=True, cursor_backend=_cursor_backend(x=100, y=100),
        )

        overlay.show()
        started.calls[0].args[0](backend.grab(region), region, "quick_save", "Terminal")

        dispatched = no_real_destination.dispatched
        assert dispatched.calls[0].kwargs["title"] == "Terminal"
        assert dispatched.calls[0].args[2] is not None


# --------------------------------------------------------------------
# The three module-level entry points and their per-session branching.
# --------------------------------------------------------------------


class TestStartRegionCapture:
    def test_an_x11_session_gets_the_single_popup_overlay(self, monkeypatch, no_real_destination, seat_ungrab):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")

        window = start_region_capture(_backend(), capture_mouse_cursor=False)

        assert isinstance(window, RegionSelectWindow)

    def test_the_selected_region_is_reported_and_handed_to_the_picker(
        self, monkeypatch, no_real_destination, seat_ungrab,
    ):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        shown = no_real_destination.shown
        captured = _Recorder()
        backend = _backend(_ONE_MONITOR)

        window = start_region_capture(backend, on_captured=captured, capture_mouse_cursor=False)
        window._on_button_press(window, _Event(x=20, y=30))
        window._on_button_release(window, _Event(x=120, y=110))

        # on_captured is "repeat last region"'s bookkeeping: it gets the
        # absolute rect, and it fires before the picker opens.
        assert captured.calls[0].args[0] == Rect(20, 30, 120, 110)
        assert shown.count == 1
        assert np.array_equal(shown.calls[0].args[0], backend.grab(Rect(20, 30, 120, 110)))

    def test_a_wayland_session_without_the_shell_extension_gets_the_per_monitor_overlay(
        self, monkeypatch, presented, no_real_destination,
    ):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setattr(gnome_region_select, "is_available", lambda: False)

        overlay = start_region_capture(_backend(_TWO_MONITORS), capture_mouse_cursor=False)

        assert isinstance(overlay, WaylandRegionSelect)
        assert len(presented) == 2  # one window per monitor
        destroy_all(overlay._windows)

    def test_a_wayland_session_with_the_shell_extension_runs_the_whole_flow_shell_side(
        self, monkeypatch, no_real_destination,
    ):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setattr(gnome_region_select, "is_available", lambda: True)
        started = _Recorder()
        monkeypatch.setattr(region_select_gnome_shell, "start_region_select", started)
        dispatched, shown = no_real_destination.dispatched, no_real_destination.shown
        captured = _Recorder()

        overlay = start_region_capture(_backend(), on_captured=captured, capture_mouse_cursor=False)

        assert isinstance(overlay, GnomeShellRegionSelect)
        assert started.count == 1

        region = Rect(20, 30, 120, 110)
        started.calls[0].args[0](_backend().grab(region), region, "clipboard")

        # The destination was already chosen Shell-side, so this path
        # dispatches it directly and shows no picker of its own.
        assert captured.calls[0].args[0] == region
        assert dispatched.calls[0].args[0] == "clipboard"
        assert shown.count == 0


class TestStartWindowPicker:
    def test_an_x11_session_gets_the_single_popup_overlay(self, monkeypatch, no_real_destination, seat_ungrab):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")

        window = start_window_picker(
            _backend(), FakeWindowEnumerator([_window()]), capture_mouse_cursor=False,
        )

        assert isinstance(window, WindowPickerWindow)

    def test_the_picked_window_is_reported_with_its_title_for_the_filename(
        self, monkeypatch, no_real_destination, seat_ungrab,
    ):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        shown = no_real_destination.shown
        captured = _Recorder()
        picked = _window(title="Terminal", bounds=Rect(40, 30, 200, 150))

        window = start_window_picker(
            _backend(), FakeWindowEnumerator([picked]), on_captured=captured, capture_mouse_cursor=False,
        )
        window._on_motion(window, _Event(x=100, y=100))
        window._on_button_press(window, _Event(x=100, y=100))

        assert captured.calls[0].args[0] == picked.bounds
        assert shown.calls[0].kwargs["title"] == "Terminal"

    def test_insert_window_bypasses_the_destination_picker_entirely(
        self, monkeypatch, no_real_destination, seat_ungrab,
    ):
        # Task #99: the image goes straight into the already-open
        # editor's layer instead of asking where to send it.
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        shown = no_real_destination.shown
        inserted = _Recorder()
        picked = _window(bounds=Rect(40, 30, 200, 150))
        backend = _backend(_ONE_MONITOR)

        window = start_window_picker(
            backend, FakeWindowEnumerator([picked]), on_window_captured=inserted, capture_mouse_cursor=False,
        )
        window._on_motion(window, _Event(x=100, y=100))
        window._on_button_press(window, _Event(x=100, y=100))

        assert shown.count == 0
        assert np.array_equal(inserted.calls[0].args[0], backend.grab(picked.bounds))

    def test_a_wayland_session_without_the_shell_extension_gets_the_per_monitor_overlay(
        self, monkeypatch, presented, no_real_destination,
    ):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setattr(gnome_window_picker, "is_available", lambda: False)

        overlay = start_window_picker(
            _backend(_TWO_MONITORS), FakeWindowEnumerator([_window()]), capture_mouse_cursor=False,
        )

        assert isinstance(overlay, WaylandWindowPicker)
        assert len(presented) == 2
        destroy_all(overlay._monitor_windows)

    def test_a_wayland_session_with_the_shell_extension_runs_the_whole_flow_shell_side(
        self, monkeypatch, no_real_destination,
    ):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setattr(gnome_window_picker, "is_available", lambda: True)
        started = _Recorder()
        monkeypatch.setattr(window_picker_gnome_shell, "start_window_picker", started)
        dispatched, shown = no_real_destination.dispatched, no_real_destination.shown

        overlay = start_window_picker(capture_mouse_cursor=False)

        assert isinstance(overlay, GnomeShellWindowPicker)
        assert started.count == 1

        region = Rect(40, 30, 200, 150)
        started.calls[0].args[0](_backend().grab(region), region, "clipboard", "Terminal")

        assert dispatched.calls[0].kwargs["title"] == "Terminal"
        assert shown.count == 0

    def test_force_plain_overlay_skips_the_shell_native_path(self, monkeypatch, presented, no_real_destination):
        # Insert Window needs the plain click-to-capture overlay even
        # where the Shell extension is available: the Shell-side one
        # picks a destination itself, with no hook for "hand it back to
        # this editor".
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setattr(gnome_window_picker, "is_available", lambda: True)

        overlay = start_window_picker(
            _backend(), FakeWindowEnumerator([_window()]), capture_mouse_cursor=False, force_plain_overlay=True,
        )

        assert isinstance(overlay, WaylandWindowPicker)
        destroy_all(overlay._monitor_windows)


@pytest.fixture
def trigger_widget():
    """A stand-in for the colour dialog's eyedropper button: a real
    widget in a real toplevel, which start_eyedropper reaches through
    get_toplevel() and Gtk.grab_get_current().
    """
    window = Gtk.Window()
    button = Gtk.Button(label="pick")
    window.add(button)
    window.show_all()
    yield button
    window.destroy()


def _capture_overlay(monkeypatch, module, name):
    """Wraps an overlay class so a test can reach the instance
    start_eyedropper builds and never returns.
    """
    created = []
    real = getattr(module, name)

    def spy(*args, **kwargs):
        overlay = real(*args, **kwargs)
        created.append(overlay)
        return overlay

    monkeypatch.setattr(module, name, spy)
    return created


class TestStartEyedropper:
    def test_an_x11_session_gets_the_single_popup_overlay(self, monkeypatch, trigger_widget, seat_ungrab):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        created = _capture_overlay(monkeypatch, eyedropper, "_EyedropperOverlay")

        start_eyedropper(trigger_widget, _Recorder(), capture_backend=_backend())

        assert len(created) == 1
        assert isinstance(created[0], _EyedropperOverlay)

    def test_the_picked_colour_reaches_the_caller(self, monkeypatch, trigger_widget, seat_ungrab):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        created = _capture_overlay(monkeypatch, eyedropper, "_EyedropperOverlay")
        backend = _backend(_ONE_MONITOR)
        picked = _Recorder()

        start_eyedropper(trigger_widget, picked, capture_backend=backend)
        overlay = created[0]
        overlay._on_button_press(overlay, _Event(x=90, y=110))
        overlay._on_button_release(overlay, _Event(x=90, y=110))

        assert picked.calls[0].args[0] == _screen_color(backend, 90, 110)

    def test_the_dialogs_modal_grab_is_suspended_for_the_pick_and_restored_after(
        self, monkeypatch, trigger_widget, seat_ungrab,
    ):
        # The colour dialog runs inside Gtk.Dialog.run(), which holds a
        # GTK-level grab that would otherwise swallow every event meant
        # for the overlay - see start_eyedropper's own comment.
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        created = _capture_overlay(monkeypatch, eyedropper, "_EyedropperOverlay")
        trigger_widget.grab_add()
        assert Gtk.grab_get_current() is trigger_widget

        start_eyedropper(trigger_widget, _Recorder(), capture_backend=_backend())

        assert Gtk.grab_get_current() is None
        overlay = created[0]
        overlay._on_button_press(overlay, _Event(x=50, y=50))
        overlay._on_button_release(overlay, _Event(x=50, y=50))

        assert Gtk.grab_get_current() is trigger_widget
        trigger_widget.grab_remove()

    def test_a_cancelled_pick_also_restores_the_grab(self, monkeypatch, trigger_widget, seat_ungrab):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        created = _capture_overlay(monkeypatch, eyedropper, "_EyedropperOverlay")
        trigger_widget.grab_add()
        cancelled = _Recorder()

        start_eyedropper(trigger_widget, _Recorder(), cancelled, capture_backend=_backend())
        overlay = created[0]
        overlay._on_key_press(overlay, _Event(keyval=Gdk.KEY_Escape))

        assert cancelled.count == 1
        assert Gtk.grab_get_current() is trigger_widget
        trigger_widget.grab_remove()

    def test_a_wayland_session_without_the_shell_extension_gets_the_per_monitor_overlay(
        self, monkeypatch, trigger_widget, presented,
    ):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setattr(gnome_eyedropper, "is_available", lambda: False)
        created = _capture_overlay(monkeypatch, eyedropper_wayland, "_WaylandEyedropperOverlay")
        backend = _backend(_ONE_MONITOR)
        picked = _Recorder()

        start_eyedropper(trigger_widget, picked, capture_backend=backend)

        assert len(created) == 1
        overlay = created[0]
        overlay._load_backdrop()
        overlay._on_button_press(60, 70)
        overlay._on_button_release(60, 70)

        assert picked.calls[0].args[0] == _screen_color(backend, 60, 70)

    def test_a_wayland_session_with_the_shell_extension_needs_no_overlay_window_at_all(
        self, monkeypatch, trigger_widget,
    ):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setattr(gnome_eyedropper, "is_available", lambda: True)
        started = _Recorder()
        monkeypatch.setattr(gnome_eyedropper, "start_eyedropper", started)
        created = _capture_overlay(monkeypatch, eyedropper_wayland, "_WaylandEyedropperOverlay")
        picked = _Recorder()

        start_eyedropper(trigger_widget, picked, capture_backend=_backend())

        assert created == []
        assert started.count == 1

        started.calls[0].args[0]((12, 34, 56, 255))

        assert picked.calls[0].args[0] == (12, 34, 56, 255)

    def test_a_cancelled_shell_native_pick_restores_the_dialogs_grab(self, monkeypatch, trigger_widget):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setattr(gnome_eyedropper, "is_available", lambda: True)
        started = _Recorder()
        monkeypatch.setattr(gnome_eyedropper, "start_eyedropper", started)
        trigger_widget.grab_add()
        cancelled = _Recorder()

        start_eyedropper(trigger_widget, _Recorder(), cancelled, capture_backend=_backend())
        assert Gtk.grab_get_current() is None

        started.calls[0].args[1]()

        assert cancelled.count == 1
        assert Gtk.grab_get_current() is trigger_widget
        trigger_widget.grab_remove()


class TestLazyDefaultBackends:
    """None of the three entry points constructs a real X11/portal
    adapter at import time - each resolves its default only when called,
    which is what lets these modules be imported with no display at all.
    """

    def test_region_capture_resolves_the_default_capture_backend(
        self, monkeypatch, no_real_destination, seat_ungrab,
    ):
        from orcshot.capture import backend_select

        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        backend = _backend(_ONE_MONITOR)
        monkeypatch.setattr(backend_select, "default_capture_backend", lambda: backend)

        window = start_region_capture(capture_mouse_cursor=False)

        assert window._frozen_image.shape == (200, 320, 4)
        assert backend.grabs == [Rect(0, 0, 320, 200)]

    def test_the_window_picker_resolves_its_default_enumerator_and_activator(
        self, monkeypatch, no_real_destination, seat_ungrab,
    ):
        from orcshot.capture import backend_select

        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        backend = _backend(_ONE_MONITOR)
        activator = FakeWindowActivator()
        picked = _window(window_id=99, bounds=Rect(40, 30, 200, 150))
        monkeypatch.setattr(backend_select, "default_capture_backend", lambda: backend)
        monkeypatch.setattr(
            backend_select, "default_window_enumerator_and_activator",
            lambda: (FakeWindowEnumerator([picked]), activator),
        )

        window = start_window_picker(capture_mouse_cursor=False)
        window._on_motion(window, _Event(x=100, y=100))
        window._on_button_press(window, _Event(x=100, y=100))

        # the activator came from the default pair too, not from nowhere
        assert activator.activated == [99]

    def test_the_eyedropper_resolves_the_default_capture_backend(
        self, monkeypatch, trigger_widget, seat_ungrab,
    ):
        from orcshot.capture import backend_select

        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        backend = _backend(_ONE_MONITOR)
        monkeypatch.setattr(backend_select, "default_capture_backend", lambda: backend)
        created = _capture_overlay(monkeypatch, eyedropper, "_EyedropperOverlay")
        picked = _Recorder()

        start_eyedropper(trigger_widget, picked)
        overlay = created[0]
        overlay._on_button_press(overlay, _Event(x=90, y=110))
        overlay._on_button_release(overlay, _Event(x=90, y=110))

        assert picked.calls[0].args[0] == _screen_color(backend, 90, 110)


class TestAnchorWindowLifetime:
    """Under Wayland the destination picker is a popup, which needs a
    real, still-mapped parent surface - so the monitor window holding
    the click stays alive until the picker closes, and is dropped then.
    """

    def test_region_capture_keeps_the_anchor_window_until_the_picker_closes(
        self, monkeypatch, presented, no_real_destination,
    ):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setattr(gnome_region_select, "is_available", lambda: False)
        overlay = start_region_capture(_backend(_ONE_MONITOR), capture_mouse_cursor=False)
        anchor = overlay._windows[0]

        overlay._on_button_press(20, 30)
        overlay._on_button_release(120, 110)

        assert no_real_destination.shown.calls[0].kwargs["anchor_window"] is anchor.get_window()
        assert anchor.get_visible() is True

        no_real_destination.menus[0].emit("deactivate")

        assert anchor.get_visible() is False

    def test_the_window_picker_drops_its_anchor_when_the_picker_closes(
        self, monkeypatch, presented, no_real_destination,
    ):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setattr(gnome_window_picker, "is_available", lambda: False)
        overlay = start_window_picker(
            _backend(_ONE_MONITOR), FakeWindowEnumerator([_window(bounds=Rect(40, 30, 200, 150))]),
            capture_mouse_cursor=False,
        )
        anchor = overlay._monitor_windows[0]

        overlay._on_motion(100, 100)
        overlay._on_button_press(100, 100)

        assert anchor.get_visible() is True
        no_real_destination.menus[0].emit("deactivate")
        assert anchor.get_visible() is False

    def test_insert_window_drops_the_anchor_immediately_with_no_picker_at_all(
        self, monkeypatch, presented, no_real_destination,
    ):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setattr(gnome_window_picker, "is_available", lambda: False)
        inserted = _Recorder()
        overlay = start_window_picker(
            _backend(_ONE_MONITOR), FakeWindowEnumerator([_window(bounds=Rect(40, 30, 200, 150))]),
            on_window_captured=inserted, capture_mouse_cursor=False, force_plain_overlay=True,
        )
        anchor = overlay._monitor_windows[0]

        overlay._on_motion(100, 100)
        overlay._on_button_press(100, 100)

        assert inserted.count == 1
        assert no_real_destination.shown.count == 0
        assert anchor.get_visible() is False
