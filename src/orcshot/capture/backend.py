"""The capture port: what every platform adapter must provide.

Adapters (X11 now, Wayland later, a fake for tests) implement
``CaptureBackend``. Everything reusable across adapters — multi-monitor
geometry — lives in ``ScreenLayout`` so it can be tested without a display.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

import numpy as np

from orcshot.core.geometry import Rect


@dataclass(frozen=True)
class Monitor:
    name: str
    bounds: Rect
    is_primary: bool = False


class ScreenLayout:
    """An arbitrary arrangement of monitors on the virtual screen.

    Makes no assumptions about monitor count, ordering, resolution, or
    which one is at the origin. Layouts may contain dead space: monitors
    of differing heights leave regions that are inside the virtual bounds
    but on no physical monitor.
    """

    def __init__(self, monitors: Sequence[Monitor]):
        if not monitors:
            raise ValueError("a screen layout needs at least one monitor")
        self.monitors = tuple(monitors)
        self.virtual_bounds = Rect.union_all(m.bounds for m in self.monitors)

    @property
    def primary(self) -> Monitor:
        for monitor in self.monitors:
            if monitor.is_primary:
                return monitor
        return self.monitors[0]

    def monitor_at(self, x: int, y: int) -> Monitor | None:
        for monitor in self.monitors:
            if monitor.bounds.contains(x, y):
                return monitor
        return None

    def clamp(self, rect: Rect) -> Rect | None:
        """Trim ``rect`` to the virtual screen, or None if it falls outside."""
        return rect.intersect(self.virtual_bounds)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ScreenLayout):
            return NotImplemented
        return self.monitors == other.monitors

    def __repr__(self) -> str:
        return f"ScreenLayout({list(self.monitors)!r})"


@runtime_checkable
class CaptureBackend(Protocol):
    """A source of screen pixels for one display protocol."""

    def screen_layout(self) -> ScreenLayout:
        """The current monitor arrangement, re-queried on each call so
        that hotplugged or rearranged monitors are picked up."""

    def grab(self, rect: Rect) -> np.ndarray:
        """Capture ``rect`` of the virtual screen as (H, W, 4) uint8 RGBA.

        ``rect`` must lie within the current virtual bounds; callers
        replaying a stored region should ``ScreenLayout.clamp`` it first.
        """
