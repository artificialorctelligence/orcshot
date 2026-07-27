"""The clipboard port: what every platform adapter must provide.

Ports-and-adapters, matching CaptureBackend/WindowEnumerator: a narrow
Protocol, a real GTK/X11-backed adapter (x11_clipboard.py), and an
in-memory fake for tests (capture/fake.py).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class ClipboardBackend(Protocol):
    def set_image(self, image: np.ndarray) -> None:
        """Put ``image`` (an (H, W, 4) uint8 RGBA array) on the clipboard."""
