"""play_capture_feedback's own settings-gating logic - each half
(sound/notification) independently skips its external call when its
own preference is off. The external calls themselves (GStreamer audio
playback, a real desktop notification) are GLib/GTK glue with no
meaningful headless test - verified live instead, same precedent as
every other file under ui/ that talks to the real desktop.
"""

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

import orcshot.capture.capture_feedback as capture_feedback_mod
from orcshot.capture.capture_feedback import (
    play_capture_feedback, play_capture_sound, show_capture_complete_notification,
)
from orcshot.settings import set_play_capture_sound, set_show_capture_notification


class _FakeGstPlayer:
    """Stands in for the real Gst.ElementFactory.make("playbin", ...)
    element - only the two calls play_capture_sound() actually makes
    on it, matching how _FakeSoundContext only implemented
    play_simple() before this module's GSound->GStreamer switch."""

    def __init__(self):
        self.states = []
        self.properties = {}

    def set_state(self, state):
        self.states.append(state)
        return Gst.StateChangeReturn.SUCCESS

    def set_property(self, name, value):
        self.properties[name] = value


class _FakeApp:
    def __init__(self):
        self.notifications = []

    def send_notification(self, notification_id, notification):
        self.notifications.append((notification_id, notification))


class TestPlayCaptureFeedback:
    def test_plays_sound_when_enabled(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(True, path=config_path)
        set_show_capture_notification(False, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_player = _FakeGstPlayer()
        monkeypatch.setattr("orcshot.capture.capture_feedback._get_player", lambda: fake_player)
        monkeypatch.setattr("orcshot.capture.capture_feedback.Gio.Application.get_default", lambda: None)

        play_capture_feedback()

        assert Gst.State.PLAYING in fake_player.states

    def test_skips_sound_when_disabled(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(False, path=config_path)
        set_show_capture_notification(False, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_player = _FakeGstPlayer()
        monkeypatch.setattr("orcshot.capture.capture_feedback._get_player", lambda: fake_player)
        monkeypatch.setattr("orcshot.capture.capture_feedback.Gio.Application.get_default", lambda: None)

        play_capture_feedback()

        assert fake_player.states == []

    def test_shows_notification_when_enabled(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(False, path=config_path)
        set_show_capture_notification(True, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_app = _FakeApp()
        monkeypatch.setattr("orcshot.capture.capture_feedback.Gio.Application.get_default", lambda: fake_app)

        play_capture_feedback()

        assert len(fake_app.notifications) == 1
        assert fake_app.notifications[0][0] == "orcshot-capture-complete"

    def test_skips_notification_when_disabled(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(False, path=config_path)
        set_show_capture_notification(False, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_app = _FakeApp()
        monkeypatch.setattr("orcshot.capture.capture_feedback.Gio.Application.get_default", lambda: fake_app)

        play_capture_feedback()

        assert fake_app.notifications == []

    def test_skips_notification_when_no_application_running(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(False, path=config_path)
        set_show_capture_notification(True, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        monkeypatch.setattr("orcshot.capture.capture_feedback.Gio.Application.get_default", lambda: None)

        play_capture_feedback()  # must not raise


class TestPlayCaptureSoundOnly:
    """The standalone sound-only function - see capture_feedback.py's
    own module docstring for why this is called separately from a new
    GAction (app.py's "play-capture-sound"), triggered from inside the
    bundled Shell extension itself (task #158 follow-up: matching
    X11's own correct sound timing, not the Wayland Shell-native
    path's original after-the-choice timing)."""

    def test_plays_when_enabled(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(True, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_player = _FakeGstPlayer()
        monkeypatch.setattr("orcshot.capture.capture_feedback._get_player", lambda: fake_player)

        play_capture_sound()

        assert Gst.State.PLAYING in fake_player.states
        assert "camera-shutter.oga" in fake_player.properties["uri"]

    def test_skips_when_disabled(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(False, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_player = _FakeGstPlayer()
        monkeypatch.setattr("orcshot.capture.capture_feedback._get_player", lambda: fake_player)

        play_capture_sound()

        assert fake_player.states == []

    def test_does_not_touch_the_notification(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(True, path=config_path)
        set_show_capture_notification(True, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_player = _FakeGstPlayer()
        monkeypatch.setattr("orcshot.capture.capture_feedback._get_player", lambda: fake_player)
        fake_app = _FakeApp()
        monkeypatch.setattr("orcshot.capture.capture_feedback.Gio.Application.get_default", lambda: fake_app)

        play_capture_sound()

        assert fake_app.notifications == []


class TestGstUnavailable:
    """Gst's typelib is expected to be present on every channel this
    project ships (confirmed live, 2026-09-01: it's part of
    org.gnome.Platform//50's own base runtime, no manifest change
    needed - unlike GSound's real Flatpak gap this module used to work
    around). The import-time guard is kept anyway, defensively - the
    whole reason this module now uses GStreamer instead of GSound is a
    typelib assumption ("commonly present") turning out to be false
    for one channel, so this module doesn't repeat that mistake by
    assuming Gst can never be missing either.
    """

    def test_play_capture_sound_returns_cleanly_without_touching_the_player(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(True, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        monkeypatch.setattr(capture_feedback_mod, "Gst", None)
        monkeypatch.setattr(capture_feedback_mod, "_player", "sentinel-untouched")

        play_capture_sound()  # must not raise

        # _get_player() must have short-circuited on Gst is None and
        # never touched the (sentinel, deliberately-not-a-real-element)
        # module-level cache.
        assert capture_feedback_mod._player == "sentinel-untouched"


class TestShowCaptureCompleteNotificationOnly:
    def test_shows_when_enabled(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_show_capture_notification(True, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_app = _FakeApp()
        monkeypatch.setattr("orcshot.capture.capture_feedback.Gio.Application.get_default", lambda: fake_app)

        show_capture_complete_notification()

        assert len(fake_app.notifications) == 1

    def test_skips_when_disabled(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_show_capture_notification(False, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_app = _FakeApp()
        monkeypatch.setattr("orcshot.capture.capture_feedback.Gio.Application.get_default", lambda: fake_app)

        show_capture_complete_notification()

        assert fake_app.notifications == []

    def test_does_not_touch_the_sound(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(True, path=config_path)
        set_show_capture_notification(True, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_player = _FakeGstPlayer()
        monkeypatch.setattr("orcshot.capture.capture_feedback._get_player", lambda: fake_player)
        fake_app = _FakeApp()
        monkeypatch.setattr("orcshot.capture.capture_feedback.Gio.Application.get_default", lambda: fake_app)

        show_capture_complete_notification()

        assert fake_player.states == []
