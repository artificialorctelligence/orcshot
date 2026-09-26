"""app.py's command-line surface, startup wiring and tray/update logic,
asserted against a real OrcshotApplication that never claims a D-Bus
name.

**Why this file has to be careful.** OrcshotApplication's
application_id is ``org.orcshot.Orcshot`` - the single-instance name a
real installed Orcshot tray app owns on a developer machine, and the
name the Snap Store granted a slot declaration for. Claiming it from a
test would collide with that running app (the .deb tray app stealing
the bus name from a Flatpak launch is an already-observed failure mode
here). Confirmed live 2026-09-26 while writing this file: ``ListNames``
on this machine's session bus already returns ``org.orcshot.Orcshot``.

The seam, test-side only - nothing in ``src/`` was changed or given a
test hook: **``set_application_id(None)`` before registering.**
GApplication only requests a well-known name for a non-NULL
application_id; with NULL it registers as a non-unique application and
exports at an anonymous object path instead. So no name is requested at
all, let alone that one, and nothing is ever called on the running
instance. ``TestBusSafety`` pins that property.

Three GLib facts shape the fixtures below, all established by probing
before any test was written:

1. **Construction claims nothing.** ``get_is_registered()`` is False
   and ``get_dbus_connection()`` is None until ``register()``, so every
   plain method can be tested on a merely-constructed app.
2. **``do_startup`` needs registration.** ``Gtk.Application.do_startup
   (self)`` chained up on an unregistered app segfaults, so ``register
   ()`` is the only way to reach it - GApplication emits "startup" from
   ``g_application_register`` when it becomes the primary instance, no
   ``run()`` and no main loop needed.
3. **Only one app per process may register.** With a session bus
   present, the second anonymous registration fails with "An object is
   already exported for the interface org.gtk.Application at
   /org/gtk/Application/anonymous", and the first app is also
   permanently the default GApplication (``set_default(None)`` is
   rejected by PyGObject), so it can never be released. Hence exactly
   one module-scoped ``started_app``; everything else uses a fresh
   unregistered ``bare_app`` and calls the startup steps
   (``_register_tray_actions``, ``_export_tray_menu``,
   ``_check_shell_extension_health``) directly, which all work
   unregistered.

That one-registration limit is this task's seam ceiling: the
alternative-branch runs of ``do_startup`` itself (the Cinnamon XApp
icon, the tray-export failure path) and ``do_dbus_register`` would each
need their own registered app, and no seam in ``src/`` offers one.
Recorded in BACKLOG #220 rather than papered over with a production
hook added for tests.

``main()`` is never called through to ``run()``: the application class
it constructs is replaced.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"),
    reason="do_startup builds real Gtk widgets (tray menu colours, default icon) - needs a display (CI: xvfb-run)",
)

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from orcshot import app as appmod
from orcshot.app import (
    APPLICATION_ID,
    CAPTURE_ACTIVE_WINDOW_OPTION,
    CAPTURE_FULL_SCREEN_OPTION,
    CAPTURE_LAST_REGION_OPTION,
    CAPTURE_REGION_OPTION,
    CAPTURE_WINDOW_PICKER_OPTION,
    OrcshotApplication,
    _CAPTURE_CLI_FLAGS,
    _defer,
    _log_session_info,
    _rgba_to_color,
    main,
)
from orcshot.capture.wayland_portal import (
    PortalRequestCancelled,
    PortalRequestFailed,
    PortalRequestTimedOut,
)


# --------------------------------------------------------------------
# fakes and helpers
# --------------------------------------------------------------------


class FakeOptionsDict:
    """The ``get_options_dict()`` half of one Gio.ApplicationCommandLine:
    do_command_line only ever asks it ``contains(name)``."""

    def __init__(self, present):
        self._present = frozenset(present)

    def contains(self, name):
        return name in self._present


class FakeCommandLine:
    """Stands in for one Gio.ApplicationCommandLine.

    Used for every routing test but one, because GApplication parses its
    main options at most once per instance (``g_application_parse_
    command_line``'s own assertion - a second call segfaults) and only
    one instance per process may register. The one live-parsed case is
    ``TestFlagRouting`` below.
    """

    def __init__(self, options=(), arguments=("orcshot",)):
        self._options = options
        self._arguments = list(arguments)

    def get_options_dict(self):
        return FakeOptionsDict(self._options)

    def get_arguments(self):
        return list(self._arguments)


class FakeEditor:
    """An EditorWindow as app.py uses one: a modified flag, a
    save-prompt, and close(). Deliberately does *not* call back into
    unregister_editor_window the way a real editor's close does - the
    tests that care about that ordering drive it explicitly.
    """

    def __init__(self, is_modified=False):
        self.is_modified = is_modified
        self.prompts = []
        self.closed = False

    def prompt_save_for_restart(self, message):
        self.prompts.append(message)

    def close(self):
        self.closed = True


class FakeMessageDialog:
    """One Gtk.MessageDialog whose run() answers instead of blocking."""

    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.ran = False
        self.destroyed = False
        FakeMessageDialog.instances.append(self)

    def run(self):
        self.ran = True
        return Gtk.ResponseType.OK

    def destroy(self):
        self.destroyed = True


def _flush_idle():
    """Runs the pending main-loop iterations _defer's GLib.idle_add
    needs, without entering a loop that would never return."""
    context = GLib.MainContext.default()
    for _ in range(50):
        if not context.pending():
            return
        context.iteration(False)


def _neutralise_startup(monkeypatch):
    """Everything do_startup does that would leave this process or touch
    the developer's real desktop.

    maybe_run_first_run_setup is the important one: XDG_CONFIG_HOME is a
    fresh temp dir per suite (tests/conftest.py), so its "already ran"
    flag is unset and it would show a real modal dialog offering to
    write autostart and hotkey configuration.

    create_status_icon is the second: it claims org.x.StatusIcon.orcshot,
    which the real Cinnamon tray on a Cinnamon dev box already owns, and
    running_on_cinnamon reads XDG_CURRENT_DESKTOP - so on this machine
    the unpatched call really does fire.
    """
    monkeypatch.setattr(appmod, "maybe_run_first_run_setup", lambda *a, **k: None)
    monkeypatch.setattr(appmod, "maybe_seed_default_external_commands", lambda *a, **k: None)
    monkeypatch.setattr(appmod, "remove_legacy_autostart_entry", lambda *a, **k: None)
    monkeypatch.setattr(appmod, "running_on_cinnamon", lambda: False)
    monkeypatch.setattr(appmod, "create_status_icon", lambda _app: None)


def _capture_starters(monkeypatch):
    """Replaces the five module-level capture-launching functions with
    recorders. Asserting on these rather than on the OrcshotApplication
    methods that call them is deliberate: it pins which capture actually
    gets launched, which is the thing a mis-routed flag gets wrong.
    """
    launched = []

    def recorder(name):
        def launch(*args, **kwargs):
            launched.append((name, args, kwargs))

        return launch

    monkeypatch.setattr(appmod, "start_region_capture", recorder("region"))
    monkeypatch.setattr(appmod, "start_full_screen_capture", recorder("full_screen"))
    monkeypatch.setattr(appmod, "start_active_window_capture", recorder("active_window"))
    monkeypatch.setattr(appmod, "start_window_picker", recorder("window_picker"))
    monkeypatch.setattr(appmod, "start_last_region_capture", recorder("last_region"))
    return launched


def _unregistered_app():
    application = OrcshotApplication()
    # The seam. Asserted, not assumed: everything below depends on it.
    application.set_application_id(None)
    assert application.get_application_id() is None
    return application


@pytest.fixture
def bare_app(monkeypatch):
    """A fresh app per test, constructed but never registered - enough
    for every method that does not need do_startup to have run."""
    _neutralise_startup(monkeypatch)
    return _unregistered_app()


@pytest.fixture(scope="module")
def started_app():
    """The one registered app this process can have (see the module
    docstring). do_startup has really run on it.

    Shared across the tests that need it, so they must not leave state
    behind; the ones that mutate it say so.
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        _neutralise_startup(monkeypatch)
        application = _unregistered_app()
        application.register(None)
        yield application


@pytest.fixture
def cli_app(started_app):
    """started_app with the single-instance flag back at its
    just-launched value, so each do_command_line test starts from a
    known state."""
    started_app._has_activated_before = False
    return started_app


@pytest.fixture(autouse=True)
def _reset_dialog_instances():
    FakeMessageDialog.instances = []
    yield
    FakeMessageDialog.instances = []


# --------------------------------------------------------------------
# the safety property this whole file rests on
# --------------------------------------------------------------------


class TestBusSafety:
    def test_the_production_id_is_still_the_name_this_file_must_not_claim(self):
        # If this ever changes, the module docstring's whole premise
        # needs re-reading before the seam below can be trusted.
        assert APPLICATION_ID == "org.orcshot.Orcshot"

    def test_a_constructed_app_has_claimed_nothing_at_all(self, bare_app):
        assert bare_app.get_is_registered() is False
        assert bare_app.get_dbus_connection() is None

    def test_the_registered_test_app_requests_no_well_known_name(self, started_app):
        assert started_app.get_application_id() is None
        assert started_app.get_is_registered() is True
        assert started_app.get_is_remote() is False
        # With a NULL application_id there is no id to derive a name or
        # an object path from - GApplication exports anonymously, so
        # org.orcshot.Orcshot cannot have been requested.
        path = started_app.get_dbus_object_path()
        assert path is None or "/org/orcshot/" not in path


# --------------------------------------------------------------------
# module-level helpers
# --------------------------------------------------------------------


class TestRgbaToColor:
    def test_channels_scale_to_bytes_and_round(self):
        rgba = Gdk.RGBA(red=1.0, green=0.5, blue=0.0, alpha=1.0)
        assert _rgba_to_color(rgba) == (255, 128, 0, 255)

    def test_a_transparent_black_is_all_zero(self):
        assert _rgba_to_color(Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=0.0)) == (0, 0, 0, 0)


class TestLogSessionInfo:
    def test_wayland_names_the_shell_extension_path(self, monkeypatch, capsys):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
        _log_session_info()
        err = capsys.readouterr().err
        assert "session_type=wayland" in err
        assert "orcshot@orcshot.org" in err

    def test_x11_names_the_native_path(self, monkeypatch, capsys):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        _log_session_info()
        assert "X11-native capture path" in capsys.readouterr().err

    def test_an_unset_session_type_is_reported_as_unset_not_crashed(self, monkeypatch, capsys):
        monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
        monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
        _log_session_info()
        err = capsys.readouterr().err
        assert "session_type=<unset>" in err
        assert "desktop=<unset>" in err


class TestDefer:
    def test_the_action_does_not_run_synchronously(self):
        ran = []
        _defer(lambda: ran.append(True))
        assert ran == []

    def test_the_action_runs_on_the_next_main_loop_iteration(self):
        ran = []
        _defer(lambda: ran.append(True))
        _flush_idle()
        assert ran == [True]

    def test_it_runs_once_not_repeatedly(self):
        ran = []
        _defer(lambda: ran.append(True))
        _flush_idle()
        _flush_idle()
        assert ran == [True]


class TestCaptureCliFlags:
    """main() decides whether a launch is a hotkey relaunch by matching
    argv against this tuple, so its exact contents are behaviour, and
    they have to match hotkey_setup.py's own HotkeyBinding table."""

    def test_it_is_the_five_long_capture_flags_and_nothing_else(self):
        assert _CAPTURE_CLI_FLAGS == (
            "--capture-region",
            "--capture-full-screen",
            "--capture-active-window",
            "--capture-window-picker",
            "--capture-last-region",
        )


class TestUpdateCheckTiming:
    def test_the_first_check_waits_for_startup_to_finish(self):
        # Real Windows' UpdateService.cs delays 20s so the check doesn't
        # compete with the app's own startup/first-run dialog. Asserted
        # as a constant because do_startup schedules it, and only one
        # app per process can reach do_startup at all (module docstring).
        assert appmod._UPDATE_CHECK_STARTUP_DELAY_SECONDS == 20

    def test_the_recurring_poll_is_hourly(self):
        assert appmod._UPDATE_CHECK_POLL_INTERVAL_SECONDS == 3600


# --------------------------------------------------------------------
# the command-line surface
# --------------------------------------------------------------------


class TestFlagRouting:
    """do_command_line's dispatch: each flag reaches its own capture."""

    @pytest.mark.parametrize(
        "option,expected",
        [
            (CAPTURE_REGION_OPTION, "region"),
            (CAPTURE_FULL_SCREEN_OPTION, "full_screen"),
            (CAPTURE_ACTIVE_WINDOW_OPTION, "active_window"),
            (CAPTURE_WINDOW_PICKER_OPTION, "window_picker"),
            (CAPTURE_LAST_REGION_OPTION, "last_region"),
        ],
    )
    def test_each_capture_flag_launches_its_own_capture(self, cli_app, monkeypatch, option, expected):
        launched = _capture_starters(monkeypatch)
        assert cli_app.do_command_line(FakeCommandLine(options=(option,))) == 0
        assert [name for name, _a, _k in launched] == [expected]

    def test_a_cli_capture_defers_to_the_cursor_setting_unlike_a_tray_one(self, cli_app, monkeypatch):
        # start_region_capture's own docstring: hotkey/CLI invocations
        # pass the default True and let Preferences decide; every
        # tray-triggered capture hardcodes False.
        launched = _capture_starters(monkeypatch)
        cli_app.do_command_line(FakeCommandLine(options=(CAPTURE_REGION_OPTION,)))
        assert launched[0][2]["capture_mouse_cursor"] is True

    def test_a_bare_launch_starts_no_capture_at_all(self, cli_app, monkeypatch):
        launched = _capture_starters(monkeypatch)
        assert cli_app.do_command_line(FakeCommandLine()) == 0
        assert launched == []

    def test_region_wins_when_several_capture_flags_are_given_at_once(self, cli_app, monkeypatch):
        launched = _capture_starters(monkeypatch)
        cli_app.do_command_line(
            FakeCommandLine(options=(CAPTURE_LAST_REGION_OPTION, CAPTURE_FULL_SCREEN_OPTION, CAPTURE_REGION_OPTION))
        )
        assert [name for name, _a, _k in launched] == ["region"]

    def test_full_screen_wins_over_the_three_flags_after_it(self, cli_app, monkeypatch):
        launched = _capture_starters(monkeypatch)
        cli_app.do_command_line(
            FakeCommandLine(
                options=(CAPTURE_ACTIVE_WINDOW_OPTION, CAPTURE_WINDOW_PICKER_OPTION, CAPTURE_FULL_SCREEN_OPTION)
            )
        )
        assert [name for name, _a, _k in launched] == ["full_screen"]

    def test_active_window_wins_over_the_window_picker(self, cli_app, monkeypatch):
        launched = _capture_starters(monkeypatch)
        cli_app.do_command_line(FakeCommandLine(options=(CAPTURE_WINDOW_PICKER_OPTION, CAPTURE_ACTIVE_WINDOW_OPTION)))
        assert [name for name, _a, _k in launched] == ["active_window"]

    def test_the_window_picker_wins_over_repeat_last_region(self, cli_app, monkeypatch):
        launched = _capture_starters(monkeypatch)
        cli_app.do_command_line(FakeCommandLine(options=(CAPTURE_LAST_REGION_OPTION, CAPTURE_WINDOW_PICKER_OPTION)))
        assert [name for name, _a, _k in launched] == ["window_picker"]


class TestRealOptionParsing:
    """The one test that goes through GLib's own option parser, proving
    the add_main_option declarations in __init__ are real and match the
    names do_command_line checks for.

    Each case gets its own app because options are parsed at most once
    per instance, and the unknown-flag case is the only one that can
    have a *fresh* app: parsing fails before g_application_register is
    reached, so it needs no registration (and cannot get one - see the
    module docstring). The valid-flag case therefore has to spend
    started_app's single parse, and no other test may call
    do_local_command_line on it.
    """

    def test_an_unknown_flag_is_rejected_with_a_non_zero_status(self, bare_app, monkeypatch):
        launched = _capture_starters(monkeypatch)
        handled, _argv, status = Gio.Application.do_local_command_line(
            bare_app, ["orcshot", "--definitely-not-an-orcshot-flag"]
        )
        assert handled is True
        assert status != 0
        assert launched == []
        assert bare_app.get_is_registered() is False

    def test_the_real_parser_routes_capture_region_to_a_region_capture(self, started_app, monkeypatch):
        launched = _capture_starters(monkeypatch)
        handled, _argv, status = Gio.Application.do_local_command_line(started_app, ["orcshot", "--capture-region"])
        assert handled is True
        assert status == 0
        assert [name for name, _a, _k in launched] == ["region"]


class TestCommandLineFileArguments:
    def test_a_positional_argument_is_opened_as_a_file(self, cli_app, monkeypatch):
        # Task #129: `orcshot %u` from a file manager's Open With lands
        # here, routed through the same single-instance forwarding.
        opened = []
        monkeypatch.setattr(cli_app, "open_file", opened.append)
        assert cli_app.do_command_line(FakeCommandLine(arguments=("orcshot", "/tmp/one.orcshot"))) == 0
        assert opened == ["/tmp/one.orcshot"]

    def test_argv0_is_never_treated_as_a_file_to_open(self, cli_app, monkeypatch):
        opened = []
        monkeypatch.setattr(cli_app, "open_file", opened.append)
        cli_app.do_command_line(FakeCommandLine(arguments=("orcshot",)))
        assert opened == []

    def test_every_positional_argument_is_opened(self, cli_app, monkeypatch):
        opened = []
        monkeypatch.setattr(cli_app, "open_file", opened.append)
        cli_app.do_command_line(FakeCommandLine(arguments=("orcshot", "/tmp/a.orcshot", "/tmp/b.orcshot")))
        assert opened == ["/tmp/a.orcshot", "/tmp/b.orcshot"]

    def test_a_flag_shaped_leftover_argument_is_not_opened_as_a_file(self, cli_app, monkeypatch):
        opened = []
        monkeypatch.setattr(cli_app, "open_file", opened.append)
        cli_app.do_command_line(FakeCommandLine(arguments=("orcshot", "--something")))
        assert opened == []

    def test_a_capture_flag_wins_over_a_positional_argument(self, cli_app, monkeypatch):
        # The if/elif chain checks the options dict first, so a file
        # given alongside a capture flag is silently not opened. Pinned
        # as observed behaviour, not endorsed.
        opened = []
        launched = _capture_starters(monkeypatch)
        monkeypatch.setattr(cli_app, "open_file", opened.append)
        cli_app.do_command_line(
            FakeCommandLine(options=(CAPTURE_REGION_OPTION,), arguments=("orcshot", "/tmp/a.orcshot"))
        )
        assert [name for name, _a, _k in launched] == ["region"]
        assert opened == []


class TestAlreadyRunningNotification:
    """Task #161: the notification fires only for a bare invocation of
    an instance that was already running - not on the first one, and not
    for any branch that already does something visible. It used to fire
    on every single Print Screen press."""

    def test_the_first_bare_invocation_says_nothing(self, cli_app, monkeypatch):
        notified = []
        monkeypatch.setattr(cli_app, "_notify", lambda *a, **k: notified.append((a, k)))
        cli_app.do_command_line(FakeCommandLine())
        assert notified == []
        assert cli_app._has_activated_before is True

    def test_a_second_bare_invocation_says_orcshot_is_already_running(self, cli_app, monkeypatch):
        notified = []
        monkeypatch.setattr(cli_app, "_notify", lambda *a, **k: notified.append((a, k)))
        cli_app.do_command_line(FakeCommandLine())
        cli_app.do_command_line(FakeCommandLine())
        assert len(notified) == 1
        args, kwargs = notified[0]
        assert "already running" in args[0]
        # A distinct id, or an "already running" notice could silently
        # replace a real pending update one - see _notify's docstring.
        assert kwargs["notification_id"] == "orcshot-already-running"

    def test_a_capture_flag_on_an_already_running_instance_stays_silent(self, cli_app, monkeypatch):
        notified = []
        _capture_starters(monkeypatch)
        monkeypatch.setattr(cli_app, "_notify", lambda *a, **k: notified.append((a, k)))
        cli_app.do_command_line(FakeCommandLine())
        cli_app.do_command_line(FakeCommandLine(options=(CAPTURE_REGION_OPTION,)))
        assert notified == []

    def test_opening_a_file_on_an_already_running_instance_stays_silent(self, cli_app, monkeypatch):
        notified = []
        monkeypatch.setattr(cli_app, "_notify", lambda *a, **k: notified.append((a, k)))
        monkeypatch.setattr(cli_app, "open_file", lambda _path: None)
        cli_app.do_command_line(FakeCommandLine())
        cli_app.do_command_line(FakeCommandLine(arguments=("orcshot", "/tmp/a.orcshot")))
        assert notified == []


class TestOpenFile:
    def test_a_plain_path_is_opened(self, bare_app, monkeypatch):
        from orcshot.ui import editor_window

        opened = []
        monkeypatch.setattr(editor_window, "open_orcshot_file_in_new_window", opened.append)
        bare_app.open_file("/tmp/shot.orcshot")
        assert opened == ["/tmp/shot.orcshot"]

    def test_a_file_uri_is_converted_to_a_path_first(self, bare_app, monkeypatch):
        from orcshot.ui import editor_window

        opened = []
        monkeypatch.setattr(editor_window, "open_orcshot_file_in_new_window", opened.append)
        bare_app.open_file("file:///tmp/shot.orcshot")
        assert opened == ["/tmp/shot.orcshot"]

    def test_a_non_local_uri_opens_nothing(self, bare_app, monkeypatch):
        from orcshot.ui import editor_window

        opened = []
        monkeypatch.setattr(editor_window, "open_orcshot_file_in_new_window", opened.append)
        bare_app.open_file("http://example.invalid/shot.orcshot")
        assert opened == []


# --------------------------------------------------------------------
# startup wiring
# --------------------------------------------------------------------


class TestStartupWiring:
    """Asserted against the one app that really went through
    do_startup."""

    def test_every_action_the_tray_and_the_shell_extension_activate_exists(self, started_app):
        # These names are the contract with a *different* process (the
        # GNOME Shell extension activates them by name over
        # org.gtk.Actions) and with debian/orcshot.preinst, so renaming
        # one silently breaks something no Python caller mentions.
        assert set(started_app.list_actions()) >= {
            "tray-region",
            "tray-full_screen",
            "tray-active_window",
            "tray-window_picker",
            "tray-repeat_region",
            "tray-open-file",
            "tray-preferences",
            "tray-quit",
            "prepare-for-upgrade",
            "play-capture-sound",
            "open-uri",
        }

    def test_open_uri_takes_a_string_because_notifications_target_it(self, started_app):
        # Gio.Notification can only target a registered GAction, so the
        # click action of every notification goes through this one.
        assert started_app.lookup_action("open-uri").get_parameter_type().dup_string() == "s"

    def test_the_tray_menu_model_is_kept_alive_on_the_app(self, started_app):
        # Not cosmetic: a local variable here was a real, live-confirmed
        # bug - every GMenuModel client stayed at get_n_items() == 0
        # forever. See _export_tray_menu's own docstring.
        assert isinstance(started_app._tray_menu, Gio.Menu)
        assert started_app._tray_menu.get_n_items() > 0

    def test_no_xapp_status_icon_is_created_off_cinnamon(self, started_app):
        assert started_app._xapp_icon is None

    def test_the_default_window_icon_is_set_from_the_bundled_logo(self, started_app):
        assert Gtk.Window.get_default_icon_list()


class TestTrayActionRegistration:
    """_register_tray_actions on its own, on an unregistered app -
    add_action and lookup_action both work before registration, which is
    what lets these run per-test instead of sharing started_app."""

    def test_repeat_last_region_starts_disabled_because_nothing_is_captured_yet(self, bare_app):
        bare_app._register_tray_actions()
        assert bare_app.lookup_action("tray-repeat_region").get_enabled() is False

    def test_every_other_tray_action_starts_enabled(self, bare_app):
        bare_app._register_tray_actions()
        for name in ("tray-region", "tray-full_screen", "tray-active_window", "tray-window_picker"):
            assert bare_app.lookup_action(name).get_enabled() is True, name

    def test_recording_a_region_enables_repeat_last_region(self, bare_app):
        # Updating the action's own enabled property is the whole
        # mechanism - the Shell extension picks it up over
        # org.gtk.Actions and xapp_tray via a property binding.
        bare_app._register_tray_actions()
        action = bare_app.lookup_action("tray-repeat_region")
        assert action.get_enabled() is False
        bare_app._remember_region("the-rect")
        assert action.get_enabled() is True


class TestExportTrayMenu:
    def test_the_exported_menu_is_the_one_kept_on_the_app(self, bare_app, monkeypatch):
        from orcshot.capture import gnome_tray_export

        exported = []
        monkeypatch.setattr(gnome_tray_export, "export_tray_menu", lambda app, menu: exported.append((app, menu)))
        bare_app._export_tray_menu()
        assert exported == [(bare_app, bare_app._tray_menu)]

    def test_the_menu_is_built_in_four_sections(self, bare_app, monkeypatch):
        # 5 capture modes, then Open File, Preferences, Quit each alone -
        # the GMenu idiom for the three dividers X11's Gtk.Menu draws.
        from orcshot.capture import gnome_tray_export

        monkeypatch.setattr(gnome_tray_export, "export_tray_menu", lambda app, menu: None)
        bare_app._export_tray_menu()
        assert bare_app._tray_menu.get_n_items() == 4


class TestShellExtensionHealthCheck:
    def test_nothing_is_checked_outside_a_wayland_session(self, bare_app, monkeypatch):
        # Not installed/enabled at all is the ordinary state on X11, not
        # something to nag about.
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        bare_app._check_shell_extension_health()
        assert bare_app._shell_bridge._listeners == []

    def test_a_stale_cached_extension_copy_is_reported_when_the_shell_says_hello(self, bare_app, monkeypatch):
        # GNOME Shell caches an extension's JS for the whole login
        # session, so an upgrade leaves the old module running until
        # the user logs out. Hello arrives asynchronously, hence the
        # listener rather than a check at startup.
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        from orcshot import gnome_extension_setup

        monkeypatch.setattr(gnome_extension_setup, "bundled_version_name", lambda: "0.4.0")
        monkeypatch.setattr(gnome_extension_setup, "needs_relogin", lambda running, bundled: True)
        notified = []
        monkeypatch.setattr(bare_app, "_notify", lambda *a, **k: notified.append(a))
        bare_app._check_shell_extension_health()
        assert len(bare_app._shell_bridge._listeners) == 1
        listener = bare_app._shell_bridge._listeners[-1]
        try:
            listener(frozenset({"capture"}))
        finally:
            bare_app._shell_bridge.off_capabilities_changed(listener)
        assert "needs a restart" in notified[0][0]

    def test_an_up_to_date_extension_says_nothing(self, bare_app, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        from orcshot import gnome_extension_setup

        monkeypatch.setattr(gnome_extension_setup, "bundled_version_name", lambda: "0.4.0")
        monkeypatch.setattr(gnome_extension_setup, "needs_relogin", lambda running, bundled: False)
        notified = []
        monkeypatch.setattr(bare_app, "_notify", lambda *a, **k: notified.append(a))
        bare_app._check_shell_extension_health()
        listener = bare_app._shell_bridge._listeners[-1]
        try:
            listener(frozenset())
        finally:
            bare_app._shell_bridge.off_capabilities_changed(listener)
        assert notified == []


# --------------------------------------------------------------------
# tray actions and the capture entry points
# --------------------------------------------------------------------


class TestTrayActionHandlers:
    def test_there_is_exactly_one_handler_per_capture_mode(self, bare_app):
        # Keyed by the same mode strings icons.py's
        # capture_mode_icon_image() uses.
        assert set(bare_app._tray_action_handlers()) == {
            "region",
            "full_screen",
            "active_window",
            "window_picker",
            "repeat_region",
        }

    @pytest.mark.parametrize(
        "mode,expected",
        [
            ("region", "region"),
            ("full_screen", "full_screen"),
            ("active_window", "active_window"),
            ("window_picker", "window_picker"),
            ("repeat_region", "last_region"),
        ],
    )
    def test_each_handler_launches_its_own_capture_with_the_cursor_off(self, bare_app, monkeypatch, mode, expected):
        # Every tray-triggered capture hardcodes the cursor off: by the
        # time the tray was clicked the pointer is over the icon, not
        # the content (start_region_capture's docstring).
        launched = _capture_starters(monkeypatch)
        bare_app._tray_action_handlers()[mode]()
        assert [name for name, _a, _k in launched] == [expected]
        assert launched[0][2]["capture_mouse_cursor"] is False

    def test_the_default_single_click_action_is_a_region_capture(self, bare_app, monkeypatch):
        launched = _capture_starters(monkeypatch)
        bare_app.start_capture()
        assert [name for name, _a, _k in launched] == ["region"]
        assert launched[0][2]["capture_mouse_cursor"] is False


class TestTrayActionActivation:
    """Activating the GActions for real, which needs the registered
    app."""

    def test_activating_a_tray_action_defers_the_capture_off_the_signal_handler(self, started_app, monkeypatch):
        # Task #134: starting a capture synchronously from the menu
        # item's own activate handler baked a fragment of the
        # still-visible menu into the screenshot.
        launched = _capture_starters(monkeypatch)
        started_app.activate_action("tray-full_screen", None)
        assert launched == []
        _flush_idle()
        assert [name for name, _a, _k in launched] == ["full_screen"]

    def test_the_open_file_action_opens_the_file_chooser(self, started_app, monkeypatch):
        called = []
        monkeypatch.setattr(started_app, "open_file_from_tray", lambda: called.append(True))
        started_app.activate_action("tray-open-file", None)
        assert called == [True]

    def test_the_preferences_action_shows_preferences(self, started_app, monkeypatch):
        called = []
        monkeypatch.setattr(started_app, "show_preferences", lambda: called.append(True))
        started_app.activate_action("tray-preferences", None)
        assert called == [True]

    def test_the_quit_action_quits_and_hides_the_tray_button(self, started_app, monkeypatch):
        called = []
        monkeypatch.setattr(started_app, "_quit_and_hide_tray_button", lambda: called.append(True))
        started_app.activate_action("tray-quit", None)
        assert called == [True]

    def test_the_upgrade_action_is_the_one_debian_preinst_activates(self, started_app, monkeypatch):
        called = []
        monkeypatch.setattr(started_app, "prepare_for_upgrade", lambda: called.append(True))
        started_app.activate_action("prepare-for-upgrade", None)
        assert called == [True]


class TestCaptureEntryPoints:
    @pytest.mark.parametrize(
        "method,expected",
        [
            ("start_region_capture", "region"),
            ("start_full_screen_capture", "full_screen"),
            ("start_active_window_capture", "active_window"),
            ("start_window_picker", "window_picker"),
        ],
    )
    def test_each_capture_passes_remember_region_as_its_callback(self, bare_app, monkeypatch, method, expected):
        launched = _capture_starters(monkeypatch)
        getattr(bare_app, method)()
        assert [name for name, _a, _k in launched] == [expected]
        assert launched[0][2]["on_captured"] == bare_app._remember_region

    def test_repeating_the_last_region_passes_the_region_and_no_callback(self, bare_app, monkeypatch):
        # Deliberately not chained through _remember_region: the region
        # being repeated already *is* last_region.
        launched = _capture_starters(monkeypatch)
        bare_app.last_region = "the-rect"
        bare_app.start_last_region_capture()
        assert launched == [("last_region", ("the-rect",), {"capture_mouse_cursor": True})]

    @pytest.mark.parametrize(
        "method",
        [
            "start_region_capture",
            "start_full_screen_capture",
            "start_active_window_capture",
            "start_window_picker",
            "start_last_region_capture",
        ],
    )
    def test_no_capture_starts_while_something_holds_a_gtk_grab(self, bare_app, monkeypatch, method):
        # Task #138 follow-up, reproduced live: with a dialog holding a
        # process-wide GTK grab, a capture overlay appeared but never
        # received any pointer input at all.
        launched = _capture_starters(monkeypatch)
        grabber = Gtk.Window()
        grabber.grab_add()
        try:
            getattr(bare_app, method)()
        finally:
            grabber.grab_remove()
            grabber.destroy()
        assert launched == []

    def test_the_grabbing_window_is_presented_instead(self, bare_app):
        grabber = Gtk.Window()
        grabber.grab_add()
        try:
            assert bare_app._block_if_modal_dialog_open() is True
        finally:
            grabber.grab_remove()
            grabber.destroy()

    def test_nothing_blocks_when_no_grab_is_held(self, bare_app):
        assert bare_app._block_if_modal_dialog_open() is False


class TestRunCapture:
    def test_a_cancelled_portal_request_is_treated_as_a_plain_cancel(self, bare_app, monkeypatch):
        # Hitting Escape on the portal's permission dialog - the most
        # ordinary way to back out of a capture - used to crash the app.
        notified = []
        monkeypatch.setattr(bare_app, "_notify", lambda *a, **k: notified.append(a))

        def cancel():
            raise PortalRequestCancelled("escape")

        bare_app._run_capture(cancel)
        assert notified == []

    @pytest.mark.parametrize("error", [PortalRequestFailed, PortalRequestTimedOut])
    def test_a_real_portal_failure_is_surfaced_as_a_notification(self, bare_app, monkeypatch, error):
        notified = []
        monkeypatch.setattr(bare_app, "_notify", lambda *a, **k: notified.append(a))

        def fail():
            raise error("response_code=2")

        bare_app._run_capture(fail)
        assert len(notified) == 1
        assert "Screenshot failed" in notified[0][0]
        assert "response_code=2" in notified[0][1]

    def test_any_other_exception_is_not_swallowed(self, bare_app):
        def boom():
            raise ValueError("a real bug, not a portal state")

        with pytest.raises(ValueError):
            bare_app._run_capture(boom)


class TestRememberRegion:
    def test_the_last_region_is_recorded(self, bare_app):
        bare_app._remember_region("the-rect")
        assert bare_app.last_region == "the-rect"

    def test_recording_before_startup_does_not_crash_on_a_missing_action(self, bare_app):
        assert bare_app._tray_repeat_action is None
        bare_app._remember_region("the-rect")
        assert bare_app.last_region == "the-rect"


# --------------------------------------------------------------------
# editor bookkeeping, quit, upgrade and restart
# --------------------------------------------------------------------


class TestEditorRegistry:
    def test_there_is_no_topmost_editor_when_none_are_open(self, bare_app):
        assert bare_app.topmost_editor() is None

    def test_the_topmost_editor_is_the_most_recently_opened_one(self, bare_app):
        first, second = FakeEditor(), FakeEditor()
        bare_app.register_editor_window(first)
        bare_app.register_editor_window(second)
        assert bare_app.topmost_editor() is second

    def test_unregistering_the_top_editor_falls_back_to_the_one_below(self, bare_app):
        first, second = FakeEditor(), FakeEditor()
        bare_app.register_editor_window(first)
        bare_app.register_editor_window(second)
        bare_app.unregister_editor_window(second)
        assert bare_app.topmost_editor() is first

    def test_unregistering_an_editor_that_was_never_registered_is_a_no_op(self, bare_app):
        bare_app.register_editor_window(FakeEditor())
        bare_app.unregister_editor_window(FakeEditor())
        assert len(bare_app._open_editors) == 1

    def test_preferences_uses_the_topmost_editor_as_its_transient_parent(self, bare_app, monkeypatch):
        from orcshot.ui import editor_window

        parents = []
        monkeypatch.setattr(editor_window, "show_preferences_dialog", parents.append)
        editor = FakeEditor()
        bare_app.register_editor_window(editor)
        bare_app.show_preferences()
        assert parents == [editor]

    def test_preferences_opens_with_no_parent_when_no_editor_is_open(self, bare_app, monkeypatch):
        # The whole point of task #119: Preferences is reachable from
        # the tray with no editor open at all.
        from orcshot.ui import editor_window

        parents = []
        monkeypatch.setattr(editor_window, "show_preferences_dialog", parents.append)
        bare_app.show_preferences()
        assert parents == [None]

    def test_open_file_from_tray_uses_the_topmost_editor_as_its_transient_parent(self, bare_app, monkeypatch):
        from orcshot.ui import editor_window

        calls = []
        monkeypatch.setattr(
            editor_window, "choose_and_open_orcshot_file", lambda transient_for: calls.append(transient_for)
        )
        editor = FakeEditor()
        bare_app.register_editor_window(editor)
        bare_app.open_file_from_tray()
        assert calls == [editor]


class TestQuit:
    def test_quitting_writes_the_marker_that_swallows_the_next_hotkey_relaunch(self, bare_app, monkeypatch):
        # Task #150 follow-up: the process dying was never the missing
        # piece; the OS-level hotkeys relaunching it were.
        marked = []
        monkeypatch.setattr(appmod, "write_quit_marker", lambda: marked.append(True))
        monkeypatch.setattr(bare_app, "quit", lambda: None)
        bare_app._quit_and_hide_tray_button()
        assert marked == [True]

    def test_an_upgrade_driven_quit_leaves_no_marker_because_it_comes_back(self, bare_app, monkeypatch):
        marked = []
        monkeypatch.setattr(appmod, "write_quit_marker", lambda: marked.append(True))
        monkeypatch.setattr(bare_app, "quit", lambda: None)
        bare_app._quit_and_hide_tray_button(write_marker=False)
        assert marked == []

    def test_open_modal_dialogs_are_closed_before_quitting(self, bare_app, monkeypatch):
        # Task #169: Gtk.Dialog.run()'s nested main loop means quit()
        # alone did nothing at all with Preferences open.
        order = []
        monkeypatch.setattr(appmod, "write_quit_marker", lambda: None)
        monkeypatch.setattr(bare_app, "quit", lambda: order.append("quit"))
        monkeypatch.setattr(bare_app, "_close_open_modal_dialogs", lambda: order.append("closed"))
        bare_app._quit_and_hide_tray_button()
        assert order == ["closed", "quit"]

    def test_a_visible_dialog_is_forced_to_respond_cancel(self, bare_app):
        dialog = Gtk.Dialog()
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        responses = []
        dialog.connect("response", lambda _d, response: responses.append(response))
        dialog.show()
        try:
            bare_app._close_open_modal_dialogs()
        finally:
            dialog.destroy()
        assert responses == [Gtk.ResponseType.CANCEL]

    def test_a_hidden_dialog_is_left_alone(self, bare_app):
        dialog = Gtk.Dialog()
        responses = []
        dialog.connect("response", lambda _d, response: responses.append(response))
        try:
            bare_app._close_open_modal_dialogs()
        finally:
            dialog.destroy()
        assert responses == []


class TestPrepareForUpgrade:
    def test_an_unmodified_editor_is_just_closed(self, bare_app, monkeypatch):
        monkeypatch.setattr(bare_app, "_quit_and_hide_tray_button", lambda **kwargs: None)
        editor = FakeEditor(is_modified=False)
        bare_app.register_editor_window(editor)
        bare_app.prepare_for_upgrade()
        assert editor.closed is True
        assert editor.prompts == []

    def test_a_modified_editor_is_asked_to_save_first(self, bare_app):
        editor = FakeEditor(is_modified=True)
        bare_app.register_editor_window(editor)
        bare_app.prepare_for_upgrade()
        assert editor.closed is False
        assert editor.prompts == ["New install incoming — save your work"]

    def test_the_quit_waits_until_the_last_editor_is_gone(self, bare_app, monkeypatch):
        quits = []
        monkeypatch.setattr(bare_app, "_quit_and_hide_tray_button", lambda **kwargs: quits.append(kwargs))
        editor = FakeEditor(is_modified=True)
        bare_app.register_editor_window(editor)
        bare_app.prepare_for_upgrade()
        assert quits == []
        bare_app.unregister_editor_window(editor)
        # write_marker=False: a package upgrade is not the user asking
        # to stay quit until they restart - the point is that it returns.
        assert quits == [{"write_marker": False}]

    def test_with_no_editors_open_it_quits_straight_away(self, bare_app, monkeypatch):
        quits = []
        monkeypatch.setattr(bare_app, "_quit_and_hide_tray_button", lambda **kwargs: quits.append(kwargs))
        bare_app.prepare_for_upgrade()
        assert quits == [{"write_marker": False}]


class TestRestartForLanguageChange:
    def test_an_unmodified_editor_is_just_closed(self, bare_app):
        editor = FakeEditor(is_modified=False)
        bare_app.register_editor_window(editor)
        bare_app.restart_for_language_change()
        assert editor.closed is True
        assert editor.prompts == []

    def test_a_modified_editor_is_asked_to_save_before_the_restart(self, bare_app):
        editor = FakeEditor(is_modified=True)
        bare_app.register_editor_window(editor)
        bare_app.restart_for_language_change()
        assert editor.prompts == ["Restarting Orcshot — save your work"]

    def test_the_restart_is_a_non_zero_exit_for_systemd_to_pick_up(self, bare_app, capsys):
        # Not execv and not `systemctl --user restart` - both were tried
        # live and both lose to Type=dbus supervision. See
        # _maybe_restart_after_language_change's own docstring.
        with pytest.raises(SystemExit) as exit_info:
            bare_app.restart_for_language_change()
        assert exit_info.value.code == 1
        assert "restarting for a language change" in capsys.readouterr().out

    def test_the_exit_waits_until_the_last_editor_closes(self, bare_app):
        editor = FakeEditor(is_modified=True)
        bare_app.register_editor_window(editor)
        bare_app.restart_for_language_change()  # no SystemExit yet
        with pytest.raises(SystemExit):
            bare_app.unregister_editor_window(editor)

    def test_nothing_exits_when_no_restart_was_asked_for(self, bare_app):
        bare_app._maybe_restart_after_language_change()


# --------------------------------------------------------------------
# update checks
# --------------------------------------------------------------------


class TestUpdateCheckScheduling:
    def test_the_startup_delay_hands_over_to_a_recurring_poll_and_does_not_repeat(self, bare_app, monkeypatch):
        scheduled = []
        monkeypatch.setattr(appmod.GLib, "timeout_add_seconds", lambda s, cb: scheduled.append((s, cb)) or 1)
        monkeypatch.setattr(bare_app, "_run_update_check", lambda **kwargs: None)
        assert bare_app._start_periodic_update_checks() is False  # one-shot
        assert [seconds for seconds, _cb in scheduled] == [3600]

    def test_the_first_check_happens_as_soon_as_the_startup_delay_is_over(self, bare_app, monkeypatch):
        monkeypatch.setattr(appmod.GLib, "timeout_add_seconds", lambda s, cb: 1)
        checked = []
        monkeypatch.setattr(bare_app, "_run_update_check", lambda **kwargs: checked.append(kwargs))
        bare_app._start_periodic_update_checks()
        assert checked == [{"manual": False}]

    def test_each_poll_tick_keeps_the_timer_alive(self, bare_app, monkeypatch):
        checked = []
        monkeypatch.setattr(bare_app, "_run_update_check", lambda **kwargs: checked.append(kwargs))
        assert bare_app._periodic_update_check_tick() is True  # keep repeating
        assert checked == [{"manual": False}]


class TestRunUpdateCheck:
    @staticmethod
    def _no_real_thread(monkeypatch):
        started = []

        class FakeThread:
            def __init__(self, target, args, daemon):
                self.target = target
                self.args = args
                self.daemon = daemon

            def start(self):
                started.append((self.target, self.args, self.daemon))

        monkeypatch.setattr(appmod.threading, "Thread", lambda target, args, daemon: FakeThread(target, args, daemon))
        return started

    def test_a_background_check_that_is_not_due_yet_does_nothing(self, bare_app, monkeypatch):
        started = self._no_real_thread(monkeypatch)
        stamped = []
        monkeypatch.setattr(appmod, "should_check_now", lambda *a: False)
        monkeypatch.setattr(appmod, "set_last_update_check", stamped.append)
        bare_app._run_update_check(manual=False)
        assert started == []
        assert stamped == []

    def test_a_due_background_check_stamps_the_time_and_fetches_off_the_main_thread(self, bare_app, monkeypatch):
        started = self._no_real_thread(monkeypatch)
        stamped = []
        monkeypatch.setattr(appmod, "should_check_now", lambda *a: True)
        monkeypatch.setattr(appmod, "set_last_update_check", stamped.append)
        bare_app._run_update_check(manual=False)
        assert len(stamped) == 1
        assert len(started) == 1
        target, args, daemon = started[0]
        # urlopen() would otherwise block the GTK main loop.
        assert target == bare_app._fetch_and_report
        assert args == (False, None)
        assert daemon is True

    def test_a_manual_check_ignores_the_interval_entirely(self, bare_app, monkeypatch):
        # A manual click always reports back, either way - silence after
        # a deliberate click would look broken.
        started = self._no_real_thread(monkeypatch)
        monkeypatch.setattr(appmod, "should_check_now", lambda *a: pytest.fail("a manual check must not ask"))
        monkeypatch.setattr(appmod, "set_last_update_check", lambda _when: None)
        parent = Gtk.Window()
        try:
            bare_app.check_for_updates_now(parent)
        finally:
            parent.destroy()
        assert started[0][1] == (True, parent)

    def test_the_fetch_hands_its_result_back_to_the_main_thread(self, bare_app, monkeypatch):
        monkeypatch.setattr(appmod, "fetch_latest_release", lambda: ("v9.9.9", "http://example.invalid/r"))
        handed = []
        monkeypatch.setattr(appmod.GLib, "idle_add", lambda cb, *args: handed.append((cb, args)) or 1)
        bare_app._fetch_and_report(True, None)
        assert handed == [(bare_app._on_update_check_result, (("v9.9.9", "http://example.invalid/r"), True, None))]


class TestUpdateCheckResult:
    @pytest.fixture(autouse=True)
    def _fixed_installed_version(self, monkeypatch):
        monkeypatch.setattr(appmod, "installed_version", lambda _name: "0.3.0")
        monkeypatch.setattr(appmod.Gtk, "MessageDialog", FakeMessageDialog)

    def test_a_newer_release_is_offered_as_a_notification_with_its_download_uri(self, bare_app, monkeypatch):
        notified = []
        monkeypatch.setattr(bare_app, "_notify", lambda *a, **k: notified.append((a, k)))
        assert bare_app._on_update_check_result(("v0.4.0", "http://example.invalid/0.4.0"), False, None) is False
        assert len(notified) == 1
        args, kwargs = notified[0]
        assert "update available" in args[0]
        assert "0.4.0" in args[1]
        assert kwargs["uri"] == "http://example.invalid/0.4.0"

    def test_a_silent_background_check_that_finds_nothing_new_says_nothing(self, bare_app, monkeypatch):
        monkeypatch.setattr(bare_app, "_notify", lambda *a, **k: pytest.fail("no notification for no news"))
        bare_app._on_update_check_result(("v0.3.0", "http://example.invalid/0.3.0"), False, None)
        assert FakeMessageDialog.instances == []

    def test_a_manual_check_that_finds_nothing_new_still_reports_back(self, bare_app):
        bare_app._on_update_check_result(("v0.3.0", "http://example.invalid/0.3.0"), True, None)
        assert len(FakeMessageDialog.instances) == 1
        dialog = FakeMessageDialog.instances[0]
        assert "up to date" in dialog.kwargs["text"]
        assert "0.3.0" in dialog.kwargs["secondary_text"]
        assert dialog.ran is True
        assert dialog.destroyed is True

    def test_a_silent_background_check_that_fails_says_nothing(self, bare_app):
        assert bare_app._on_update_check_result(None, False, None) is False
        assert FakeMessageDialog.instances == []

    def test_a_manual_check_that_fails_says_so(self, bare_app):
        bare_app._on_update_check_result(None, True, None)
        assert len(FakeMessageDialog.instances) == 1
        dialog = FakeMessageDialog.instances[0]
        assert "Couldn't check for updates" in dialog.kwargs["text"]
        assert dialog.destroyed is True


class TestNotify:
    def test_a_notification_carries_the_body_and_a_stable_default_id(self, bare_app, monkeypatch):
        sent = []
        monkeypatch.setattr(bare_app, "send_notification", lambda nid, n: sent.append((nid, n)))
        bare_app._notify("Title", "Body")
        notification_id, notification = sent[0]
        # The default is the update notification's own id, so its
        # original call site did not have to change when a second
        # caller started sharing this method.
        assert notification_id == "orcshot-update-available"
        assert isinstance(notification, Gio.Notification)

    def test_a_uri_notification_uses_the_id_it_was_given(self, bare_app, monkeypatch):
        sent = []
        monkeypatch.setattr(bare_app, "send_notification", lambda nid, n: sent.append((nid, n)))
        bare_app._notify("Title", "Body", uri="http://example.invalid/x", notification_id="custom-id")
        assert sent[0][0] == "custom-id"

    def test_two_different_notifications_must_not_share_an_id(self, bare_app, monkeypatch):
        # _notify's docstring: a shared id would let an "already
        # running" notice silently replace a real pending update one.
        sent = []
        monkeypatch.setattr(bare_app, "send_notification", lambda nid, n: sent.append(nid))
        bare_app._notify("Update", "Body")
        bare_app._notify("Running", "Body", notification_id="orcshot-already-running")
        assert sent[0] != sent[1]


# --------------------------------------------------------------------
# main()
# --------------------------------------------------------------------


class FakeApplication:
    """Replaces OrcshotApplication inside main(): run() answers instead
    of entering Gtk's main loop, and there is no application_id to
    claim."""

    instances = []

    def __init__(self):
        self.argv = None
        FakeApplication.instances.append(self)

    def run(self, argv):
        self.argv = list(argv)
        return 0


@pytest.fixture
def fake_main(monkeypatch):
    FakeApplication.instances = []
    monkeypatch.setattr(appmod, "OrcshotApplication", FakeApplication)
    names = []
    monkeypatch.setattr(appmod.GLib, "set_prgname", names.append)
    cleared = []
    monkeypatch.setattr(appmod, "clear_quit_marker", lambda: cleared.append(True))
    return names, cleared


class TestMain:
    def test_the_process_name_is_set_explicitly_for_wm_class_matching(self, monkeypatch, fake_main):
        names, _cleared = fake_main
        monkeypatch.setattr(appmod, "is_quit_marker_set", lambda: False)
        monkeypatch.setattr(appmod.sys, "argv", ["orcshot"])
        main()
        # Must match debian/orcshot.desktop's StartupWMClass regardless
        # of how this entry point was invoked.
        assert names == ["orcshot"]

    def test_a_normal_launch_runs_the_application_with_argv(self, monkeypatch, fake_main):
        _names, cleared = fake_main
        monkeypatch.setattr(appmod, "is_quit_marker_set", lambda: False)
        monkeypatch.setattr(appmod.sys, "argv", ["orcshot", "--capture-region"])
        assert main() == 0
        assert len(FakeApplication.instances) == 1
        assert FakeApplication.instances[0].argv == ["orcshot", "--capture-region"]
        # Nothing to clear when no marker was set - quit_marker_path()
        # would otherwise stat on every single launch for no reason.
        assert cleared == []

    def test_a_capture_hotkey_after_an_explicit_quit_does_nothing_at_all(self, monkeypatch, fake_main):
        # Task #150: "it should not be running anymore... it should
        # remain this way until the user restarts." A capture-flag
        # invocation while the marker is set can only be a
        # hotkey-triggered relaunch.
        _names, cleared = fake_main
        monkeypatch.setattr(appmod, "is_quit_marker_set", lambda: True)
        monkeypatch.setattr(appmod.sys, "argv", ["orcshot", "--capture-full-screen"])
        assert main() == 0
        assert FakeApplication.instances == []
        # The marker stays, so the *next* hotkey press is swallowed too.
        assert cleared == []

    def test_a_bare_relaunch_after_a_quit_clears_the_marker_and_starts_up(self, monkeypatch, fake_main):
        _names, cleared = fake_main
        monkeypatch.setattr(appmod, "is_quit_marker_set", lambda: True)
        monkeypatch.setattr(appmod.sys, "argv", ["orcshot"])
        assert main() == 0
        assert cleared == [True]
        assert len(FakeApplication.instances) == 1

    def test_opening_a_file_after_a_quit_is_a_real_reopen_not_a_hotkey(self, monkeypatch, fake_main):
        _names, cleared = fake_main
        monkeypatch.setattr(appmod, "is_quit_marker_set", lambda: True)
        monkeypatch.setattr(appmod.sys, "argv", ["orcshot", "/tmp/shot.orcshot"])
        main()
        assert cleared == [True]
        assert len(FakeApplication.instances) == 1

    def test_a_non_capture_flag_after_a_quit_is_also_a_real_reopen(self, monkeypatch, fake_main):
        _names, cleared = fake_main
        monkeypatch.setattr(appmod, "is_quit_marker_set", lambda: True)
        monkeypatch.setattr(appmod.sys, "argv", ["orcshot", "--help"])
        main()
        assert cleared == [True]

    def test_main_returns_whatever_the_application_run_returns(self, monkeypatch, fake_main):
        monkeypatch.setattr(appmod, "is_quit_marker_set", lambda: False)
        monkeypatch.setattr(appmod.sys, "argv", ["orcshot"])

        class FailingApplication(FakeApplication):
            def run(self, argv):
                super().run(argv)
                return 7

        monkeypatch.setattr(appmod, "OrcshotApplication", FailingApplication)
        assert main() == 7
