"""Capture-complete feedback (task #126/#158): a themed system sound
and/or a desktop notification, right after a capture completes -
faithful port of Windows' own Capture-tab "Play camera sound"/"Show
notification" checkboxes (CaptureHelper.cs's DoCaptureFeedback,
ICoreConfiguration.cs's PlayCameraSound/ShowTrayNotification - see
settings.py's own get_play_capture_sound/get_show_capture_notification
docstrings for the exact citation).

play_capture_sound() and show_capture_complete_notification() are
separate functions, not one combined call, because they fire from two
different moments depending on platform:

- ui/destination_picker.py's show_destination_picker (X11's own
  Gtk.Menu, and the Wayland portal-fallback path) calls both together,
  right as the picker itself is about to appear - direflail's own
  explicit confirmation this is the correct timing, matching Windows.
- The Wayland Shell-native path is different: the *entire*
  capture-then-show-picker round trip happens inside the bundled
  GNOME Shell extension's own JS code as one opaque D-Bus call
  (gnome_capture_rect.py/region_select_gnome_shell.py/
  window_picker_gnome_shell.py) - Python only ever learns which
  destination was chosen *after* the user has already picked one, via
  dispatch_destination. Calling play_capture_sound() there would fire
  it a beat late, after the choice, not when the picker actually
  appeared - live-reported by direflail as a real, audible difference
  from the (correct) X11 timing. So the sound is instead triggered
  from inside the extension itself (extension.js's own
  pickDestinationAsync, right before its menu opens) via a new
  "play-capture-sound" GAction - see app.py's own registration of it
  and extension.js's own comment at that call site. dispatch_destination
  only calls show_capture_complete_notification() - the notification's
  timing was never reported as a problem, so it's left exactly where
  it was.

The sound uses GSound (gir1.2-gsound-1.0), a small freedesktop library
purpose-built for playing themed system sounds by event ID -
"camera-shutter" is the same sound-theme event GNOME's own Screenshot
utility uses for this exact purpose (confirmed live: a real,
recognized event, distinct from an unrecognized one which raises
GLib.Error - see this module's own tests). Chosen over bundling a
custom sound file (what Windows Greenshot does, via an embedded WAV
resource) or shelling out to canberra-gtk-play: GSound is the
standard GNOME-native mechanism for exactly this, already commonly
present on any GNOME/GTK3 desktop.
"""

from __future__ import annotations

import gi

gi.require_version("GSound", "1.0")
from gi.repository import Gio, GLib, GSound

from orcshot.settings import get_play_capture_sound, get_show_capture_notification

_CAMERA_SHUTTER_EVENT_ID = "camera-shutter"
_CAPTURE_NOTIFICATION_ID = "orcshot-capture-complete"

_sound_context = None


def _get_sound_context() -> GSound.Context:
    global _sound_context
    if _sound_context is None:
        _sound_context = GSound.Context.new()
    return _sound_context


def play_capture_sound() -> None:
    if not get_play_capture_sound():
        return
    try:
        _get_sound_context().play_simple({GSound.ATTR_EVENT_ID: _CAMERA_SHUTTER_EVENT_ID}, None)
    except GLib.Error:
        # Decorative feedback, not core functionality - a missing
        # sound theme or unavailable audio subsystem must never
        # interrupt an actual capture, same reasoning as every other
        # best-effort GLib.Error guard in this codebase (e.g. app.py's
        # own _quit_and_hide_tray_button).
        pass


def show_capture_complete_notification() -> None:
    if not get_show_capture_notification():
        return
    app = Gio.Application.get_default()
    # None in standalone-script/test contexts with no running
    # Gio.Application - same guard editor_window.py's own
    # register_editor_window call uses for the same reason.
    if app is not None:
        notification = Gio.Notification.new("Screenshot captured")
        notification.set_body("Choose what to do with it.")
        notification.set_icon(Gio.ThemedIcon.new("orcshot"))
        app.send_notification(_CAPTURE_NOTIFICATION_ID, notification)


def play_capture_feedback() -> None:
    """Both halves together, each still checking its own preference
    internally - see this module's own docstring for exactly which
    callers should use this vs. the two functions above individually."""
    play_capture_sound()
    show_capture_complete_notification()
