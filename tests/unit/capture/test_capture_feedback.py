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


class _FakeNotification:
    """Gio.Notification has setters but no getters, so the only way to
    assert the title/body/icon the user actually sees is to stand in for
    the whole Gio namespace (below) and record them. Task 9 (BACKLOG
    #220): every one of those three strings was unasserted."""

    def __init__(self, title):
        self.title = title
        self.body = None
        self.icon = None

    def set_body(self, body):
        self.body = body

    def set_icon(self, icon):
        self.icon = icon


class _FakeThemedIcon:
    def __init__(self, name):
        self.name = name


class _FakeGio:
    """Only the four Gio entry points show_capture_complete_notification
    touches."""

    def __init__(self, app):
        fake_gio = self

        class Application:
            @staticmethod
            def get_default():
                return app

        class Notification:
            @staticmethod
            def new(title):
                fake_gio.notification = _FakeNotification(title)
                return fake_gio.notification

        class ThemedIcon:
            @staticmethod
            def new(name):
                return _FakeThemedIcon(name)

        self.notification = None
        self.Application = Application
        self.Notification = Notification
        self.ThemedIcon = ThemedIcon


class _FakeGst:
    """Stands in for the whole Gst namespace _get_player() uses, recording
    the init and the element it was asked to build. State is a passthrough
    to the real enum so callers can still compare against Gst.State.NULL."""

    State = Gst.State

    def __init__(self, element="fake-playbin-element"):
        self.init_calls = []
        self.make_calls = []
        self._element = element
        fake_gst = self

        class ElementFactory:
            @staticmethod
            def make(*args):
                fake_gst.make_calls.append(args)
                return fake_gst._element

        self.ElementFactory = ElementFactory

    def init(self, *args):
        self.init_calls.append(args)


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


class TestGetPlayer:
    """The lazily-built, module-cached playbin element. Task 9 (BACKLOG
    #220): nothing asserted that Gst was initialised exactly once, that
    the element was a `playbin`, or that the cache was a cache - a mutant
    could invert either guard and the suite stayed green while no sound
    ever played."""

    def test_initialises_gst_once_and_builds_a_playbin(self, monkeypatch):
        fake_gst = _FakeGst()
        monkeypatch.setattr(capture_feedback_mod, "Gst", fake_gst)
        monkeypatch.setattr(capture_feedback_mod, "_gst_initialized", False)
        monkeypatch.setattr(capture_feedback_mod, "_player", None)

        player = capture_feedback_mod._get_player()

        assert fake_gst.init_calls == [(None,)]
        # playbin is the element that decodes the bundled .oga and picks an
        # audio sink by itself; the second argument is only the element's
        # own name, but a None there is a real GStreamer API misuse.
        assert fake_gst.make_calls == [("playbin", "orcshot-capture-sound-player")]
        assert player == "fake-playbin-element"

    def test_reuses_the_cached_element_without_re_initialising(self, monkeypatch):
        fake_gst = _FakeGst()
        monkeypatch.setattr(capture_feedback_mod, "Gst", fake_gst)
        monkeypatch.setattr(capture_feedback_mod, "_gst_initialized", False)
        monkeypatch.setattr(capture_feedback_mod, "_player", None)

        first = capture_feedback_mod._get_player()
        second = capture_feedback_mod._get_player()

        assert second is first
        assert fake_gst.init_calls == [(None,)]
        assert len(fake_gst.make_calls) == 1


class TestSoundPipelineStates:
    def test_resets_the_pipeline_to_null_before_playing(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_play_capture_sound(True, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_player = _FakeGstPlayer()
        monkeypatch.setattr("orcshot.capture.capture_feedback._get_player", lambda: fake_player)

        play_capture_sound()

        # Exactly NULL then PLAYING, in that order: a still-PLAYING
        # pipeline from a rapid previous capture will not accept a new URI,
        # so dropping (or mis-typing) the NULL reset makes the second
        # shutter sound of a burst silent.
        assert fake_player.states == [Gst.State.NULL, Gst.State.PLAYING]


class TestNotificationContents:
    def test_sends_the_title_body_and_icon_the_user_actually_sees(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        set_show_capture_notification(True, path=config_path)
        monkeypatch.setattr("orcshot.settings.config_file_path", lambda: config_path)
        fake_app = _FakeApp()
        fake_gio = _FakeGio(fake_app)
        monkeypatch.setattr(capture_feedback_mod, "Gio", fake_gio)

        show_capture_complete_notification()

        (notification_id, notification), = fake_app.notifications
        assert notification_id == "orcshot-capture-complete"
        # The notification object built above is the one that gets sent -
        # not a None that would make the whole notification vanish.
        assert notification is fake_gio.notification
        assert notification.title == "Screenshot captured"
        assert notification.body == "Choose what to do with it."
        # "orcshot" is the real installed themed icon name (see
        # debian/orcshot.install's own icon paths); a wrong case here gets
        # no icon at all from the icon theme.
        assert notification.icon.name == "orcshot"
