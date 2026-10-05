"""Pure region-resolution logic for each capture mode: given a
CaptureBackend/WindowEnumerator, what Rect should get grabbed. Kept
separate from the actual grab + launch-EditorWindow glue
(ui/capture_modes.py) so it's unit testable against the fakes without
needing GTK.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Optional, Sequence

from orcshot.capture.backend import CaptureBackend
from orcshot.capture.window import WindowEnumerator, WindowInfo
from orcshot.core.geometry import Rect


def full_screen_region(capture_backend: CaptureBackend) -> Rect:
    return capture_backend.screen_layout().virtual_bounds


def active_window_info(capture_backend: CaptureBackend, window_enumerator: WindowEnumerator) -> Optional[WindowInfo]:
    """The currently focused window, its ``bounds`` clamped to the
    virtual screen (a window's reported geometry can extend slightly
    past it - e.g. after being dragged partly off-screen), or None if
    there's no active window (focus could be on the desktop itself) or
    it's entirely off-screen.

    Was ``active_window_region`` (returning just the clamped Rect)
    until task #139 - callers now also need ``.title`` to fill in the
    ``${title}`` filename pattern token (core/filename_pattern.py),
    which real Windows Greenshot always has available for these two
    capture modes (FilenameHelper.cs's own ${title} substitution)
    since a captured window always has one, unlike region/full-screen
    capture.
    """
    window = window_enumerator.active_window()
    if window is None:
        return None
    clamped = capture_backend.screen_layout().clamp(window.bounds)
    if clamped is None:
        return None
    return replace(window, bounds=clamped)


class HeadlessCaptureError(RuntimeError):
    """A headless capture cannot be performed correctly, with the reason
    as its message - one line, for stderr and a non-zero exit."""


def resolve_window_for_headless_capture(
    windows: Sequence[WindowInfo],
    on_current_workspace: Callable[[WindowInfo], bool],
    title: str,
) -> WindowInfo:
    """The window ``title`` names, or a refusal saying why it cannot be
    captured correctly right now (BACKLOG #225).

    Refusing matters here in a way it does not for the interactive
    picker. Neither platform reads a window's own buffer: X11 crops a
    frozen full-screen grab, and GNOME's ``capture-rect`` crops a stage
    screenshot. So a window that is minimised, on another workspace, or
    covered by something else does not produce its own pixels - it
    produces whatever is actually on screen there, with no error. A
    person looking at the result would notice; the scripted caller this
    exists for cannot. A wrong image is worse than no image, so this
    raises instead.

    ``windows`` is ``WindowEnumerator.list_windows()``'s own bottom-to-
    top stacking order, so everything after the target is drawn over it.
    That contract holds on both platforms: X11 reads
    ``_NET_CLIENT_LIST_STACKING``, and GNOME's ``list-windows`` iterates
    ``global.get_window_actors()``, documented bottom-to-top and already
    relied on by the Shell-side window picker's own hover logic.

    ``on_current_workspace`` is a callback rather than a ``WindowInfo``
    field on purpose. Workspace membership is not part of the
    cross-platform enumerator contract and nothing else needs it; adding
    it to ``WindowInfo`` would ripple into every fake and every contract
    test for one caller's benefit. GNOME gets it free from
    ``list-windows``' own ``in_current_workspace``; X11 reads
    ``_NET_WM_DESKTOP`` against the root's ``_NET_CURRENT_DESKTOP``.

    Only for ``--window``: a full-screen capture cannot be wrongly
    occluded, since whatever is on top is exactly what was asked for.
    """
    needle = title.lower()
    matches = [window for window in windows if needle in window.title.lower()]
    if not matches:
        raise HeadlessCaptureError(f"no window matching {title!r}")

    # Last match, not first: bottom-to-top order means the last one is
    # the topmost, the same "last match wins" rule ui/window_picker.py
    # already uses to decide what a click landed on.
    target = matches[-1]
    if target.is_minimized:
        raise HeadlessCaptureError(f"window {target.title!r} is minimised")
    if not on_current_workspace(target):
        raise HeadlessCaptureError(f"window {target.title!r} is on another workspace")

    target_index = next(i for i, window in enumerate(windows) if window.window_id == target.window_id)
    for above in windows[target_index + 1:]:
        # Above in the stacking order but not actually on screen covers
        # nothing - a minimised or off-workspace window draws no pixels.
        if above.is_minimized or not on_current_workspace(above):
            continue
        if above.bounds.intersect(target.bounds) is not None:
            raise HeadlessCaptureError(f"window {target.title!r} is covered by {above.title!r}")
    return target
