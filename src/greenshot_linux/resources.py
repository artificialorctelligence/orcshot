"""Path to the app's bundled logo asset (the real image, not a
recreation) - used for both the window/taskbar icon
(Gtk.Window.set_default_icon_from_file, see app.py's do_startup) and
the system tray icon (Gtk.StatusIcon.set_from_file, see
_build_tray_icon), and referenced by the autostart .desktop entry's
Icon field (see autostart.py). One shared asset for every icon
surface, rather than a separate hand-drawn recreation per surface -
simpler, and matches "this is supposed to be a port" (exact fidelity
to the original mark) over a stylized approximation.
"""

from __future__ import annotations

from pathlib import Path

RESOURCES_DIR = Path(__file__).parent / "resources"
LOGO_PATH = RESOURCES_DIR / "greenshot-linux.png"
