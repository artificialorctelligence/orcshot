"""The second bus name, and the session that owns it (BACKLOG #225).

The extension talks to whoever owns a bus name it watches. The tray app
owns `org.orcshot.Orcshot`, so a headless process - which by decision #1
must not construct OrcshotApplication at all - cannot reach the extension
through it. The extension therefore watches a second name,
`org.orcshot.Orcshot.Headless`, and HeadlessShellSession is what owns it
for the few hundred milliseconds a capture takes.

This is scripts/ci-shell-roundtrip.py's own recipe promoted into the
package: own the name, export the action group, register the bridge on
it, wait for Hello, act, unown. That script has proven the recipe works
inside both the strict snap and the Flatpak sandbox, which is why it was
chosen over two plausible alternatives nothing had exercised.

No real bus here. Gio.bus_own_name and GLib.MainLoop are faked so the
three outcomes - Hello arrives, the name is lost, nothing answers - are
all reachable without a session bus, which CI does not have.
"""

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402
import pytest  # noqa: E402

from orcshot.capture import shell_bridge as bridge_module  # noqa: E402
from orcshot.capture.shell_bridge import (  # noqa: E402
    HEADLESS_ACTIONS_PATH,
    HEADLESS_BUS_NAME,
    HEADLESS_SHELL_OBJECT_PATH,
    SHELL_OBJECT_PATH,
    HeadlessSessionUnavailable,
    HeadlessShellSession,
    ShellBridge,
)


class FakeConnection:
    """Records what a real Gio.DBusConnection would have been asked to do."""

    def __init__(self):
        self.exported_groups = []
        self.registered_objects = []

    def export_action_group(self, path, group):
        self.exported_groups.append(path)

    def register_object(self, path, interface, handler):
        self.registered_objects.append(path)


class TestRegisterHonoursTheShellObjectPath:
    """register() has always taken an object_path it then ignored,
    hardcoding SHELL_OBJECT_PATH. A second bus name needs a second Shell
    object path, so the dead parameter becomes a real one.
    """

    def test_the_default_is_the_original_path_so_nothing_else_changes(self):
        connection = FakeConnection()

        ShellBridge().register(connection, "/org/orcshot/Orcshot", Gio.SimpleActionGroup())

        assert connection.registered_objects == [SHELL_OBJECT_PATH]

    def test_a_given_shell_object_path_is_used(self):
        connection = FakeConnection()

        ShellBridge().register(
            connection, HEADLESS_ACTIONS_PATH, Gio.SimpleActionGroup(),
            shell_object_path=HEADLESS_SHELL_OBJECT_PATH,
        )

        assert connection.registered_objects == [HEADLESS_SHELL_OBJECT_PATH]

    def test_the_action_is_still_added_when_there_is_no_connection(self):
        """The existing unit-test path: no bus, just the action."""
        group = Gio.SimpleActionGroup()

        ShellBridge().register(None, HEADLESS_ACTIONS_PATH, group)

        assert group.has_action("shell-request")


class TestTheHeadlessNameIsAChildOfTheAppId:
    def test_the_bus_name_is_under_the_app_id(self):
        """Deliberate: the Snap Store granted a dbus declaration for
        org.orcshot.Orcshot, and a child name is the shape most likely to
        satisfy the same naming criteria when a second slot is requested.
        """
        assert HEADLESS_BUS_NAME.startswith("org.orcshot.Orcshot")
        assert HEADLESS_BUS_NAME != "org.orcshot.Orcshot"

    def test_the_paths_match_the_bus_name_and_do_not_collide(self):
        assert HEADLESS_ACTIONS_PATH != "/org/orcshot/Orcshot"
        assert HEADLESS_SHELL_OBJECT_PATH != SHELL_OBJECT_PATH
        assert HEADLESS_SHELL_OBJECT_PATH.startswith(HEADLESS_ACTIONS_PATH)


class _FakeInvocation:
    def return_value(self, variant):
        pass


def _deliver_hello(bridge, capabilities):
    """Drive the real Hello path rather than reaching past it - the
    extension's Hello is an ordinary D-Bus method call, and this is the
    exact variant it sends.
    """
    bridge.handle_method_call(
        None, ":1.9", HEADLESS_SHELL_OBJECT_PATH, "org.orcshot.Orcshot.Shell", "Hello",
        GLib.Variant("(sas)", ["0.4.0", sorted(capabilities)]), _FakeInvocation(),
    )


@pytest.fixture
def fake_bus(monkeypatch):
    """Stands in for Gio.bus_own_name + GLib.MainLoop.

    `script` says what the bus does once the loop runs: "acquired" calls
    the bus-acquired callback then delivers Hello, "lost" calls the
    name-lost callback, "silent" does nothing so the timeout wins.
    """
    state = {"owned": None, "unowned": [], "script": "acquired", "capabilities": frozenset({"ping"})}

    def fake_own_name(bus_type, name, flags, on_acquired, on_name_acquired, on_lost):
        state["owned"] = name
        state["on_acquired"] = on_acquired
        state["on_lost"] = on_lost
        return 4242

    def fake_unown_name(owner_id):
        state["unowned"].append(owner_id)

    class FakeLoop:
        def __init__(self):
            self.quit_called = False

        def run(self):
            if state["script"] == "acquired":
                state["on_acquired"](FakeConnection(), state["owned"])
                _deliver_hello(state["bridge"], state["capabilities"])
            elif state["script"] == "lost":
                state["on_lost"](FakeConnection(), state["owned"])

        def quit(self):
            self.quit_called = True

    monkeypatch.setattr(bridge_module.Gio, "bus_own_name", fake_own_name)
    monkeypatch.setattr(bridge_module.Gio, "bus_unown_name", fake_unown_name)
    monkeypatch.setattr(bridge_module.GLib, "MainLoop", FakeLoop)
    monkeypatch.setattr(bridge_module.GLib, "timeout_add", lambda ms, cb: 99)
    monkeypatch.setattr(bridge_module.GLib, "source_remove", lambda sid: None)
    return state


class TestOpeningASession:
    def test_hello_hands_back_a_bridge_carrying_the_capabilities(self, fake_bus):
        fake_bus["capabilities"] = frozenset({"ping", "capture-rect-headless"})
        session = HeadlessShellSession()
        fake_bus["bridge"] = session.bridge

        bridge = session.open()

        assert bridge.has("capture-rect-headless")

    def test_it_owns_the_headless_name_not_the_main_one(self, fake_bus):
        session = HeadlessShellSession()
        fake_bus["bridge"] = session.bridge

        session.open()

        assert fake_bus["owned"] == HEADLESS_BUS_NAME

    def test_losing_the_name_is_refused_with_a_reason(self, fake_bus):
        fake_bus["script"] = "lost"
        session = HeadlessShellSession()
        fake_bus["bridge"] = session.bridge

        with pytest.raises(HeadlessSessionUnavailable, match="name"):
            session.open()

    def test_no_hello_at_all_is_refused_with_a_different_reason(self, fake_bus):
        """Not a GNOME session, or the extension is not installed or not
        enabled. Distinct from losing the name, because the fix differs.
        """
        fake_bus["script"] = "silent"
        session = HeadlessShellSession()
        fake_bus["bridge"] = session.bridge

        with pytest.raises(HeadlessSessionUnavailable, match="Hello|extension"):
            session.open()


class TestClosingASession:
    def test_close_unowns_the_name(self, fake_bus):
        session = HeadlessShellSession()
        fake_bus["bridge"] = session.bridge
        session.open()

        session.close()

        assert fake_bus["unowned"] == [4242]

    def test_close_is_safe_when_open_never_succeeded(self, fake_bus):
        """A caller closing in a finally must not raise over the original
        failure and hide it.
        """
        fake_bus["script"] = "lost"
        session = HeadlessShellSession()
        fake_bus["bridge"] = session.bridge
        with pytest.raises(HeadlessSessionUnavailable):
            session.open()

        session.close()

    @pytest.mark.parametrize("script", ["lost", "silent"])
    def test_a_failed_open_unowns_the_name_itself(self, fake_bus, script):
        """open() takes the name before it can discover either failure,
        so it has to give it back on the way out. Leaving that to the
        caller's finally would be enough for the two callers that exist -
        but a name held by a process that already gave up is exactly what
        makes the *next* headless capture fail with "another headless
        capture may be running".
        """
        fake_bus["script"] = script
        session = HeadlessShellSession()
        fake_bus["bridge"] = session.bridge

        with pytest.raises(HeadlessSessionUnavailable):
            session.open()

        assert fake_bus["unowned"] == [4242]

    def test_closing_after_a_failed_open_does_not_unown_twice(self, fake_bus):
        """Both callers close in a finally regardless, so the second
        attempt must be a no-op rather than a double unown.
        """
        fake_bus["script"] = "lost"
        session = HeadlessShellSession()
        fake_bus["bridge"] = session.bridge
        with pytest.raises(HeadlessSessionUnavailable):
            session.open()

        session.close()

        assert fake_bus["unowned"] == [4242]
