"""Monitor/virtual-screen geometry via GDK's own display API.

Not specific to X11 or Wayland - GDK abstracts the actual windowing
backend itself (auto-selected from the session, GDK_BACKEND, etc.), so
monitor enumeration works the same way regardless of which protocol is
underneath. Shared by X11CaptureBackend and WaylandCaptureBackend, which
only differ in how they actually grab pixels (direct root-window read
vs the XDG Desktop Portal), not in how they enumerate monitors -
originally lived only in x11.py, extracted here once a second backend
needed the exact same logic rather than a duplicate copy.
"""

from __future__ import annotations

import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk

from greenshot_linux.capture.backend import Monitor, ScreenLayout
from greenshot_linux.core.geometry import Rect


def gdk_screen_layout(display=None) -> ScreenLayout:
    if display is None:
        display = Gdk.Display.get_default()
    monitors = []
    primary = display.get_primary_monitor()
    for index in range(display.get_n_monitors()):
        gdk_monitor = display.get_monitor(index)
        geometry = gdk_monitor.get_geometry()
        # Geometry is in application pixels; on a scaled display the
        # framebuffer is scale_factor times larger in each direction.
        scale = gdk_monitor.get_scale_factor()
        monitors.append(
            Monitor(
                name=gdk_monitor.get_model() or f"monitor-{index}",
                bounds=Rect(
                    geometry.x * scale,
                    geometry.y * scale,
                    (geometry.x + geometry.width) * scale,
                    (geometry.y + geometry.height) * scale,
                ),
                is_primary=(
                    gdk_monitor.is_primary()
                    if primary is None
                    else gdk_monitor == primary
                ),
            )
        )
    return ScreenLayout(monitors)
