"""Pure coverage for the app side of the extension contract (spec
2026-09-11 section 2). No bus: handle_method_call is driven directly with
fake invocations, and the action's state changes are observed on a real
Gio.SimpleAction held in a Gio.SimpleActionGroup (no export needed)."""

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib
import pytest

from orcshot.capture.shell_bridge import ShellBridge, ShellRequestError, ShellUnavailable

IFACE = "org.orcshot.Orcshot.Shell"
PATH = "/org/orcshot/Orcshot/Shell"


class FakeInvocation:
    def __init__(self):
        self.value = None
        self.error = None

    def return_value(self, variant):
        self.value = variant.unpack() if variant is not None else ()

    def return_dbus_error(self, name, message):
        self.error = (name, message)


def make_bridge():
    bridge = ShellBridge()
    group = Gio.SimpleActionGroup()
    bridge.register(connection=None, object_path="/org/orcshot/Orcshot", action_map=group)
    return bridge, group


def call(bridge, method, variant):
    inv = FakeInvocation()
    bridge.handle_method_call(None, ":1.9", PATH, IFACE, method, variant, inv)
    return inv


def test_hello_records_capabilities_and_version():
    bridge, _ = make_bridge()
    assert bridge.has("region-select") is False
    inv = call(bridge, "Hello", GLib.Variant("(sas)", ("0.4.0", ["tray", "region-select"])))
    assert inv.error is None
    assert bridge.capabilities == frozenset({"tray", "region-select"})
    assert bridge.version_name == "0.4.0"
    assert bridge.has("region-select") is True
    assert bridge.has("eyedropper") is False


def test_hello_notifies_subscribers():
    bridge, _ = make_bridge()
    seen = []
    bridge.on_capabilities_changed(seen.append)
    call(bridge, "Hello", GLib.Variant("(sas)", ("0.4.0", ["tray"])))
    assert seen == [frozenset({"tray"})]


def test_request_async_bumps_action_state_and_get_request_returns_params():
    bridge, group = make_bridge()
    call(bridge, "Hello", GLib.Variant("(sas)", ("0.4.0", ["capture-rect"])))
    results = []
    rid = bridge.request_async(
        "capture-rect", {"x": 1, "y": 2, "width": 30, "height": 40},
        on_result=results.append, on_error=pytest.fail,
    )
    assert group.get_action_state("shell-request").unpack() == rid
    inv = call(bridge, "GetRequest", GLib.Variant("(u)", (rid,)))
    assert inv.value == ({"kind": "capture-rect", "x": 1, "y": 2, "width": 30, "height": 40},)


def test_deliver_resolves_pending_request_with_result_dict():
    bridge, _ = make_bridge()
    call(bridge, "Hello", GLib.Variant("(sas)", ("0.4.0", ["capture-rect"])))
    results = []
    rid = bridge.request_async(
        "capture-rect", {"x": 0, "y": 0, "width": 1, "height": 1},
        on_result=results.append, on_error=pytest.fail,
    )
    payload = {
        "ok": GLib.Variant("b", True),
        "destination": GLib.Variant("s", "editor"),
        "pngBytes": GLib.Variant("ay", b"\x89PNG"),
    }
    inv = call(bridge, "Deliver", GLib.Variant("(ua{sv})", (rid, payload)))
    assert inv.error is None
    assert results == [{"ok": True, "destination": "editor", "pngBytes": b"\x89PNG"}]


def test_deliver_with_ok_false_calls_on_error():
    bridge, _ = make_bridge()
    call(bridge, "Hello", GLib.Variant("(sas)", ("0.4.0", ["eyedropper"])))
    errors = []
    rid = bridge.request_async("eyedropper", {}, on_result=pytest.fail, on_error=errors.append)
    payload = {"ok": GLib.Variant("b", False), "error": GLib.Variant("s", "cancelled")}
    call(bridge, "Deliver", GLib.Variant("(ua{sv})", (rid, payload)))
    assert len(errors) == 1
    assert isinstance(errors[0], ShellRequestError)
    assert "cancelled" in str(errors[0])


def test_deliver_unknown_id_is_dropped_not_an_error():
    bridge, _ = make_bridge()
    inv = call(bridge, "Deliver", GLib.Variant("(ua{sv})", (999, {})))
    assert inv.error is None and inv.value == ()


def test_get_request_unknown_id_returns_dbus_error():
    bridge, _ = make_bridge()
    inv = call(bridge, "GetRequest", GLib.Variant("(u)", (42,)))
    assert inv.error is not None


def test_request_async_without_capability_raises_unavailable():
    bridge, _ = make_bridge()
    with pytest.raises(ShellUnavailable):
        bridge.request_async("region-select", {}, on_result=pytest.fail, on_error=pytest.fail)


def test_request_sync_times_out_as_unavailable():
    bridge, _ = make_bridge()
    call(bridge, "Hello", GLib.Variant("(sas)", ("0.4.0", ["ping"])))
    with pytest.raises(ShellUnavailable):
        bridge.request("ping", timeout_ms=50)


def test_request_sync_returns_delivered_result():
    bridge, _ = make_bridge()
    call(bridge, "Hello", GLib.Variant("(sas)", ("0.4.0", ["list-windows"])))

    # Deliver from a timeout inside the nested loop, as the real extension would.
    def deliver_soon():
        rid = next(iter(bridge._pending))
        call(bridge, "Deliver", GLib.Variant("(ua{sv})", (rid, {"windows": GLib.Variant("s", "[]")})))
        return False

    GLib.timeout_add(10, deliver_soon)
    assert bridge.request("list-windows", timeout_ms=1000) == {"windows": "[]"}


def test_ids_are_unique_and_increasing():
    bridge, _ = make_bridge()
    call(bridge, "Hello", GLib.Variant("(sas)", ("0.4.0", ["ping"])))
    a = bridge.request_async("ping", {}, on_result=lambda r: None, on_error=lambda e: None)
    b = bridge.request_async("ping", {}, on_result=lambda r: None, on_error=lambda e: None)
    assert b == a + 1
