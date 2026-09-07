"""Paths to the app's bundled assets.

LOGO_PATH: the real logo image (not a recreation) - used for the
window/taskbar icon (Gtk.Window.set_default_icon_from_file, see
app.py's do_startup) and the About dialog's logo (editor_window.py),
and referenced by the autostart .desktop entry's Icon field (see
autostart.py). The tray icon (BACKLOG #189) is a separate installed
asset instead: both the GNOME Shell extension and the Cinnamon applet
reference it by icon-theme name (Gio.ThemedIcon.new("orcshot")/
set_applet_icon_name("orcshot")), resolving to
usr/share/icons/hicolor/128x128/apps/orcshot.png via
debian/orcshot.install - not this module's LOGO_PATH, since those run
in a separate process (GNOME Shell/Cinnamon) that can't read this
app's own resources/ directory. One shared asset for every icon
surface LOGO_PATH itself does cover, rather than a separate
hand-drawn recreation per surface - simpler, and matches "this is
supposed to be a port" (exact fidelity to the original mark) over a
stylized approximation.

CAMERA_SHUTTER_SOUND_PATH: the capture-complete sound - see
capture/capture_feedback.py's own module docstring for the full
sourcing/licensing story and why it's bundled rather than resolved
from the desktop's own sound theme.
"""

from __future__ import annotations

from pathlib import Path

RESOURCES_DIR = Path(__file__).parent / "resources"
LOGO_PATH = RESOURCES_DIR / "orcshot.png"
CAMERA_SHUTTER_SOUND_PATH = RESOURCES_DIR / "camera-shutter.oga"
