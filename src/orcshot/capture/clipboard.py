"""The clipboard port: what every platform adapter must provide.

Ports-and-adapters, matching CaptureBackend/WindowEnumerator: a narrow
Protocol, real GTK-backed adapters (x11_clipboard.py, wayland_clipboard.py -
see the latter's docstring for the one real difference between them),
and an in-memory fake for tests (capture/fake.py). backend_select.py's
default_clipboard_backend() picks the right one for the session.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class ClipboardBackend(Protocol):
    def set_image(self, image: np.ndarray) -> None:
        """Put ``image`` (an (H, W, 4) uint8 RGBA array) on the clipboard."""
