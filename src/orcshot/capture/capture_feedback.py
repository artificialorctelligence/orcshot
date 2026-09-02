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

**Sound mechanism (rewritten 2026-09-01, BACKLOG #195)**: this used to
play a themed system sound via GSound (gir1.2-gsound-1.0), resolved by
event ID from whatever sound theme was installed. That broke on the
Flatpak channel - gir1.2-gsound-1.0's typelib has no equivalent in
org.gnome.Platform//50 or org.gnome.Sdk//50 (confirmed live), and
staging GSound from source turned out to need building *two* libraries
(GSound itself, plus its own libcanberra dependency - neither has a
Flathub shared-module) - real, non-trivial work, investigated and
rejected as out of scope for what should be a decorative sound effect.

Replaced with GStreamer playing a bundled sound file instead, for two
reasons, both confirmed live rather than assumed:

1. **GStreamer is genuinely available everywhere this project ships**,
   unlike GSound. `org.gnome.Platform//50` already bundles its Python
   bindings and the `playbin`/`vorbisdec` elements this module needs
   (`gst-plugins-base`, confirmed via `gst-inspect-1.0` - no manifest
   change needed for the typelib itself, just `--socket=pulseaudio`
   for actual audio output, which the Flatpak manifest didn't have at
   all before this - real playback verified live end-to-end inside a
   genuine Flatpak sandbox, `GstPulseSinkClock` connecting and reaching
   EOS cleanly). apt and Snap get the same two real Ubuntu packages
   (`gir1.2-gstreamer-1.0`, `gstreamer1.0-plugins-base`) the normal way.
2. **Real playback was verified live on three separate machines**
   (this project's own Mint dev host, a real Ubuntu 24.04.4 LTS VM, a
   real Ubuntu 26.04/GNOME 50 VM) - not just one, specifically to rule
   out a machine-specific fluke, since this whole rewrite exists
   *because* an earlier "commonly present" assumption about GSound
   turned out to be false for one channel.

The sound file itself (`resources/camera-shutter.oga`) is the real
`camera-shutter.oga` from the `sound-theme-freedesktop` package - the
same file GSound's own `"camera-shutter"` event ID already resolved to
on a standard install, so this sounds identical to what most users
already heard before this rewrite, just bundled instead of resolved
from the desktop's own theme at runtime (direflail's own explicit
call: consistent behavior across installs isn't required - "i'm ok if
it's different between installs" - this was chosen for being simpler
and removing GSound entirely, not because per-theme variation needed
eliminating). CC-BY-SA-3.0, credited to freesound user
`horsthorstensen` - see THIRD_PARTY_NOTICES.md for the full
attribution, matching this project's own established convention for
bundled third-party assets.
"""

from __future__ import annotations

import gi

from gi.repository import Gio, GLib

try:
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
except ValueError:
    # Confirmed live to be genuinely present on every channel this
    # project ships (see module docstring) - this guard is kept
    # anyway, defensively, for the same reason the rest of this module
    # now exists: an earlier "commonly present" assumption about a
    # different library (GSound) turned out to be false for one
    # channel. Without this guard, gi.require_version would raise
    # ValueError at *import* time, and this module is imported
    # unconditionally from app.py's own do_startup path
    # (_register_tray_actions), crashing every normal launch on
    # whichever channel it happened on - not just the capture-sound
    # feature. Gst stays None; play_capture_sound below degrades to a
    # silent no-op, the same "decorative feedback, never interrupt a
    # capture" reasoning as the existing `except GLib.Error` a few
    # lines down, which guards its own separate case (a *present* Gst
    # failing at runtime, e.g. no audio sink available).
    Gst = None

from orcshot.resources import CAMERA_SHUTTER_SOUND_PATH
from orcshot.settings import get_play_capture_sound, get_show_capture_notification

_CAPTURE_NOTIFICATION_ID = "orcshot-capture-complete"

_player = None
_gst_initialized = False


def _get_player() -> Gst.Element | None:
    global _player, _gst_initialized
    if Gst is None:
        return None
    if not _gst_initialized:
        Gst.init(None)
        _gst_initialized = True
    if _player is None:
        _player = Gst.ElementFactory.make("playbin", "orcshot-capture-sound-player")
    return _player


def play_capture_sound() -> None:
    if not get_play_capture_sound():
        return
    player = _get_player()
    if player is None:
        # Gst unavailable at import time on this channel - see the
        # module-level guard above. Nothing to play.
        return
    try:
        # Reset to NULL first - a still-PLAYING pipeline from a rapid
        # previous capture needs to stop before the URI can be
        # changed and playback restarted.
        player.set_state(Gst.State.NULL)
        player.set_property("uri", Gst.filename_to_uri(str(CAMERA_SHUTTER_SOUND_PATH)))
        player.set_state(Gst.State.PLAYING)
    except GLib.Error:
        # Decorative feedback, not core functionality - a missing
        # audio sink or unavailable audio subsystem must never
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
