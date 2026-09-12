"""The app side of Orcshot's GNOME Shell extension contract (spec:
docs/superpowers/specs/2026-09-11-snap-compliant-extension-delivery-design.md
section 2). The app never calls into the Shell. It asks by changing the
state of one stateful action, `shell-request` (its state is the latest
request id - the only outbound signal a strictly confined snap is
allowed, org.gtk.Actions.Changed), and the extension answers by calling
back into this object: GetRequest(id) for the parameters, Deliver(id,
result) with the outcome, and Hello(version_name, capabilities) whenever
it (re)connects. Proven live under both the strict snap and the Flatpak
sandbox on 2026-09-11 with zero denials.

Signals carry ids, methods carry data: image bytes never ride the
action state, only GetRequest/Deliver.
"""

from __future__ import annotations

import sys
import traceback
from typing import Callable

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

SHELL_OBJECT_PATH = "/org/orcshot/Orcshot/Shell"
SHELL_INTERFACE = "org.orcshot.Orcshot.Shell"
REQUEST_ACTION = "shell-request"


class ShellRequestError(RuntimeError):
    """The extension answered, and the answer is a failure (user
    cancelled, Shell-side exception)."""


class ShellUnavailable(ShellRequestError):
    """No extension has said Hello with this capability, or it never
    answered within the timeout - callers fall back to the portal path,
    exactly as they did for a failed org.gnome.Shell call before."""


def _to_variant(value) -> GLib.Variant:
    if isinstance(value, bool):
        return GLib.Variant("b", value)
    if isinstance(value, int):
        return GLib.Variant("i", value)
    if isinstance(value, float):
        return GLib.Variant("d", value)
    if isinstance(value, (bytes, bytearray)):
        return GLib.Variant("ay", bytes(value))
    if isinstance(value, str):
        return GLib.Variant("s", value)
    raise TypeError(f"unsupported request parameter type: {type(value).__name__}")


def _from_unpacked(value):
    # GLib.Variant('ay').unpack() yields a list of ints on the PyGObject
    # versions this project ships on; normalise to bytes so callers
    # never see the difference. An empty list stays a list - it can't
    # be told apart from an empty 'as', and no caller needs empty bytes.
    if isinstance(value, list) and value and all(isinstance(b, int) and 0 <= b < 256 for b in value):
        return bytes(value)
    return value


class ShellBridge:
    SHELL_IFACE_XML = f"""
    <node>
      <interface name="{SHELL_INTERFACE}">
        <method name="Hello">
          <arg type="s" name="version_name" direction="in"/>
          <arg type="as" name="capabilities" direction="in"/>
        </method>
        <method name="GetRequest">
          <arg type="u" name="id" direction="in"/>
          <arg type="a{{sv}}" name="request" direction="out"/>
        </method>
        <method name="Deliver">
          <arg type="u" name="id" direction="in"/>
          <arg type="a{{sv}}" name="result" direction="in"/>
        </method>
      </interface>
    </node>
    """

    def __init__(self) -> None:
        self.capabilities: frozenset[str] = frozenset()
        self.version_name: str | None = None
        self._pending: dict[int, dict] = {}
        self._next_id = 1
        self._listeners: list[Callable[[frozenset[str]], None]] = []
        self._action = Gio.SimpleAction.new_stateful(REQUEST_ACTION, GLib.VariantType("u"), GLib.Variant("u", 0))

    # -- wiring ---------------------------------------------------------

    def register(self, connection, object_path: str, action_map: Gio.ActionMap) -> None:
        """Adds the request action to the app's action map (GApplication
        exports it at /org/orcshot/Orcshot alongside the tray actions)
        and, when a connection is given, exports the Shell object.
        connection=None is the unit-test path: no bus, just the action."""
        action_map.add_action(self._action)
        if connection is not None:
            node_info = Gio.DBusNodeInfo.new_for_xml(self.SHELL_IFACE_XML)
            connection.register_object(SHELL_OBJECT_PATH, node_info.interfaces[0], self.handle_method_call)

    def on_capabilities_changed(self, callback: Callable[[frozenset[str]], None]) -> None:
        self._listeners.append(callback)

    def off_capabilities_changed(self, callback: Callable[[frozenset[str]], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def has(self, kind: str) -> bool:
        return kind in self.capabilities

    # -- requests ---------------------------------------------------------

    def request_async(self, kind: str, params: dict, on_result, on_error, timeout_ms: int | None = None) -> int:
        if not self.has(kind):
            raise ShellUnavailable(f"no Shell extension capability {kind!r} (capabilities: {sorted(self.capabilities)})")
        rid = self._next_id
        self._next_id += 1
        entry = {"kind": kind, "params": dict(params), "on_result": on_result, "on_error": on_error, "timeout": None}
        if timeout_ms is not None:
            entry["timeout"] = GLib.timeout_add(timeout_ms, self._on_timeout, rid)
        self._pending[rid] = entry
        self._action.set_state(GLib.Variant("u", rid))
        return rid

    def request(self, kind: str, params: dict | None = None, timeout_ms: int = 5000) -> dict:
        """Blocking form for the two callers that were call_sync before
        (clipboard set, window list). Spins a nested main loop: Deliver
        is an incoming call on this process's own connection, which only
        the main loop can service - a plain wait would deadlock."""
        loop = GLib.MainLoop()
        box: dict = {}

        def done(result):
            box["result"] = result
            loop.quit()

        def failed(error):
            box["error"] = error
            loop.quit()

        self.request_async(kind, params or {}, done, failed, timeout_ms=timeout_ms)
        loop.run()
        if "error" in box:
            raise box["error"]
        return box["result"]

    def _on_timeout(self, rid: int) -> bool:
        entry = self._pending.pop(rid, None)
        if entry is not None:
            entry["timeout"] = None
            entry["on_error"](ShellUnavailable(f"Shell extension did not answer request {rid} ({entry['kind']})"))
        return False

    # -- the extension's calls --------------------------------------------

    def handle_method_call(self, connection, sender, path, iface, method, params: GLib.Variant, invocation) -> None:
        try:
            if method == "Hello":
                version_name, capabilities = params.unpack()
                self.version_name = version_name
                self.capabilities = frozenset(capabilities)
                for listener in list(self._listeners):
                    listener(self.capabilities)
                invocation.return_value(None)
            elif method == "GetRequest":
                (rid,) = params.unpack()
                entry = self._pending.get(rid)
                if entry is None:
                    invocation.return_dbus_error("org.orcshot.Orcshot.Shell.UnknownRequest", f"no pending request {rid}")
                    return
                payload = {"kind": GLib.Variant("s", entry["kind"])}
                payload.update({k: _to_variant(v) for k, v in entry["params"].items()})
                invocation.return_value(GLib.Variant("(a{sv})", (payload,)))
            elif method == "Deliver":
                rid, result = params.unpack()
                entry = self._pending.pop(rid, None)
                invocation.return_value(None)
                if entry is None:
                    print(f"[shell_bridge] Deliver for unknown request {rid} dropped", file=sys.stderr)
                    return
                if entry["timeout"] is not None:
                    GLib.source_remove(entry["timeout"])
                result = {k: _from_unpacked(v) for k, v in result.items()}
                if result.get("ok", True) is False:
                    entry["on_error"](ShellRequestError(result.get("error", "Shell extension reported failure")))
                else:
                    entry["on_result"](result)
            else:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
        except Exception:
            # Same caveat as every PyGObject D-Bus callback in this
            # project: an exception here is otherwise swallowed silently.
            print("[shell_bridge] exception in handle_method_call:", file=sys.stderr, flush=True)
            traceback.print_exc()


_bridge: ShellBridge | None = None


def get_bridge() -> ShellBridge:
    global _bridge
    if _bridge is None:
        _bridge = ShellBridge()
    return _bridge


def set_bridge(bridge: ShellBridge | None) -> None:
    global _bridge
    _bridge = bridge
