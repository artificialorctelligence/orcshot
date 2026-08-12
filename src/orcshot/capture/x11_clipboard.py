"""GTK clipboard adapter.

Uses Gtk.Clipboard.set_image, which advertises the pixbuf under the
standard image targets GDK/GTK support (image/png, image/bmp, ...) -
the Linux/X11 equivalent of the Windows source's multi-format
clipboard support (ClipboardFormat.PNG/DIB/BITMAP/DIBV5 in
Greenshot.Base/Core/Enums/ClipboardFormat.cs). DIB/BITMAP/DIBV5 are
Windows GDI-specific formats with no X11 analogue, so this doesn't
attempt to reproduce them - one well-supported image target is enough
for pasting into GIMP, LibreOffice, browsers, and chat apps.

clipboard.store() asks the X clipboard manager to persist the data
past this process exiting, matching what a user expects "copy" to do.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

import numpy as np

from orcshot.ui.gdk_convert import numpy_to_pixbuf


class X11ClipboardBackend:
    def set_image(self, image: np.ndarray) -> None:
        clipboard = Gtk.Clipboard.get_default(Gdk.Display.get_default())
        clipboard.set_image(numpy_to_pixbuf(image))
        clipboard.store()
