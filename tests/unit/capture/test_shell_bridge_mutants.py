"""The parts of the extension contract that test_shell_bridge.py executes
but does not pin down (BACKLOG #220, task 9: 88 surviving mutants, 67% TCE).

shell_bridge.py is one half of a contract with a separately-shipped
component - the GNOME Shell extension - and the Snap Store granted a
`dbus` slot declaration for exactly the names in it (forum thread 53283,
2026-09-17). A silently wrong object path, interface name, method name or
D-Bus argument type does not fail here; it fails on a user's Wayland
session, as "capture does nothing". So the assertions below are mostly
about *exact names and exact D-Bus types*, not about control flow.

The same applies to the two stderr diagnostics: both exist because a
PyGObject D-Bus callback swallows exceptions, so a diagnostic that went to
stdout, or printed None, would be worse than useless during a live
extension bring-up.

No bus of any kind. handle_method_call is driven directly with a fake
invocation, register() is given a fake connection that only records what
it was asked to export, and the only real GLib machinery used is a
SimpleActionGroup and a main loop.
"""

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib
import pytest

from orcshot.capture import shell_bridge
from orcshot.capture.shell_bridge import (
    REQUEST_ACTION,
    SHELL_INTERFACE,
    SHELL_OBJECT_PATH,
    ShellBridge,
    ShellRequestError,
    ShellUnavailable,
    _from_unpacked,
    _to_variant,
    get_bridge,
    set_bridge,
)

IFACE = "org.orcshot.Orcshot.Shell"
PATH = "/org/orcshot/Orcshot/Shell"


# Copied from test_shell_bridge.py rather than imported - pytest's
# importlib mode forbids test modules importing each other.
class FakeInvocation:
    def __init__(self):
        self.value = None
        self.error = None

    def return_value(self, variant):
        self.value = variant.unpack() if variant is not None else ()

    def return_dbus_error(self, name, message):
        self.error = (name, message)


class FakeConnection:
    """Records register_object's arguments. The real call is what exports
    the object the extension dials; nothing else about a connection is
    used by register()."""

    def __init__(self):
        self.calls = []

    def register_object(self, *args):
        self.calls.append(args)
        return 1


def make_bridge():
    bridge = ShellBridge()
    group = Gio.SimpleActionGroup()
    bridge.register(connection=None, object_path="/org/orcshot/Orcshot", action_map=group)
    return bridge, group


def call(bridge, method, variant):
    inv = FakeInvocation()
    bridge.handle_method_call(None, ":1.9", PATH, IFACE, method, variant, inv)
    return inv


def hello(bridge, *capabilities):
    return call(bridge, "Hello", GLib.Variant("(sas)", ("0.4.0", list(capabilities))))


class TestRequestParameterTypes:
    """_to_variant is the outbound half of the wire format: every request
    parameter the app puts in GetRequest's a{sv} reply is typed here, and
    the extension's JS reads those variants by type. A wrong type
    signature is a runtime failure on the extension side, invisible to
    this process.
    """

    @pytest.mark.parametrize(
        "value, type_string, unpacked",
        [
            (True, "b", True),
            (7, "i", 7),
            (1.5, "d", 1.5),
            # 'ay' comes back as a list of ints on the PyGObject versions
            # this project ships on - see _from_unpacked's own comment.
            (b"\x89PNG", "ay", [137, 80, 78, 71]),
            (bytearray(b"\x89PNG"), "ay", [137, 80, 78, 71]),
            ("editor", "s", "editor"),
        ],
    )
    def test_each_parameter_type_gets_its_dbus_signature(self, value, type_string, unpacked):
        variant = _to_variant(value)

        assert variant.get_type_string() == type_string
        assert variant.unpack() == unpacked

    def test_a_bool_is_typed_as_a_bool_and_not_as_an_int(self):
        """isinstance(True, int) is True in Python, so the bool branch has
        to come first or every boolean request parameter would reach the
        extension as 'i'."""
        assert _to_variant(True).get_type_string() == "b"
        assert _to_variant(False).get_type_string() == "b"

    def test_an_unsupported_type_names_itself_in_the_error(self):
        """The message is the only thing that tells a developer which
        parameter they put in the request dict."""
        with pytest.raises(TypeError) as raised:
            _to_variant(["not", "supported"])

        assert str(raised.value) == "unsupported request parameter type: list"

    def test_a_request_parameter_survives_the_round_trip_to_get_request(self):
        bridge, _ = make_bridge()
        hello(bridge, "capture-rect")
        bridge.request_async(
            "capture-rect",
            {"path": "/tmp/shot.png", "scale": 1.5, "cursor": True},
            on_result=lambda r: None,
            on_error=pytest.fail,
        )

        inv = call(bridge, "GetRequest", GLib.Variant("(u)", (1,)))

        assert inv.value == ({"kind": "capture-rect", "path": "/tmp/shot.png", "scale": 1.5, "cursor": True},)


class TestFromUnpacked:
    """The inbound half. Deliver's result values arrive unpacked, and an
    'ay' payload (PNG bytes, the whole point of Deliver carrying data)
    arrives as a list of ints that has to be told apart from a genuine
    list of numbers.
    """

    def test_a_byte_list_becomes_bytes_including_the_boundary_values(self):
        """0 and 255 are ordinary bytes in a PNG; a bound that excluded
        either would leave a real capture as a list of ints."""
        assert _from_unpacked([0, 137, 80, 255]) == b"\x00\x89P\xff"

    def test_a_number_list_outside_byte_range_stays_a_list(self):
        """Window geometry and monitor ids come back as 'ai'. 256 is not a
        byte, so the list must stay a list rather than being forced
        through bytes()."""
        assert _from_unpacked([1, 256]) == [1, 256]
        assert _from_unpacked([-1, 2]) == [-1, 2]

    def test_a_list_that_is_not_ints_stays_a_list(self):
        """Hello's capabilities and the window list arrive as 'as'. Both
        halves of the guard have to hold for every element, or a string
        list would be handed to bytes()."""
        assert _from_unpacked(["tray", "region-select"]) == ["tray", "region-select"]

    def test_an_empty_list_stays_a_list(self):
        assert _from_unpacked([]) == []


class TestInitialState:
    def test_no_extension_has_said_hello_yet(self):
        bridge, _ = make_bridge()

        assert bridge.version_name is None
        assert bridge.capabilities == frozenset()

    def test_the_first_request_id_is_one_so_zero_can_mean_no_request(self):
        """The action's state starts at 0 and the extension treats a state
        change as "there is a request with this id" - so 0 must never be a
        real id."""
        bridge, group = make_bridge()
        hello(bridge, "ping")

        assert group.get_action_state(REQUEST_ACTION).unpack() == 0

        rid = bridge.request_async("ping", {}, on_result=lambda r: None, on_error=lambda e: None)

        assert rid == 1

    def test_the_request_action_is_the_name_and_type_the_extension_watches(self):
        _bridge, group = make_bridge()
        action = group.lookup_action(REQUEST_ACTION)

        assert action is not None
        assert action.get_state().get_type_string() == "u"
        assert action.get_parameter_type().dup_string() == "u"


class TestRegister:
    def test_it_exports_the_shell_object_the_extension_dials(self):
        """The path, the interface name and all three method names are the
        contract the Snap dbus declaration was granted for; every one of
        them is also hard-coded in the extension's JS."""
        bridge = ShellBridge()
        connection = FakeConnection()

        bridge.register(connection, "/org/orcshot/Orcshot", Gio.SimpleActionGroup())

        assert len(connection.calls) == 1
        args = connection.calls[0]
        assert len(args) == 3
        path, interface_info, handler = args
        assert path == SHELL_OBJECT_PATH == "/org/orcshot/Orcshot/Shell"
        assert interface_info is not None
        assert interface_info.name == SHELL_INTERFACE == "org.orcshot.Orcshot.Shell"
        assert handler == bridge.handle_method_call
        signatures = {
            method.name: ([a.signature for a in method.in_args], [a.signature for a in method.out_args])
            for method in interface_info.methods
        }
        assert signatures == {
            "Hello": (["s", "as"], []),
            "GetRequest": (["u"], ["a{sv}"]),
            "Deliver": (["u", "a{sv}"], []),
        }

    def test_without_a_connection_the_action_is_still_added(self):
        """The unit-test path, and also the pre-bus phase of startup."""
        bridge = ShellBridge()
        group = Gio.SimpleActionGroup()

        bridge.register(None, "/org/orcshot/Orcshot", group)

        assert group.lookup_action(REQUEST_ACTION) is not None


class TestUnavailableMessages:
    def test_a_missing_capability_names_the_kind_and_what_is_available(self):
        """Callers fall back to the portal path on this error; the message
        is what tells a developer whether the extension is old or absent."""
        bridge, _ = make_bridge()
        hello(bridge, "tray")

        with pytest.raises(ShellUnavailable) as raised:
            bridge.request_async("region-select", {}, on_result=pytest.fail, on_error=pytest.fail)

        message = str(raised.value)
        assert "region-select" in message
        assert "tray" in message

    def test_a_timeout_names_the_request_and_its_kind(self):
        bridge, _ = make_bridge()
        hello(bridge, "list-windows")

        with pytest.raises(ShellUnavailable) as raised:
            bridge.request("list-windows", timeout_ms=30)

        message = str(raised.value)
        assert "list-windows" in message
        assert "1" in message

    def test_a_timeout_for_an_already_answered_request_is_a_silent_no_op(self):
        """Deliver cancels the timeout source, but a source that already
        fired can still run its callback once. It must not raise out of a
        GLib callback, and it must not ask to be rescheduled."""
        bridge, _ = make_bridge()

        assert bridge._on_timeout(9999) is False

    def test_a_timed_request_records_the_source_id_deliver_will_cancel(self):
        """Deliver cancels the pending timeout by reading entry["timeout"].
        If request_async stored the source id anywhere else, the guard
        would read the None it was initialised with and the source would
        outlive the answered request."""
        bridge, _ = make_bridge()
        hello(bridge, "ping")
        results = []

        rid = bridge.request_async(
            "ping", {}, on_result=results.append, on_error=pytest.fail, timeout_ms=10_000
        )
        entry = bridge._pending[rid]

        assert isinstance(entry["timeout"], int) and entry["timeout"] > 0

        call(bridge, "Deliver", GLib.Variant("(ua{sv})", (rid, {"ok": GLib.Variant("b", True)})))

        assert results == [{"ok": True}]
        assert rid not in bridge._pending

    def test_a_request_without_a_timeout_has_no_source_to_cancel(self):
        bridge, _ = make_bridge()
        hello(bridge, "ping")

        rid = bridge.request_async("ping", {}, on_result=lambda r: None, on_error=pytest.fail)

        assert bridge._pending[rid]["timeout"] is None

    def test_the_blocking_form_defaults_to_a_five_second_timeout(self):
        """request() is the form the two former call_sync callers use
        (clipboard set, window list). Its default is the only thing
        standing between a missing Deliver and a hung nested main loop."""
        bridge, _ = make_bridge()
        hello(bridge, "ping")
        seen = {}

        def spy(kind, params, on_result, on_error, timeout_ms=None):
            seen["timeout_ms"] = timeout_ms
            GLib.idle_add(lambda: (on_result({"ok": True}), False)[1])
            return 1

        bridge.request_async = spy

        assert bridge.request("ping") == {"ok": True}
        assert seen["timeout_ms"] == 5000


class TestDeliverAndErrorReporting:
    def test_ok_false_without_an_error_field_still_says_what_happened(self):
        """The extension is allowed to answer {ok: false} with no detail;
        the fallback text is then the whole diagnostic."""
        bridge, _ = make_bridge()
        hello(bridge, "eyedropper")
        errors = []
        rid = bridge.request_async("eyedropper", {}, on_result=pytest.fail, on_error=errors.append)

        call(bridge, "Deliver", GLib.Variant("(ua{sv})", (rid, {"ok": GLib.Variant("b", False)})))

        assert len(errors) == 1
        assert isinstance(errors[0], ShellRequestError)
        assert str(errors[0]) == "Shell extension reported failure"

    def test_a_result_without_an_ok_field_is_treated_as_success(self):
        """The window-list and clipboard answers carry no "ok" - only a
        failure says so explicitly."""
        bridge, _ = make_bridge()
        hello(bridge, "list-windows")
        results = []
        rid = bridge.request_async("list-windows", {}, on_result=results.append, on_error=pytest.fail)

        call(bridge, "Deliver", GLib.Variant("(ua{sv})", (rid, {"windows": GLib.Variant("s", "[]")})))

        assert results == [{"windows": "[]"}]

    def test_get_request_for_an_unknown_id_returns_the_documented_error_name(self):
        """The extension matches on this error name to tell "the app
        forgot my request" apart from "the app is not there"."""
        bridge, _ = make_bridge()

        inv = call(bridge, "GetRequest", GLib.Variant("(u)", (42,)))

        assert inv.error == ("org.orcshot.Orcshot.Shell.UnknownRequest", "no pending request 42")
        assert inv.value is None

    def test_an_unknown_method_returns_the_standard_dbus_error(self):
        """A method name this app does not know means the extension is
        newer than the app; the reply has to be the well-known
        freedesktop name, which the extension's JS already handles."""
        bridge, _ = make_bridge()

        inv = call(bridge, "GetScreenshotNow", GLib.Variant("(u)", (1,)))

        assert inv.error == ("org.freedesktop.DBus.Error.UnknownMethod", "GetScreenshotNow")

    def test_deliver_for_an_unknown_id_says_so_on_stderr(self, capsys):
        """Dropped silently before this diagnostic existed. It is the only
        signal that the extension answered a request the app had already
        timed out - and it belongs on stderr, where the journal picks it
        up."""
        bridge, _ = make_bridge()

        inv = call(bridge, "Deliver", GLib.Variant("(ua{sv})", (999, {})))

        captured = capsys.readouterr()
        assert inv.error is None and inv.value == ()
        assert "[shell_bridge] Deliver for unknown request 999 dropped" in captured.err
        assert captured.out == ""

    def test_an_exception_inside_the_handler_is_reported_on_stderr(self, capsys):
        """PyGObject swallows an exception raised inside a D-Bus method
        callback. This print plus the traceback is the only reason a
        mismatched extension is debuggable at all, so it must carry the
        marker text, the traceback, and go to stderr."""
        bridge, _ = make_bridge()

        # A Hello with the wrong signature - what an extension built
        # against a different contract version would send.
        inv = call(bridge, "Hello", GLib.Variant("(s)", ("0.4.0",)))

        captured = capsys.readouterr()
        # The whole first line, not a substring of it: the marker is what
        # someone greps the journal for during a live extension bring-up.
        assert captured.err.splitlines()[0] == "[shell_bridge] exception in handle_method_call:"
        assert "Traceback" in captured.err
        assert captured.out == ""
        assert inv.value is None and inv.error is None
        assert bridge.version_name is None


class TestProcessBridge:
    def test_get_bridge_creates_one_bridge_and_keeps_returning_it(self):
        """Every caller reaches the bridge through this accessor, so a
        second instance would mean requests registered on a bridge the
        extension never talks to."""
        previous = shell_bridge._bridge
        try:
            set_bridge(None)

            first = get_bridge()

            assert isinstance(first, ShellBridge)
            assert get_bridge() is first
        finally:
            set_bridge(previous)

    def test_set_bridge_replaces_the_process_bridge(self):
        previous = shell_bridge._bridge
        try:
            replacement = ShellBridge()
            set_bridge(replacement)

            assert get_bridge() is replacement
        finally:
            set_bridge(previous)
