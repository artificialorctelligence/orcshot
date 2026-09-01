"""play_capture_feedback's own settings-gating logic - each half
(sound/notification) independently skips its external call when its
own preference is off. The external calls themselves (GSound audio
playback, a real desktop notification) are GLib/GTK glue with no
meaningful headless test - verified live instead, same precedent as
every other file under ui/ that talks to the real desktop.
"""

import orcshot.capture.capture_feedback as capture_feedback_mod
from orcshot.capture.capture_feedback import (
    play_capture_feedback, play_capture_sound, show_capture_complete_notification,
)
from orcshot.settings import set_play_capture_sound, set_show_capture_notification


class _FakeSoundContext:
    def __init__(self):
        self.played = []

    def play_simple(self, attrs, cancellable):
        self.played.append(attrs)


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
        fake_context = _FakeSoundContext()
        monkeypatch.setattr("orcshot.capture.capture_feedback._get_sound_context", lambda: fake_context)
        monkeypatch.setattr("orcshot.capture.capture_feedback.Gio.Application.get_default", lambda: None)

        play_capture_feedback()

        assert len(fake_context.played) == 1

    def test_skips_sound_when_disabled(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(False, path=config_path)
        set_show_capture_notification(False, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_context = _FakeSoundContext()
        monkeypatch.setattr("orcshot.capture.capture_feedback._get_sound_context", lambda: fake_context)
        monkeypatch.setattr("orcshot.capture.capture_feedback.Gio.Application.get_default", lambda: None)

        play_capture_feedback()

        assert fake_context.played == []

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
        fake_context = _FakeSoundContext()
        monkeypatch.setattr("orcshot.capture.capture_feedback._get_sound_context", lambda: fake_context)

        play_capture_sound()

        assert len(fake_context.played) == 1

    def test_skips_when_disabled(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(False, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_context = _FakeSoundContext()
        monkeypatch.setattr("orcshot.capture.capture_feedback._get_sound_context", lambda: fake_context)

        play_capture_sound()

        assert fake_context.played == []

    def test_does_not_touch_the_notification(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(True, path=config_path)
        set_show_capture_notification(True, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_context = _FakeSoundContext()
        monkeypatch.setattr("orcshot.capture.capture_feedback._get_sound_context", lambda: fake_context)
        fake_app = _FakeApp()
        monkeypatch.setattr("orcshot.capture.capture_feedback.Gio.Application.get_default", lambda: fake_app)

        play_capture_sound()

        assert fake_app.notifications == []


class TestGSoundUnavailable:
    """GSound's typelib is genuinely absent on some channels (Flatpak's
    org.gnome.Platform//50 - see this module's own docstring), which
    sets the module-level `GSound = None`. Nothing else in this test
    file exercises that branch of _get_sound_context/play_capture_sound
    (final-review Minor finding, 2026-08-31) - a future refactor could
    drop the guard entirely and this suite would stay green.
    """

    def test_play_capture_sound_returns_cleanly_without_touching_the_context(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(True, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        monkeypatch.setattr(capture_feedback_mod, "GSound", None)
        monkeypatch.setattr(capture_feedback_mod, "_sound_context", "sentinel-untouched")

        play_capture_sound()  # must not raise

        # _get_sound_context() must have short-circuited on GSound is
        # None and never touched the (sentinel, deliberately-not-a-real-
        # context) module-level cache.
        assert capture_feedback_mod._sound_context == "sentinel-untouched"


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
        fake_context = _FakeSoundContext()
        monkeypatch.setattr("orcshot.capture.capture_feedback._get_sound_context", lambda: fake_context)
        fake_app = _FakeApp()
        monkeypatch.setattr("orcshot.capture.capture_feedback.Gio.Application.get_default", lambda: fake_app)

        show_capture_complete_notification()

        assert fake_context.played == []
