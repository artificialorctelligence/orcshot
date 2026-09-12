# Snap-compliant Extension Delivery Implementation Plan

> **Amended 2026-09-12:** every Cinnamon Spices step (Task 8's `spices` leaf and `spices-sync.sh`,
> RELEASING.md step 4, Task 9 Step 2, the `flatpak-cinnamon` dialog) is withdrawn - BACKLOG #208
> replaces the Cinnamon applet with an app-owned `XApp.StatusIcon`. Kept below for the record.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the copy-into-home GNOME Shell extension install and the app→`org.gnome.Shell` call direction with one merged extension distributed through extensions.gnome.org (and the Cinnamon applet through Spices), where the extension calls *into* the app — so the snap passes store review and all three channels share one code path.

**Architecture:** The app owns `org.orcshot.Orcshot`, exports a stateful `shell-request` action (request ids only) and an `org.orcshot.Orcshot.Shell` object (`Hello` / `GetRequest` / `Deliver`). One extension `orcshot@orcshot.org` watches the action, fetches the request, runs the privileged work in the Shell, delivers the result by method call. First-run per channel only decides *how the extension gets installed*: `.deb` system-wide, Flatpak via GNOME's `InstallRemoteExtension`, Snap via an EGO redirect, Flatpak-on-Cinnamon via a Spices redirect.

**Tech Stack:** Python 3 / PyGObject (Gio, GLib, Gtk 3), GJS ES modules (GNOME Shell 45–50), pytest, snapcraft 9, flatpak-builder, GitHub Actions. Spec: `docs/superpowers/specs/2026-09-11-snap-compliant-extension-delivery-design.md`.

## Global Constraints

- The app never calls `org.gnome.Shell` or `org.gnome.Shell.Extensions` after Task 3, with one exception: the Flatpak first-run's `InstallRemoteExtension` call (Task 6).
- The extension exposes **nothing** on D-Bus. All calls are extension → app.
- Signals carry ids, methods carry data: the only outbound signal is the `shell-request` action's `u` state.
- `metadata.json`'s `version` field is EGO's; the app reads only `version-name`.
- Extension UUID: `orcshot@orcshot.org`. Bus name `org.orcshot.Orcshot`, action-group path `/org/orcshot/Orcshot`, Shell object path `/org/orcshot/Orcshot/Shell`, interface `org.orcshot.Orcshot.Shell`.
- Request kinds (exact strings): `region-select`, `window-picker`, `eyedropper`, `capture-rect`, `set-clipboard-image`, `list-windows`, `activate-window`, `ping`. Capability `tray` is reported but never requested.
- Nothing is written into the user's home by the app on any channel. `personal-files` never returns to `snapcraft.yaml`; `--filesystem=~/.local/share/gnome-shell/extensions` never returns to the Flatpak manifest.
- Every "works" claim cites a command and its output. VM access: memory file `project_orcshot_vm_access.md` (Ubuntu 26.04 = SSH port 2222 as `ubuntu2604`; Ubuntu2404 = port 2223 as `vboxuser`).
- Commit after every task; commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Tests: `.venv/bin/pytest tests/ -q` must stay green after each task. Do not run the suite in a way that rewrites `po/orcshot.pot` (BACKLOG #204 is resolved; `git status` must stay clean of it).

---

## File map

| Path | Responsibility | Task |
|---|---|---|
| `src/orcshot/capture/shell_bridge.py` (new) | App side of the contract: `shell-request` action, `org.orcshot.Orcshot.Shell` object, pending table, `has()`/`request()`/`request_async()` | 1 |
| `src/orcshot/app.py` | Registers the bridge in `do_dbus_register`; stale-copy health check via `version_name` | 2 |
| `src/orcshot/gnome_extension_setup.py` | Single UUID, `bundled_version_name()`, `needs_relogin()`; `enable_extension_live` deleted | 2 |
| `src/orcshot/capture/gnome_{clipboard,window_calls,region_select,window_picker,eyedropper,capture_rect}.py` | Same public API, plumbing swapped to the bridge | 3 |
| `src/orcshot/capture/backend_select.py` | Per-call capability checks | 3 |
| `src/orcshot/resources/gnome-shell-extensions/orcshot@orcshot.org/` (new; three old dirs deleted) | The merged extension: `extension.js`, `tray.js`, `capture.js`, `windows.js`, `metadata.json`, data | 4 |
| `debian/orcshot.install`, `THIRD_PARTY_NOTICES.md` | One extension directory | 4 |
| `src/orcshot/ui/first_run_setup.py`, `src/orcshot/channel_detect.py` | Per-channel install redirect; copy-into-home deleted | 5 |
| `snapcraft.yaml`, `org.orcshot.Orcshot.yaml`, `.github/workflows/snap.yml`, `scripts/pack-extension.sh` (new) | Packaging without the plug/grant; CI installs from the packed zip | 6 |
| VMs | Live regression pass, `review-tools` verdict | 7 |
| `.orclab/publish/channels.yaml`, `RELEASING.md`, `scripts/spices-sync.sh` (new), `VERIFICATION.md`, `BACKLOG.md` | Publishing pipeline and records | 8 |
| EGO account, Spices fork, Flathub manifest — user-gated | First submissions | 9 |

---

### Task 1: `shell_bridge.py` — the app side of the contract

**Files:**
- Create: `src/orcshot/capture/shell_bridge.py`
- Test: `tests/unit/capture/test_shell_bridge.py`

**Interfaces:**
- Produces:
  ```python
  class ShellRequestError(RuntimeError): ...
  class ShellUnavailable(ShellRequestError): ...      # no capability, no extension, or timeout

  class ShellBridge:
      SHELL_IFACE_XML: str
      def __init__(self) -> None
      def register(self, connection: Gio.DBusConnection, object_path: str, action_map: Gio.ActionMap) -> None
      capabilities: frozenset[str]        # empty until Hello
      version_name: str | None
      def has(self, kind: str) -> bool
      def on_capabilities_changed(self, callback: Callable[[frozenset[str]], None]) -> None
      def request_async(self, kind: str, params: dict, on_result: Callable[[dict], None], on_error: Callable[[Exception], None], timeout_ms: int | None = None) -> int
      def request(self, kind: str, params: dict | None = None, timeout_ms: int = 5000) -> dict
      def handle_method_call(self, connection, sender, path, iface, method, params: GLib.Variant, invocation) -> None

  def get_bridge() -> ShellBridge          # module singleton, created on first call
  def set_bridge(bridge: ShellBridge) -> None   # tests inject a fake
  ```
- `handle_method_call` is the raw Gio callback; tests call it with a fake `invocation` that records `return_value(variant)` / `return_dbus_error(name, msg)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/capture/test_shell_bridge.py
"""Pure coverage for the app side of the extension contract. No bus:
handle_method_call is driven directly with fake invocations, and the
action's state changes are observed on a real Gio.SimpleAction held in
a Gio.SimpleActionGroup (no export needed)."""
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
    rid = bridge.request_async("capture-rect", {"x": 1, "y": 2, "width": 30, "height": 40},
                               on_result=results.append, on_error=pytest.fail)
    assert group.get_action_state("shell-request").unpack() == rid
    inv = call(bridge, "GetRequest", GLib.Variant("(u)", (rid,)))
    assert inv.value == ({"kind": "capture-rect", "x": 1, "y": 2, "width": 30, "height": 40},)


def test_deliver_resolves_pending_request_with_result_dict():
    bridge, _ = make_bridge()
    call(bridge, "Hello", GLib.Variant("(sas)", ("0.4.0", ["capture-rect"])))
    results = []
    rid = bridge.request_async("capture-rect", {"x": 0, "y": 0, "width": 1, "height": 1},
                               on_result=results.append, on_error=pytest.fail)
    payload = GLib.Variant("a{sv}", {"ok": GLib.Variant("b", True), "destination": GLib.Variant("s", "editor"),
                                      "pngBytes": GLib.Variant("ay", b"\x89PNG")})
    inv = call(bridge, "Deliver", GLib.Variant("(ua{sv})", (rid, payload)))
    assert inv.error is None
    assert results == [{"ok": True, "destination": "editor", "pngBytes": b"\x89PNG"}]


def test_deliver_with_ok_false_calls_on_error():
    bridge, _ = make_bridge()
    call(bridge, "Hello", GLib.Variant("(sas)", ("0.4.0", ["eyedropper"])))
    errors = []
    rid = bridge.request_async("eyedropper", {}, on_result=pytest.fail, on_error=errors.append)
    payload = GLib.Variant("a{sv}", {"ok": GLib.Variant("b", False), "error": GLib.Variant("s", "cancelled")})
    call(bridge, "Deliver", GLib.Variant("(ua{sv})", (rid, payload)))
    assert len(errors) == 1 and isinstance(errors[0], ShellRequestError) and "cancelled" in str(errors[0])


def test_deliver_unknown_id_is_dropped_not_an_error():
    bridge, _ = make_bridge()
    inv = call(bridge, "Deliver", GLib.Variant("(ua{sv})", (999, GLib.Variant("a{sv}", {}))))
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
        call(bridge, "Deliver", GLib.Variant("(ua{sv})", (rid, GLib.Variant("a{sv}", {"windows": GLib.Variant("s", "[]")}))))
        return False
    GLib.timeout_add(10, deliver_soon)
    assert bridge.request("list-windows", timeout_ms=1000) == {"windows": "[]"}


def test_ids_are_unique_and_increasing():
    bridge, _ = make_bridge()
    call(bridge, "Hello", GLib.Variant("(sas)", ("0.4.0", ["ping"])))
    a = bridge.request_async("ping", {}, on_result=lambda r: None, on_error=lambda e: None)
    b = bridge.request_async("ping", {}, on_result=lambda r: None, on_error=lambda e: None)
    assert b == a + 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/capture/test_shell_bridge.py -q`
Expected: `ModuleNotFoundError: No module named 'orcshot.capture.shell_bridge'`

- [ ] **Step 3: Write the module**

```python
# src/orcshot/capture/shell_bridge.py
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
    # never see the difference.
    if isinstance(value, list) and value and all(isinstance(b, int) and 0 <= b < 256 for b in value):
        return bytes(value)
    if isinstance(value, list) and value == []:
        return value
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/capture/test_shell_bridge.py -q`
Expected: `11 passed`. If `test_deliver_resolves_pending_request_with_result_dict` fails on `pngBytes` being a list, extend `_from_unpacked` — that assertion is the whole point of it.

- [ ] **Step 5: Commit**

```bash
git add src/orcshot/capture/shell_bridge.py tests/unit/capture/test_shell_bridge.py
git commit -m "Add shell_bridge: the app side of the inverted extension contract (#205)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Wire the bridge into the app; single UUID; stale-copy check by version-name

**Files:**
- Modify: `src/orcshot/app.py:168-300` (`__init__`, `do_dbus_register`, `_check_shell_extension_health`)
- Modify: `src/orcshot/gnome_extension_setup.py` (UUID constants, `extensions_to_enable`, delete `enable_extension_live`, add `bundled_version_name`, `needs_relogin`)
- Modify: `src/orcshot/autostart.py:25` (docstring mentions `enable_extension_live`)
- Test: `tests/unit/test_gnome_extension_setup.py`

**Interfaces:**
- Consumes: `ShellBridge.register`, `get_bridge()` (Task 1).
- Produces:
  ```python
  # gnome_extension_setup.py
  EXTENSION_UUID = "orcshot@orcshot.org"
  def extensions_to_enable(is_gnome_wayland: bool) -> list[str]     # always [EXTENSION_UUID] now
  def bundled_version_name() -> str                                  # from the bundled metadata.json
  def needs_relogin(live_version_name: str | None, bundled: str) -> bool
  ```
  `TRAY_EXTENSION_UUID`, `CLIPBOARD_EXTENSION_UUID`, `WINDOW_CALLS_EXTENSION_UUID` are kept as aliases of `EXTENSION_UUID` **until Task 5 deletes their last users**, then removed there.

- [ ] **Step 1: Write the failing tests**

Replace the `extensions_to_enable` tests in `tests/unit/test_gnome_extension_setup.py` (`test_can_enable_all_three_bundled_extensions_independently`, `test_gnome_wayland_enables_all_three`, `test_gnome_x11_enables_only_tray`) with:

```python
from orcshot.gnome_extension_setup import (
    EXTENSION_UUID, bundled_version_name, extensions_to_enable, needs_relogin,
)


class TestExtensionsToEnable:
    def test_wayland_enables_the_one_extension(self):
        assert extensions_to_enable(True) == [EXTENSION_UUID]

    def test_x11_enables_it_too_for_the_tray(self):
        assert extensions_to_enable(False) == [EXTENSION_UUID]


class TestVersionName:
    def test_bundled_version_name_is_a_dotted_version(self):
        name = bundled_version_name()
        assert name and all(part.isdigit() for part in name.split("."))

    def test_needs_relogin_when_live_is_older(self):
        assert needs_relogin("0.3.0", "0.4.0") is True

    def test_no_relogin_when_equal_or_newer(self):
        assert needs_relogin("0.4.0", "0.4.0") is False
        assert needs_relogin("0.5.0", "0.4.0") is False

    def test_no_relogin_when_no_extension_at_all(self):
        assert needs_relogin(None, "0.4.0") is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_gnome_extension_setup.py -q`
Expected: `ImportError: cannot import name 'EXTENSION_UUID'`

- [ ] **Step 3: Implement in `gnome_extension_setup.py`**

At the UUID constants (around line 34):

```python
EXTENSION_UUID = "orcshot@orcshot.org"
# Transitional aliases - Task 5 of the 2026-09-11 plan deletes these with
# their last callers in first_run_setup.py.
WINDOW_CALLS_EXTENSION_UUID = EXTENSION_UUID
CLIPBOARD_EXTENSION_UUID = EXTENSION_UUID
TRAY_EXTENSION_UUID = EXTENSION_UUID
```

Replace `extensions_to_enable`'s body:

```python
def extensions_to_enable(is_gnome_wayland: bool) -> list:
    """One extension now carries tray, capture and window-calls (spec
    2026-09-11 section 2); the tray is wanted on X11 too, so the session
    type no longer changes the answer. Kept as a function so first-run
    setup's call site is unchanged."""
    return [EXTENSION_UUID]
```

Delete `enable_extension_live` entirely (lines ~106-165) and its `Gio` D-Bus imports if now unused. Add:

```python
import json
from pathlib import Path


def bundled_version_name() -> str:
    """The extension's own protocol version, from the copy bundled in
    this package's resources - `version-name`, the field EGO leaves alone
    (EGO overwrites `version` with its own counter, so that one is never
    read). The resources ship in every channel even though only the
    .deb *installs* them; this is why."""
    metadata = Path(__file__).parent / "resources" / "gnome-shell-extensions" / EXTENSION_UUID / "metadata.json"
    return json.loads(metadata.read_text())["version-name"]


def _version_tuple(name: str) -> tuple:
    return tuple(int(p) for p in name.split("."))


def needs_relogin(live_version_name, bundled: str) -> bool:
    """True when the running Shell serves an older copy than the one
    shipped - the state after an upgrade until the user logs out and in
    (GNOME Shell never reloads an extension's JS mid-session). None
    means no extension said Hello at all, which is the ordinary "not
    installed" state and not something to nag about."""
    if live_version_name is None:
        return False
    return _version_tuple(live_version_name) < _version_tuple(bundled)
```

`bundled_version_name()` reads `orcshot@orcshot.org/metadata.json`, which Task 4 creates. Until then, create the minimal file so this task is green on its own:

```bash
mkdir -p src/orcshot/resources/gnome-shell-extensions/orcshot@orcshot.org
cat > src/orcshot/resources/gnome-shell-extensions/orcshot@orcshot.org/metadata.json <<'EOF'
{
  "uuid": "orcshot@orcshot.org",
  "name": "Orcshot",
  "description": "Orcshot's tray icon, Wayland clipboard, region/window/eyedropper capture and window list, running inside GNOME Shell. Calls into the Orcshot app; exposes nothing on D-Bus itself.",
  "shell-version": ["45", "46", "47", "48", "49", "50"],
  "version-name": "0.4.0",
  "url": "https://github.com/artificialorctelligence/orcshot"
}
EOF
```

- [ ] **Step 4: Wire the bridge in `app.py`**

In `OrcshotApplication.__init__` (after `super().__init__`): `self._shell_bridge = get_bridge()` with `from orcshot.capture.shell_bridge import get_bridge` at the imports.

In `do_dbus_register`, after the Destinations `register_object` call and before `return True`:

```python
        # Spec 2026-09-11 §2: the extension calls in here; the app's only
        # outbound signal is the shell-request action this registers.
        self._shell_bridge.register(connection, object_path, self)
```

(`object_path` is `/org/orcshot/Orcshot`; `self` is the `Gio.ActionMap`. The bridge exports the Shell object at its own fixed `/org/orcshot/Orcshot/Shell`.)

Replace `_check_shell_extension_health`'s body after the docstring:

```python
        if os.environ.get("XDG_SESSION_TYPE") != "wayland":
            return
        from orcshot.gnome_extension_setup import bundled_version_name, needs_relogin

        def check(_capabilities):
            if needs_relogin(self._shell_bridge.version_name, bundled_version_name()):
                self._notify(
                    _("Orcshot's Wayland integration needs a restart"),
                    _(
                        "An update changed how Orcshot's Shell extension works, but your session is "
                        "still running the previous version. Log out and back in to finish applying it."
                    ),
                )

        # Hello arrives after startup, asynchronously - check when it does.
        self._shell_bridge.on_capabilities_changed(check)
```

Delete the now-unused imports of `EXPECTED_API_VERSION`, `get_live_api_version`, `gnome_region_select.is_available` inside that method. In `autostart.py:25` reword the docstring sentence to drop the `enable_extension_live` reference.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: all pass. `tests/unit/ui/test_first_run_setup.py` still imports the alias constants, so it stays green.

- [ ] **Step 6: Commit**

```bash
git add src/orcshot/app.py src/orcshot/gnome_extension_setup.py src/orcshot/autostart.py src/orcshot/resources/gnome-shell-extensions/orcshot@orcshot.org/metadata.json tests/unit/test_gnome_extension_setup.py
git commit -m "Wire the shell bridge into the app; one extension UUID; stale-copy check by version-name (#205)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Switch the six GNOME capture modules and backend selection to the bridge

**Files:**
- Modify: `src/orcshot/capture/gnome_clipboard.py`, `gnome_window_calls.py`, `gnome_region_select.py`, `gnome_window_picker.py`, `gnome_eyedropper.py`, `gnome_capture_rect.py`, `backend_select.py`
- Test: `tests/unit/capture/test_gnome_clipboard.py`, `tests/unit/capture/test_gnome_window_calls.py`, `tests/unit/capture/test_gnome_region_select.py`

**Interfaces:**
- Consumes: `get_bridge()`, `ShellBridge.has/request/request_async`, `ShellRequestError`, `ShellUnavailable` (Task 1).
- Produces (unchanged public API — callers in `app.py`, `ui/*.py`, `backend_select.py` do not change):
  `GnomeClipboardBackend().set_image(image)`, `gnome_clipboard.is_available()`, `GnomeWindowCallsBackend().list_windows()/active_window()/activate(id)`, `gnome_window_calls.is_available()`, `start_region_select(on_selected, on_cancelled)`, `start_window_picker(on_selected, on_cancelled)`, `start_eyedropper(on_picked, on_cancelled)`, `start_capture_rect(rect, on_captured, on_cancelled)`, each module's `is_available()`.
- Deleted: `BUS_NAME`, `OBJECT_PATH`, `INTERFACE`, `EXPECTED_API_VERSION`, `get_live_api_version`, `GnomeClipboardBackend.ping`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/capture/test_gnome_clipboard.py`:

```python
import numpy as np
import pytest
from orcshot.capture import shell_bridge
from orcshot.capture.gnome_clipboard import GnomeClipboardBackend, GnomeClipboardUnavailable, is_available


class FakeBridge:
    def __init__(self, capabilities=(), result=None, error=None):
        self.capabilities = frozenset(capabilities)
        self.calls = []
        self._result, self._error = result, error
    def has(self, kind):
        return kind in self.capabilities
    def request(self, kind, params=None, timeout_ms=5000):
        self.calls.append((kind, params))
        if self._error:
            raise self._error
        return self._result


@pytest.fixture
def fake_bridge(monkeypatch):
    def install(**kw):
        bridge = FakeBridge(**kw)
        monkeypatch.setattr(shell_bridge, "_bridge", bridge)
        return bridge
    return install


def test_is_available_is_the_clipboard_capability(fake_bridge):
    assert is_available() is False
    fake_bridge(capabilities=["set-clipboard-image"])
    assert is_available() is True


def test_set_image_sends_png_bytes_as_a_request(fake_bridge):
    bridge = fake_bridge(capabilities=["set-clipboard-image"], result={"ok": True})
    GnomeClipboardBackend().set_image(np.zeros((2, 2, 4), dtype=np.uint8))
    (kind, params), = bridge.calls
    assert kind == "set-clipboard-image"
    assert params["pngBytes"].startswith(b"\x89PNG")


def test_set_image_maps_bridge_errors_to_unavailable(fake_bridge):
    fake_bridge(capabilities=["set-clipboard-image"], error=shell_bridge.ShellUnavailable("gone"))
    with pytest.raises(GnomeClipboardUnavailable):
        GnomeClipboardBackend().set_image(np.zeros((2, 2, 4), dtype=np.uint8))
```

Add to `tests/unit/capture/test_gnome_window_calls.py` (reuse the same `FakeBridge`/fixture — copy them; a shared `tests/unit/capture/fake_bridge.py` is fine too):

```python
import json
from orcshot.capture.gnome_window_calls import GnomeWindowCallsBackend, GnomeWindowCallsUnavailable, is_available


def test_list_windows_parses_the_delivered_json(fake_bridge):
    fake_bridge(capabilities=["list-windows"], result={"windows": json.dumps([_raw()])})
    windows = GnomeWindowCallsBackend().list_windows()
    assert [w.window_id for w in windows] == [12345]


def test_activate_sends_the_window_id(fake_bridge):
    bridge = fake_bridge(capabilities=["activate-window"], result={"ok": True})
    GnomeWindowCallsBackend().activate(7)
    assert bridge.calls == [("activate-window", {"id": 7})]


def test_is_available_is_the_list_windows_capability(fake_bridge):
    assert is_available() is False
    fake_bridge(capabilities=["list-windows"])
    assert is_available() is True
```

Add to `tests/unit/capture/test_gnome_region_select.py`:

```python
from orcshot.capture import shell_bridge
from orcshot.capture.gnome_region_select import start_region_select


class FakeAsyncBridge:
    def __init__(self, capabilities):
        self.capabilities = frozenset(capabilities)
        self.calls = []
    def has(self, kind):
        return kind in self.capabilities
    def request_async(self, kind, params, on_result, on_error, timeout_ms=None):
        self.calls.append((kind, params, on_result, on_error))
        return 1


def test_start_region_select_requests_with_magnifier_flag_and_decodes_result(monkeypatch, tmp_path):
    bridge = FakeAsyncBridge(["region-select"])
    monkeypatch.setattr(shell_bridge, "_bridge", bridge)
    monkeypatch.setattr("orcshot.capture.gnome_region_select.get_show_magnifier_while_selecting", lambda: True)
    got = []
    start_region_select(on_selected=lambda img, rect, dest: got.append((img.shape, rect, dest)), on_cancelled=lambda: got.append("cancel"))
    kind, params, on_result, _ = bridge.calls[0]
    assert (kind, params) == ("region-select", {"showMagnifier": True})
    on_result({"ok": True, "destination": "editor", "pngBytes": _png_2x3(), "x": 5, "y": 6, "width": 2, "height": 3})
    assert got[0][0] == (3, 2, 4) and got[0][1].left == 5 and got[0][2] == "editor"


def test_start_region_select_error_is_cancel(monkeypatch):
    bridge = FakeAsyncBridge(["region-select"])
    monkeypatch.setattr(shell_bridge, "_bridge", bridge)
    monkeypatch.setattr("orcshot.capture.gnome_region_select.get_show_magnifier_while_selecting", lambda: False)
    got = []
    start_region_select(on_selected=lambda *a: got.append("selected"), on_cancelled=lambda: got.append("cancel"))
    bridge.calls[0][3](shell_bridge.ShellRequestError("cancelled"))
    assert got == ["cancel"]
```

`_png_2x3()` — encode a 3-row, 2-column RGBA numpy array with the module's own `_encode_png` from `gnome_clipboard` (the existing test file already builds PNGs; reuse its helper).

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/unit/capture/test_gnome_clipboard.py tests/unit/capture/test_gnome_window_calls.py tests/unit/capture/test_gnome_region_select.py -q`
Expected: failures on `is_available()` (still probes D-Bus) and `bridge.calls` being empty.

- [ ] **Step 3: Rewrite `gnome_clipboard.py`'s plumbing**

Keep the docstring (update its second paragraph to say "via the bridge, spec 2026-09-11"), `_encode_png`, `GnomeClipboardUnavailable`. Delete `BUS_NAME`, `OBJECT_PATH`, `INTERFACE`, `EXPECTED_API_VERSION`, `_VERSION_*`, `get_live_api_version`, `ping`. The class becomes:

```python
from orcshot.capture.shell_bridge import ShellRequestError, get_bridge

CAPABILITY = "set-clipboard-image"


class GnomeClipboardBackend:
    def set_image(self, image: np.ndarray) -> None:
        try:
            get_bridge().request(CAPABILITY, {"pngBytes": _encode_png(image)}, timeout_ms=5000)
        except ShellRequestError as error:
            raise GnomeClipboardUnavailable(f"Shell extension {CAPABILITY} failed: {error}") from error


def is_available() -> bool:
    """A capability the extension announced in Hello - a dictionary
    lookup, no probe, no side effect on the user's clipboard."""
    return get_bridge().has(CAPABILITY)
```

- [ ] **Step 4: Rewrite `gnome_window_calls.py`'s plumbing**

Keep everything above `class GnomeWindowCallsBackend` except the three bus constants. The class:

```python
from orcshot.capture.shell_bridge import ShellRequestError, get_bridge


class GnomeWindowCallsBackend:
    def _list_raw(self) -> list[dict]:
        try:
            result = get_bridge().request("list-windows", timeout_ms=5000)
        except ShellRequestError as error:
            raise GnomeWindowCallsUnavailable(f"Shell extension list-windows failed: {error}") from error
        return json.loads(result["windows"])

    def list_windows(self):
        windows = [parse_window_info(w) for w in self._list_raw()]
        return [w for w in windows if is_capturable(w)]

    def active_window(self):
        for raw in self._list_raw():
            if raw.get("focus"):
                return parse_window_info(raw)
        return None

    def activate(self, window_id: int) -> None:
        try:
            get_bridge().request("activate-window", {"id": int(window_id)}, timeout_ms=5000)
        except ShellRequestError as error:
            raise GnomeWindowCallsUnavailable(f"Shell extension activate-window failed: {error}") from error


def is_available() -> bool:
    return get_bridge().has("list-windows")
```

- [ ] **Step 5: Rewrite the four async modules**

`gnome_region_select.py` — replace `is_available` and `start_region_select`'s bus call:

```python
from orcshot.capture.shell_bridge import ShellRequestError, ShellUnavailable, get_bridge

CAPABILITY = "region-select"


def is_available() -> bool:
    return get_bridge().has(CAPABILITY)


def start_region_select(on_selected, on_cancelled=None) -> None:
    # (keep the existing docstring)
    def on_result(result: dict):
        try:
            image = decode_png(bytes(result["pngBytes"]))
            x, y, w, h = result["x"], result["y"], result["width"], result["height"]
            on_selected(image, Rect(x, y, x + w, y + h), result["destination"])
        except Exception:
            print("[gnome_region_select] exception in on_result:", file=sys.stderr, flush=True)
            traceback.print_exc()

    def on_error(_error):
        if on_cancelled is not None:
            on_cancelled()

    try:
        get_bridge().request_async(
            CAPABILITY, {"showMagnifier": get_show_magnifier_while_selecting()}, on_result, on_error,
        )
    except ShellUnavailable:
        on_error(None)
```

Apply the same shape to the other three, with these kinds/params/results:

| Module | kind | params | `on_result` unpack |
|---|---|---|---|
| `gnome_window_picker.start_window_picker` | `window-picker` | `{}` | `image = decode_png(bytes(r["pngBytes"]))`, `on_selected(image, Rect(x, y, x+w, y+h), r["destination"], r["title"])` — keep the exact positional order the current `on_reply` passes |
| `gnome_eyedropper.start_eyedropper` | `eyedropper` | `{}` | `on_picked(r["r"], r["g"], r["b"], r["a"])` |
| `gnome_capture_rect.start_capture_rect` | `capture-rect` | `{"x": rect.left, "y": rect.top, "width": rect.width, "height": rect.height}` | `on_captured(decode_png(bytes(r["pngBytes"])), r["destination"])` — keep the current argument order |

Each module's `is_available()` becomes `get_bridge().has(<its kind>)`. Delete `OBJECT_PATH`/`INTERFACE`/`BUS_NAME` imports and constants in all four. Read each module's current `on_reply` before rewriting to keep callback arities identical — the UI callers are not touched by this task.

- [ ] **Step 6: `backend_select.py` — per-call selection**

`default_clipboard_backend()` and `default_window_enumerator_and_activator()` currently probe once. Replace the Wayland branches with wrappers that decide per call:

```python
class _WaylandClipboard:
    """Shell-native when the extension has said Hello, portal otherwise -
    decided on every call, because Hello arrives asynchronously after
    startup and a one-time probe could race it (spec 2026-09-11 §3)."""
    def __init__(self):
        from orcshot.capture.wayland_clipboard import WaylandClipboardBackend
        self._portal = WaylandClipboardBackend()
    def set_image(self, image):
        from orcshot.capture.gnome_clipboard import GnomeClipboardBackend, GnomeClipboardUnavailable, is_available
        if is_available():
            try:
                return GnomeClipboardBackend().set_image(image)
            except GnomeClipboardUnavailable:
                pass
        return self._portal.set_image(image)
```

Return `_WaylandClipboard()` on Wayland. Check `ClipboardBackend`'s protocol in `capture/clipboard.py` (or wherever it is defined) and implement every method it declares, delegating to `self._portal` for the rest. For windows, keep `default_window_enumerator_and_activator()` as is (it is called at picker start, after Hello has long arrived) but make `window_picker_supported()` call `is_available()` each time — it already does.

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: all pass; `grep -rn "org.gnome.Shell" src/orcshot --include=*.py` prints only `gnome_extension_setup.py` lines (the `enable_extension` gsettings path mentions the schema `org.gnome.shell`, lower-case) and nothing under `capture/`.

- [ ] **Step 8: Commit**

```bash
git add src/orcshot/capture tests/unit/capture
git commit -m "Route every GNOME capture module through the shell bridge; no app->org.gnome.Shell calls remain (#205)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The merged extension `orcshot@orcshot.org`

**Files:**
- Create: `src/orcshot/resources/gnome-shell-extensions/orcshot@orcshot.org/{extension.js,tray.js,capture.js,windows.js}`; move `icons/`, `locale/`, `icon_geometry.json`, `magnifier_constants.json` from `orcshot-clipboard@orcshot.org/`
- Delete: `orcshot-clipboard@orcshot.org/`, `orcshot-tray@orcshot.org/`, `window-calls@domandoman.xyz/`
- Modify: `debian/orcshot.install:4-21`, `THIRD_PARTY_NOTICES.md` (window-calls path), `src/orcshot/hotkey_setup.py:508-510` (comment), `src/orcshot/gnome_extension_setup.py` (drop the three alias constants once `first_run_setup.py` no longer imports them — see Task 5; if Task 5 hasn't run, leave them)

**Interfaces:**
- Consumes: the app-side contract from Task 1 (method names, kinds, result keys — the table in Task 3 Step 5 and the spec §2).
- Produces: a GNOME Shell extension that (a) calls `Hello("<version-name>", [...])` on enable and on every `org.orcshot.Orcshot` name appearance, (b) subscribes to `shell-request`, (c) for each request id calls `GetRequest`, dispatches on `kind`, calls `Deliver`.

- [ ] **Step 1: Create the directory by moving, so `git` keeps history**

```bash
cd src/orcshot/resources/gnome-shell-extensions
git mv orcshot-clipboard@orcshot.org/extension.js orcshot@orcshot.org/capture.js
git mv orcshot-clipboard@orcshot.org/icons orcshot@orcshot.org/icons
git mv orcshot-clipboard@orcshot.org/locale orcshot@orcshot.org/locale
git mv orcshot-clipboard@orcshot.org/icon_geometry.json orcshot@orcshot.org/icon_geometry.json
git mv orcshot-clipboard@orcshot.org/magnifier_constants.json orcshot@orcshot.org/magnifier_constants.json
git mv orcshot-tray@orcshot.org/extension.js orcshot@orcshot.org/tray.js
git mv window-calls@domandoman.xyz/extension.js orcshot@orcshot.org/windows.js
git rm -r orcshot-clipboard@orcshot.org orcshot-tray@orcshot.org window-calls@domandoman.xyz
ls orcshot@orcshot.org
```

Expected: `capture.js icon_geometry.json icons locale magnifier_constants.json metadata.json tray.js windows.js`.

- [ ] **Step 2: Turn `tray.js` into a module**

In `tray.js`: delete the `import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';` line and the whole `export default class OrcshotTrayExtension extends Extension { ... }` block at the bottom (lines ~275-330). Add at the end:

```javascript
/** Builds the panel button while org.orcshot.Orcshot is owned; extension.js
 *  drives create/destroy from its own name watcher so there is exactly one
 *  watcher for the whole extension. */
export function createTrayButton() {
    const button = new OrcshotTrayButton();
    Main.panel.addToStatusArea('orcshot-tray-button', button);
    return button;
}
```

Keep `BUS_NAME`, `MENU_PATH`, `ACTIONS_PATH` constants and the `OrcshotTrayButton` class exactly as they are.

- [ ] **Step 3: Turn `capture.js` into a module**

In `capture.js`:
1. Delete the `CLIPBOARD_IFACE`, `CAPTURE_IFACE`, `VERSION_IFACE`, `API_VERSION` constants and the `export default class Extension extends ShellExtension { ... }` block (from `export default` to the end of the file). Delete the `ShellExtension`, `PanelMenu`, `PopupMenu` imports if nothing else in the file uses them (grep first — `pickDestinationAsync` uses `PopupMenu`; keep what is used).
2. Fix the file-reading helpers that locate data files relative to the extension directory (`_loadMagnifierConstants`, `_loadIconGeometry` around lines 244 and 1713): they currently derive the path from the extension object; make them take a `dir` (a `Gio.File`) parameter and export an `init(extensionDir)` that stores it in a module-level `let _dir`.
3. Append the request handlers — one exported async function per kind, returning the `Deliver` result object. Each is the body of the corresponding `*Async` method with `invocation.return_value(...)` replaced by `return {...}`:

```javascript
// ---- request handlers: kind -> async (params) => result object ----
export const handlers = {
    async 'region-select'({ showMagnifier }) {
        const overlay = new RegionSelectOverlay(!!showMagnifier);
        const r = await overlay.selectAsync();
        return r === null ? { ok: false, error: 'cancelled' }
            : { ok: true, destination: r.destination, pngBytes: r.pngBytes, x: r.x, y: r.y, width: r.width, height: r.height };
    },
    async 'window-picker'() {
        // body of StartWindowPickerAsync, same translation; result keys:
        // ok, destination, title, pngBytes, x, y, width, height
    },
    async 'eyedropper'() {
        // body of StartEyedropperAsync; result keys: ok, r, g, b, a
    },
    async 'capture-rect'({ x, y, width, height }) {
        // body of CaptureRectAsync; result keys: ok, destination, pngBytes
    },
    async 'set-clipboard-image'({ pngBytes }) {
        // body of SetImage (St.Clipboard set_content with the PNG bytes)
        return { ok: true };
    },
    async 'ping'() {
        return { ok: true };
    },
};
```

Write each body out in full from the existing method — the existing methods are the reference implementation and must not change behaviour; only their input (destructured params instead of a `parameters` array) and output (a returned object instead of `invocation.return_value`) change. `pngBytes` values must be a `Uint8Array` (what `selectAsync` already yields), which `GLib.Variant` packs as `ay`.

- [ ] **Step 4: Turn `windows.js` into a module**

In `windows.js`: keep the license header and the modification notes. Delete the `export default class Extension { enable() {...} disable() {...} ... }` wrapper but keep `List()`, `Activate()`, `_get_window_by_wid()` and their helpers as module-level functions:

```javascript
export const handlers = {
    async 'list-windows'() {
        return { windows: List() };        // List() already returns the JSON string
    },
    async 'activate-window'({ id }) {
        Activate(id);                       // throws if not found -> extension.js reports ok:false
        return { ok: true };
    },
};
```

Delete the `MR_DBUS_IFACE` XML constant and the `Gio.DBusExportedObject` usage.

- [ ] **Step 5: Write `extension.js` — the dispatcher**

```javascript
// extension.js - Orcshot's GNOME Shell extension: one name watcher, one
// Hello, one request loop. Everything privileged lives in capture.js,
// windows.js and tray.js; this file only routes.
//
// Direction: this extension CALLS the Orcshot app; the app never calls the
// Shell. The app asks by changing the state of its `shell-request` action
// (org.gtk.Actions.Changed is the one signal a strict snap may emit), and
// this file answers with GetRequest/Deliver on org.orcshot.Orcshot.Shell.
// Spec: docs/superpowers/specs/2026-09-11-snap-compliant-extension-delivery-design.md
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Capture from './capture.js';
import * as Windows from './windows.js';
import { createTrayButton } from './tray.js';

const BUS_NAME = 'org.orcshot.Orcshot';
const ACTIONS_PATH = '/org/orcshot/Orcshot';
const SHELL_PATH = '/org/orcshot/Orcshot/Shell';
const SHELL_IFACE = 'org.orcshot.Orcshot.Shell';
const REQUEST_ACTION = 'shell-request';

const HANDLERS = { ...Capture.handlers, ...Windows.handlers };
const CAPABILITIES = ['tray', ...Object.keys(HANDLERS)];

function toVariantDict(obj) {
    const out = {};
    for (const [k, v] of Object.entries(obj)) {
        if (typeof v === 'boolean') out[k] = new GLib.Variant('b', v);
        else if (typeof v === 'number') out[k] = new GLib.Variant('i', v | 0);
        else if (typeof v === 'string') out[k] = new GLib.Variant('s', v);
        else if (v instanceof Uint8Array) out[k] = new GLib.Variant('ay', v);
        else if (v instanceof GLib.Bytes) out[k] = new GLib.Variant('ay', v.toArray());
        else throw new Error(`unsupported result value for ${k}: ${typeof v}`);
    }
    return new GLib.Variant('a{sv}', out);
}

export default class OrcshotExtension extends Extension {
    enable() {
        log('orcshot: extension enabled');
        Capture.init(this.dir);
        this._button = null;
        this._group = null;
        this._stateChangedId = 0;
        this._watchId = Gio.bus_watch_name(
            Gio.BusType.SESSION, BUS_NAME, Gio.BusNameWatcherFlags.NONE,
            () => this._onAppAppeared(),
            () => this._onAppVanished(),
        );
    }

    disable() {
        if (this._watchId) { Gio.bus_unwatch_name(this._watchId); this._watchId = 0; }
        this._onAppVanished();
    }

    _onAppAppeared() {
        if (!this._button) {
            try { this._button = createTrayButton(); }
            catch (e) { logError(e, 'orcshot: failed to build tray button'); }
        }
        this._group = Gio.DBusActionGroup.get(Gio.DBus.session, BUS_NAME, ACTIONS_PATH);
        this._stateChangedId = this._group.connect('action-state-changed', (_g, name, state) => {
            if (name === REQUEST_ACTION)
                this._handleRequest(state.get_uint32()).catch(e => logError(e, 'orcshot: request failed'));
        });
        this._group.list_actions();   // first call only kicks off DescribeAll; the group goes live asynchronously
        this._call('Hello', new GLib.Variant('(sas)', [this.metadata['version-name'], CAPABILITIES]))
            .catch(e => logError(e, 'orcshot: Hello failed'));
    }

    _onAppVanished() {
        if (this._group && this._stateChangedId) { this._group.disconnect(this._stateChangedId); }
        this._group = null; this._stateChangedId = 0;
        if (this._button) { this._button.destroy(); this._button = null; }
    }

    _call(method, args) {
        return new Promise((resolve, reject) => {
            Gio.DBus.session.call(BUS_NAME, SHELL_PATH, SHELL_IFACE, method, args, null,
                Gio.DBusCallFlags.NONE, 10000, null, (conn, res) => {
                    try { resolve(conn.call_finish(res)); } catch (e) { reject(e); }
                });
        });
    }

    async _handleRequest(id) {
        if (!id) return;                                   // initial state 0
        const [req] = (await this._call('GetRequest', new GLib.Variant('(u)', [id]))).deepUnpack();
        const { kind, ...params } = req;
        const handler = HANDLERS[kind];
        let result;
        try {
            result = handler ? await handler(params) : { ok: false, error: `unknown kind ${kind}` };
        } catch (e) {
            logError(e, `orcshot: handler ${kind} threw`);
            result = { ok: false, error: String(e) };
        }
        await this._call('Deliver', new GLib.Variant('(ua{sv})', [id, toVariantDict(result)]));
    }
}
```

`this.metadata['version-name']` is how GNOME's `Extension` base class exposes `metadata.json`. `deepUnpack()` on the `(a{sv})` reply gives a plain object whose `ay` values arrive as `Uint8Array` — `set-clipboard-image` consumes that directly.

- [ ] **Step 6: Update the packaging list and notices**

`debian/orcshot.install`: replace lines 4–10 and 20–21 (the three extension directories) with:

```
src/orcshot/resources/gnome-shell-extensions/orcshot@orcshot.org/*.js usr/share/gnome-shell/extensions/orcshot@orcshot.org/
src/orcshot/resources/gnome-shell-extensions/orcshot@orcshot.org/metadata.json usr/share/gnome-shell/extensions/orcshot@orcshot.org/
src/orcshot/resources/gnome-shell-extensions/orcshot@orcshot.org/icon_geometry.json usr/share/gnome-shell/extensions/orcshot@orcshot.org/
src/orcshot/resources/gnome-shell-extensions/orcshot@orcshot.org/magnifier_constants.json usr/share/gnome-shell/extensions/orcshot@orcshot.org/
src/orcshot/resources/gnome-shell-extensions/orcshot@orcshot.org/icons/*.png usr/share/gnome-shell/extensions/orcshot@orcshot.org/icons/
```

(Check how `locale/` is currently installed for the clipboard extension and carry that line over with the new path.) In `THIRD_PARTY_NOTICES.md`, change the window-calls file path to `orcshot@orcshot.org/windows.js`. In `hotkey_setup.py:508-510`, reword the comment that names "window-calls then orcshot-clipboard" to "the orcshot@orcshot.org extension".

- [ ] **Step 7: Syntax-check the JS and install it live on the 26.04 VM**

No unit test can load GJS Shell modules. Two checks, both required:

```bash
# 1. Parse-only check for each module (catches syntax errors, not resource imports)
for f in src/orcshot/resources/gnome-shell-extensions/orcshot@orcshot.org/*.js; do node --check "$f" 2>&1 | grep -v "Cannot find module\|resource:" ; done
```

Expected: no `SyntaxError` lines. (`node` rejects `gi://` imports only at load, not parse — `--check` is parse-only.)

```bash
# 2. Real Shell: copy to the VM's user extension dir and log out/in there
V="ssh -i ~/.ssh/orcshot_dev_vm -p 2222 ubuntu2604@localhost"
tar -C src/orcshot/resources/gnome-shell-extensions -cf - orcshot@orcshot.org | $V 'rm -rf ~/.local/share/gnome-shell/extensions/{orcshot-clipboard@orcshot.org,orcshot-tray@orcshot.org,window-calls@domandoman.xyz,orcshot@orcshot.org}; tar -C ~/.local/share/gnome-shell/extensions -xf -'
$V 'gsettings set org.gnome.shell enabled-extensions "[\"orcshot@orcshot.org\"]"'
```

Then log the VM out and in (GUI: `DISPLAY=:0 VBoxManage startvm "Ubuntu 26.04" --type gui` after a poweroff if headless; the desktop auto-logs in), and:

```bash
$V 'journalctl --user -b -o cat | grep -i "orcshot\|JS ERROR" | tail -20'
```

Expected: `orcshot: extension enabled`, no `JS ERROR`. Install the current source tree on the VM (`pip install -e` in the VM's `~/orcshot-dev` checkout, or the `.deb` from Task 6 later) and start Orcshot inside the graphical session; expected in the app's stderr: nothing about `org.gnome.Shell`, and `gdbus introspect --session --dest org.orcshot.Orcshot --object-path /org/orcshot/Orcshot/Shell` shows the three methods. Trigger `tray-region` via `gdbus call ... org.gtk.Actions.Activate tray-region [] {}` as the VM memory describes; the Shell overlay must appear and the captured image must reach the editor.

- [ ] **Step 8: Run the suite and commit**

Run: `.venv/bin/pytest tests/ -q` — Expected: all pass.

```bash
git add -A src/orcshot/resources/gnome-shell-extensions debian/orcshot.install THIRD_PARTY_NOTICES.md src/orcshot/hotkey_setup.py
git commit -m "Merge the three GNOME Shell extensions into orcshot@orcshot.org; extension calls the app, exposes nothing (#205)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: First-run per channel — redirect, never copy

**Files:**
- Modify: `src/orcshot/ui/first_run_setup.py` (delete lines 125-246 helpers and `_install_bundled_extensions_for_sandboxed_channel`, `show_snap_connect_prompt` at 508+; the `is_gnome` block at 463-472)
- Modify: `src/orcshot/channel_detect.py` (delete `_metadata_version`, `install_bundled_extension_if_needed`; keep `detect_channel`)
- Modify: `src/orcshot/gnome_extension_setup.py` (delete the three alias constants)
- Create: `src/orcshot/ui/extension_install.py`
- Test: `tests/unit/ui/test_first_run_setup.py`, `tests/unit/test_channel_detect.py`, `tests/unit/ui/test_extension_install.py`

**Interfaces:**
- Consumes: `detect_channel()`, `get_bridge().on_capabilities_changed`, `EXTENSION_UUID`.
- Produces:
  ```python
  # ui/extension_install.py
  EGO_URL = "https://extensions.gnome.org/extension/<id>/orcshot/"   # placeholder until Task 9 publishes; until then "https://extensions.gnome.org/"
  SPICES_URL = "https://cinnamon-spices.linuxmint.com/applets/view/<id>"   # same
  def plan_install(channel: str, desktop: str) -> str | None
      # -> None | "flatpak-gnome" | "snap-gnome" | "flatpak-cinnamon"
  def request_gnome_install(uuid: str, bus=None) -> str    # InstallRemoteExtension; returns GNOME's result string
  def show_install_dialog(plan: str, parent=None) -> None  # the §7 dialogs; auto-closes on Hello
  ```
  `desktop` is the same value `first_run_setup` already computes (`"gnome"` / `"cinnamon"` / other).

- [ ] **Step 1: Write the failing tests**

`tests/unit/ui/test_extension_install.py`:

```python
import pytest
from orcshot.ui.extension_install import plan_install, request_gnome_install


@pytest.mark.parametrize("channel,desktop,expected", [
    ("deb", "gnome", None),
    ("deb", "cinnamon", None),
    ("flatpak", "gnome", "flatpak-gnome"),
    ("flatpak", "cinnamon", "flatpak-cinnamon"),
    ("snap", "gnome", "snap-gnome"),
    ("snap", "cinnamon", None),
    ("flatpak", "kde", None),
])
def test_plan_install(channel, desktop, expected):
    assert plan_install(channel, desktop) == expected


class FakeBus:
    def __init__(self, reply="successful"):
        self.calls = []
        self._reply = reply
    def call_sync(self, dest, path, iface, method, args, reply_type, flags, timeout, cancellable):
        self.calls.append((dest, path, iface, method, args.unpack()))
        from gi.repository import GLib
        return GLib.Variant("(s)", (self._reply,))


def test_request_gnome_install_asks_the_shell():
    bus = FakeBus()
    assert request_gnome_install("orcshot@orcshot.org", bus=bus) == "successful"
    (dest, path, iface, method, args), = bus.calls
    assert (dest, path, iface, method, args) == (
        "org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Extensions", "InstallRemoteExtension", ("orcshot@orcshot.org",))
```

In `tests/unit/ui/test_first_run_setup.py`: delete `test_extension_bundle_dir_snap`, `test_snap_real_home_extensions_dir_uses_snap_real_home_not_home`, `test_deb_channel_never_installs_bundled_extensions`, `test_snap_channel_installs_each_bundled_extension`, `test_snap_channel_prompts_when_an_install_fails`, `test_extension_bundle_dir_flatpak`, `test_flatpak_home_extensions_dir_uses_real_home`, `test_flatpak_channel_installs_each_bundled_extension`, `test_flatpak_channel_never_prompts_on_install_failure`, `test_snap_real_home_cinnamon_applets_dir`, `test_flatpak_home_cinnamon_applets_dir`, `test_cinnamon_applet_bundle_dir_snap`, `test_cinnamon_applet_bundle_dir_flatpak`. Add:

```python
def test_gnome_finish_enables_the_one_extension_and_shows_the_channel_dialog(monkeypatch):
    from orcshot.ui import first_run_setup
    enabled, shown = [], []
    monkeypatch.setattr(first_run_setup, "enable_extension", lambda backend, uuid: enabled.append(uuid))
    monkeypatch.setattr(first_run_setup, "detect_channel", lambda: "snap")
    monkeypatch.setattr(first_run_setup, "show_install_dialog", lambda plan, parent=None: shown.append(plan))
    first_run_setup._finish_gnome_setup(settings_backend=object(), desktop="gnome", parent=None)
    assert enabled == ["orcshot@orcshot.org"]
    assert shown == ["snap-gnome"]


def test_gnome_finish_on_deb_shows_nothing(monkeypatch):
    from orcshot.ui import first_run_setup
    shown = []
    monkeypatch.setattr(first_run_setup, "enable_extension", lambda backend, uuid: None)
    monkeypatch.setattr(first_run_setup, "detect_channel", lambda: "deb")
    monkeypatch.setattr(first_run_setup, "show_install_dialog", lambda plan, parent=None: shown.append(plan))
    first_run_setup._finish_gnome_setup(settings_backend=object(), desktop="gnome", parent=None)
    assert shown == []
```

In `tests/unit/test_channel_detect.py`: delete every test of `install_bundled_extension_if_needed` / `_metadata_version`; keep the `detect_channel` tests.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/unit/ui/test_extension_install.py tests/unit/ui/test_first_run_setup.py -q`
Expected: `ModuleNotFoundError: orcshot.ui.extension_install`.

- [ ] **Step 3: Write `ui/extension_install.py`**

```python
"""How Orcshot's GNOME Shell extension (or Cinnamon applet) gets installed
on each channel - spec 2026-09-11 §4 and §7. The app never writes into the
user's home on any channel; a sandboxed app is not allowed to put code
where the desktop shell loads it from (Snap Store: refused as a
confinement escape; Flathub: a home grant to review). So:

- .deb: the package installed it system-wide. Nothing to do.
- Flatpak on GNOME: ask GNOME to install it from extensions.gnome.org
  (InstallRemoteExtension; GNOME shows its own confirmation dialog).
  Exactly how Extension Manager on Flathub does it.
- Snap on GNOME: no snapd interface reaches GNOME's installer, so the
  dialog sends the user to extensions.gnome.org with explicit steps.
- Flatpak on Cinnamon: the tray applet lives on Cinnamon Spices; the
  dialog sends the user to System Settings -> Applets -> Download.
- Snap on Cinnamon: nothing (decided 2026-09-11: Mint blocks snapd).

Every dialog closes itself when the extension/applet says Hello.
"""

from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

from orcshot.capture.shell_bridge import get_bridge
from orcshot.i18n import _

EXTENSION_UUID = "orcshot@orcshot.org"
# Both URLs are replaced with the real listing pages once the first
# submissions are accepted (plan Task 9); the site roots work meanwhile.
EGO_URL = "https://extensions.gnome.org/"
SPICES_URL = "https://cinnamon-spices.linuxmint.com/applets/"


def plan_install(channel: str, desktop: str) -> str | None:
    if channel == "flatpak" and desktop == "gnome":
        return "flatpak-gnome"
    if channel == "flatpak" and desktop == "cinnamon":
        return "flatpak-cinnamon"
    if channel == "snap" and desktop == "gnome":
        return "snap-gnome"
    return None


def request_gnome_install(uuid: str, bus=None) -> str:
    """GNOME installs and enables the extension from EGO, with its own
    'Install extension?' dialog. Returns GNOME's result string
    ('successful' / 'cancelled'). The one org.gnome.Shell call left in
    the app, allowed because Flatpak grants --talk-name=org.gnome.Shell
    and the call *asks* rather than acts."""
    bus = bus or Gio.bus_get_sync(Gio.BusType.SESSION, None)
    reply = bus.call_sync(
        "org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Extensions", "InstallRemoteExtension",
        GLib.Variant("(s)", (uuid,)), GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 120000, None,
    )
    return reply.unpack()[0]


_TEXT = {
    "snap-gnome": (
        _("One more step for the tray icon and Wayland capture"),
        _("Orcshot's tray icon, region selection and window picker on Wayland run inside GNOME Shell as an "
          "extension. Snap packages aren't allowed to install extensions, so this one comes from GNOME's own "
          "extension site.\n\n"
          "1. Click Open extensions.gnome.org below.\n"
          "2. On the Orcshot page, switch the toggle to ON.\n"
          "3. That's it — this window closes by itself when the extension is running.\n\n"
          "If the page says your browser needs the GNOME Shell integration add-on: install the add-on it links "
          "to, then on Ubuntu run  sudo apt install gnome-browser-connector  (or install Extension Manager from "
          "the Software app and search for Orcshot there). This is a one-time setup for any extension, not just "
          "Orcshot's.\n\n"
          "Without the extension Orcshot still works — captures use GNOME's screenshot service and there's no "
          "tray icon."),
        _("Open extensions.gnome.org"), EGO_URL,
    ),
    "flatpak-gnome": (
        _("One more step for the tray icon and Wayland capture"),
        _("Orcshot's tray icon, region selection and window picker on Wayland run inside GNOME Shell as an "
          "extension. Click Install extension and GNOME will ask you to confirm.\n\n"
          "Without it Orcshot still works — captures use GNOME's screenshot service and there's no tray icon."),
        _("Install extension"), None,
    ),
    "flatpak-cinnamon": (
        _("One more step for the tray icon"),
        _("Orcshot's tray icon on Cinnamon is an applet from Mint's applet library.\n\n"
          "1. Open System Settings → Applets.\n"
          "2. Choose the Download tab and search for Orcshot.\n"
          "3. Click the install arrow, then add it to your panel from the Manage tab.\n\n"
          "This window closes by itself when the applet is running. Without it Orcshot still works; there's "
          "just no tray icon."),
        _("Open the Orcshot applet page"), SPICES_URL,
    ),
}


def show_install_dialog(plan: str, parent: Gtk.Window = None) -> None:
    title, body, action_label, url = _TEXT[plan]
    dialog = Gtk.Dialog(title=_("Orcshot Setup"), transient_for=parent)
    dialog.add_buttons(_("Later"), Gtk.ResponseType.CANCEL, action_label, Gtk.ResponseType.OK)
    box = dialog.get_content_area()
    heading = Gtk.Label(label=f"<b>{GLib.markup_escape_text(title)}</b>", use_markup=True, xalign=0)
    text = Gtk.Label(label=body, wrap=True, xalign=0, max_width_chars=70)
    for w in (heading, text):
        w.set_margin_start(12); w.set_margin_end(12); w.set_margin_top(8)
        box.add(w)
    box.show_all()

    def on_capabilities(caps):
        if caps:
            dialog.response(Gtk.ResponseType.DELETE_EVENT)

    get_bridge().on_capabilities_changed(on_capabilities)

    def on_response(d, response):
        if response == Gtk.ResponseType.OK:
            if url is not None:
                Gio.AppInfo.launch_default_for_uri(url, None)   # goes through the desktop portal under both sandboxes
                return                                          # keep the dialog open until Hello
            try:
                request_gnome_install(EXTENSION_UUID)
            except GLib.Error as error:
                text.set_text(body + "\n\n" + _("GNOME could not install it: %s") % error.message)
                return
            return                                              # Hello closes it
        d.destroy()

    dialog.connect("response", on_response)
    dialog.show()
```

`get_bridge().on_capabilities_changed` appends listeners forever; the dialog's listener holding a destroyed dialog is harmless (`response` on a destroyed `Gtk.Dialog` is a no-op warning at worst). If it isn't, add `off_capabilities_changed(callback)` to the bridge and call it in `on_response` — the test in Task 1 doesn't constrain that.

- [ ] **Step 4: Rewrite the GNOME branch of `first_run_setup.py`**

Delete lines 125–246 (`_extension_bundle_dir` … `_install_bundled_extensions_for_sandboxed_channel`) and `show_snap_connect_prompt`. Replace the `if is_gnome:` block inside `_run_dialog` (lines ~463-472) with `_finish_gnome_setup(settings_backend, desktop=desktop_name, parent=parent)` — read how `_run_dialog` computes `is_gnome`/`is_cinnamon` today and pass the same string it derives them from. Add:

```python
from orcshot.channel_detect import detect_channel
from orcshot.gnome_extension_setup import EXTENSION_UUID, enable_extension, extensions_to_enable
from orcshot.ui.extension_install import plan_install, show_install_dialog


def _finish_gnome_setup(settings_backend, desktop: str, parent=None) -> None:
    """Enables the extension in gsettings (works under every sandbox,
    proven; takes effect once GNOME has the files) and, on the channels
    that cannot install the files themselves, shows the redirect dialog
    for this channel/desktop. On .deb the package installed them: nothing
    to show."""
    for uuid in extensions_to_enable(True):
        enable_extension(settings_backend, uuid)
    plan = plan_install(detect_channel(), desktop)
    if plan is not None:
        show_install_dialog(plan, parent)
```

Also call `show_install_dialog` for the Cinnamon-on-Flatpak case from the Cinnamon branch of `_run_dialog` (the `is_cinnamon` path that today installs the applet): replace that install with `plan = plan_install(detect_channel(), "cinnamon"); if plan: show_install_dialog(plan, parent)`. Remove the imports of the alias UUID constants, `enable_extension_live`, `install_bundled_extension_if_needed`. Fix the module docstring's description of the sandboxed-channel behaviour (lines 1-30) to one paragraph pointing at `extension_install.py`. Add a Preferences → *Desktop integration* entry that calls `show_install_dialog(plan_install(detect_channel(), desktop))` when the plan isn't `None` — find the Preferences window in `ui/` and add one button beside the existing autostart controls; label `_("Set up the tray icon and Wayland capture…")`.

In `channel_detect.py` delete `_metadata_version` and `install_bundled_extension_if_needed` and the now-unused `json/shutil/tempfile` imports; shorten the module docstring to the `detect_channel` sentence. In `gnome_extension_setup.py` delete the three alias constants.

- [ ] **Step 5: Run the suite; grep for leftovers**

Run: `.venv/bin/pytest tests/ -q` — Expected: all pass.
Run: `grep -rn "install_bundled_extension_if_needed\|show_snap_connect_prompt\|SNAP_REAL_HOME\|TRAY_EXTENSION_UUID\|CLIPBOARD_EXTENSION_UUID\|WINDOW_CALLS_EXTENSION_UUID" src tests .github snapcraft.yaml` — Expected: only `.github/workflows/snap.yml` (Task 6 fixes it).

- [ ] **Step 6: Commit**

```bash
git add -A src/orcshot/ui src/orcshot/channel_detect.py src/orcshot/gnome_extension_setup.py tests/unit
git commit -m "First-run per channel: GNOME installs from EGO on Flatpak, redirects on Snap and Cinnamon; no home writes (#205)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Packaging and CI without the plug and the grant

**Files:**
- Modify: `snapcraft.yaml` (delete `plugs:` block lines ~75-79, the `- dot-local-share-gnome-shell` app plug, the `bundled-extensions` and `bundled-cinnamon-applets` parts)
- Modify: `org.orcshot.Orcshot.yaml` (delete line 9 `--filesystem=…extensions:create`, the `bundled-extensions` and `bundled-cinnamon-applets` modules at ~262-277)
- Modify: `.github/workflows/snap.yml` (delete the `snap connect` step and the "Trigger the app's real first-run extension-install path" step; add install-from-zip; add two assertions)
- Create: `scripts/pack-extension.sh`

**Interfaces:**
- Produces: `scripts/pack-extension.sh [out_dir]` → `dist/orcshot@orcshot.org.shell-extension.zip` (default `dist/`), exit non-zero on any failure. Used by CI here, by the EGO leaf in Task 8, by the user in Task 9.

- [ ] **Step 1: Write `scripts/pack-extension.sh`**

```bash
#!/usr/bin/env bash
# Packs the GNOME Shell extension into the zip layout `gnome-extensions pack`
# produces, without needing GNOME Shell on this machine (the snap build
# container and the Mint host both lack it). Output: <out>/orcshot@orcshot.org.shell-extension.zip
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)/src/orcshot/resources/gnome-shell-extensions/orcshot@orcshot.org"
OUT="${1:-$(cd "$(dirname "$0")/.." && pwd)/dist}"
UUID="orcshot@orcshot.org"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -r "$SRC/." "$STAGE/"
# Compile translations if the extension ships .po sources.
if [ -d "$STAGE/po" ]; then
  for po in "$STAGE"/po/*.po; do
    lang="$(basename "$po" .po)"
    mkdir -p "$STAGE/locale/$lang/LC_MESSAGES"
    msgfmt -o "$STAGE/locale/$lang/LC_MESSAGES/$UUID.mo" "$po"
  done
  rm -rf "$STAGE/po"
fi
python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); assert m["uuid"]=="orcshot@orcshot.org" and m["version-name"], "metadata.json incomplete"' "$STAGE/metadata.json"
mkdir -p "$OUT"
rm -f "$OUT/$UUID.shell-extension.zip"
( cd "$STAGE" && zip -qr "$OUT/$UUID.shell-extension.zip" . -x '*.po' )
echo "$OUT/$UUID.shell-extension.zip"
```

`chmod +x scripts/pack-extension.sh`. Run it: expected prints the zip path; `unzip -l dist/*.zip | grep -c "\.js$"` prints `4`. Add `dist/` to `.gitignore` if it isn't.

- [ ] **Step 2: `snapcraft.yaml`**

Delete the top-level `plugs:` block (`dot-local-share-gnome-shell: interface: personal-files …`), the `- dot-local-share-gnome-shell` line under `apps.orcshot.plugs`, and the `bundled-extensions` and `bundled-cinnamon-applets` parts entirely. Keep the `dbus-orcshot` slot. Run `review-tools` on the next CI build (Task 7 verifies the verdict is `dbus` only).

- [ ] **Step 3: Flatpak manifest**

Delete `  - --filesystem=~/.local/share/gnome-shell/extensions:create` and its comment, and the `bundled-extensions` / `bundled-cinnamon-applets` modules. Keep `--talk-name=org.gnome.Shell` and its comment, rewritten to: "the one org.gnome.Shell call left: first-run asks GNOME to install the extension from extensions.gnome.org (InstallRemoteExtension). Whether this can be narrowed to org.gnome.Shell.Extensions is spec 2026-09-11 verification item 2." Lint: `flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest org.orcshot.Orcshot.yaml` — expected: no errors.

- [ ] **Step 4: `.github/workflows/snap.yml`**

Delete the steps `Connect personal-files (...)` and `Trigger the app's real first-run extension-install path`. After `Install it locally (--dangerous, ...)` add:

```yaml
      - name: Install the extension the way a user would (from the packed zip, unconfined)
        run: |
          scripts/pack-extension.sh /tmp/ext
          gnome-extensions install --force /tmp/ext/orcshot@orcshot.org.shell-extension.zip || \
            { mkdir -p "$HOME/.local/share/gnome-shell/extensions"; unzip -q -o /tmp/ext/orcshot@orcshot.org.shell-extension.zip -d "$HOME/.local/share/gnome-shell/extensions/orcshot@orcshot.org"; }
          test -f "$HOME/.local/share/gnome-shell/extensions/orcshot@orcshot.org/extension.js"
```

(`gnome-extensions` needs the `gnome-shell` package, which a later step installs; move the `Install gnome-shell and headless deps` step above this one.) Replace `orcshot-tray@orcshot.org` with `orcshot@orcshot.org` in the `enable_extension` and `enabled-extensions` assertions, and `"orcshot-tray: extension enabled"` with `"orcshot: extension enabled"` in the log-marker step. After the "Confirm the already-running Shell loads the extension" step add:

```yaml
      - name: "Hello and one capture-rect round trip through the confined app (spec 2026-09-11 §6)"
        run: |
          export XDG_RUNTIME_DIR=/run/user/$(id -u)
          export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
          snap run --shell orcshot -c 'python3 - <<"PY"
          import os
          os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/%d/bus" % os.getuid()
          import gi; gi.require_version("Gio", "2.0")
          from gi.repository import Gio, GLib
          from orcshot.capture.shell_bridge import ShellBridge
          loop = GLib.MainLoop(); bridge = ShellBridge(); group = Gio.SimpleActionGroup()
          def on_bus(conn, name):
              conn.export_action_group("/org/orcshot/Orcshot", group)
              bridge.register(conn, "/org/orcshot/Orcshot", group)
          Gio.bus_own_name(Gio.BusType.SESSION, "org.orcshot.Orcshot", Gio.BusNameOwnerFlags.NONE, on_bus, None, None)
          def after_hello(caps):
              assert "capture-rect" in caps and "tray" in caps, caps
              print("Hello ->", sorted(caps), bridge.version_name)
              bridge.request_async("capture-rect", {"x": 0, "y": 0, "width": 8, "height": 8},
                                   lambda r: (print("capture-rect ok, %d bytes" % len(r["pngBytes"])), loop.quit()),
                                   lambda e: (print("capture-rect FAILED:", e), os._exit(1)), timeout_ms=15000)
          bridge.on_capabilities_changed(after_hello)
          GLib.timeout_add_seconds(30, lambda: (print("no Hello within 30s"), os._exit(1)))
          loop.run()
          PY'
```

- [ ] **Step 5: Push a branch and watch CI**

```bash
git add scripts/pack-extension.sh snapcraft.yaml org.orcshot.Orcshot.yaml .github/workflows/snap.yml .gitignore
git commit -m "Packaging without the personal-files plug or the Flatpak home grant; CI installs the extension from the packed zip (#205)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push -u origin HEAD
gh run watch --exit-status "$(gh run list --workflow snap.yml -L1 --json databaseId --jq '.[0].databaseId')"
```

Expected: `snap / verify` green, including the new round-trip step printing `Hello -> [...]` and `capture-rect ok`. `flatpak.yml` green. If `gnome-extensions install` on the runner needs a running Shell, the `unzip` fallback covers it — the assertion is on the file, not the command.

---

### Task 7: Live verification on the VMs, before publishing

**Files:**
- Modify: `VERIFICATION.md` (add the scenarios; record results)

**Interfaces:** consumes everything above; produces recorded evidence and, if anything fails, fixes committed before Task 8.

- [ ] **Step 1: `.deb` on Ubuntu 26.04 (GNOME 50, Wayland) — the regression gate**

Build: `dpkg-buildpackage -us -uc -b` (RELEASING.md step 4); copy `../orcshot_<ver>_all.deb` to the VM; `sudo apt install ./orcshot_<ver>_all.deb`; remove any per-user copies left from Task 4 Step 7 (`rm -rf ~/.local/share/gnome-shell/extensions/orcshot*`) so the system-wide copy is what loads; log out/in; start Orcshot from a terminal *inside the session*. Then, each triggered as the VM memory describes (`gdbus call … org.gtk.Actions.Activate tray-<mode> [] {}`) and screenshotted (`import -window …`):

| Feature | Expected evidence |
|---|---|
| Tray | panel icon present; menu opens with every item |
| Region select | Shell overlay + loupe; editor opens with the capture |
| Window picker | hover highlight from `list-windows`; clicked window raised and captured |
| Eyedropper (from the editor's colour dialog) | colour picked |
| Clipboard destination | `wl-paste --list-types` shows `image/png` |
| Health check | app stderr has no `org.gnome.Shell` errors; `gdbus introspect … /org/orcshot/Orcshot/Shell` lists Hello/GetRequest/Deliver |

Record each command and its output in `VERIFICATION.md` under a new "2026-09-11 extension delivery" heading.

- [ ] **Step 2: Same on Ubuntu 24.04 (GNOME 46)** — port 2223, `vboxuser`, session picker set to "Ubuntu" (Wayland), per the VM memory. Same table.

- [ ] **Step 3: Snap on 26.04** — install the CI artifact (`gh run download … -n orcshot-snap`), `sudo snap install --dangerous`. First-run must show the `snap-gnome` dialog with the §7 text (screenshot it). Install the extension as a stock user would: `sudo apt install gnome-shell-extension-manager`, open Extension Manager — *until Task 9 publishes it, install from the packed zip instead*: `gnome-extensions install --force dist/orcshot@orcshot.org.shell-extension.zip`, log out/in. The dialog must have closed itself on Hello (relaunch the app if the session restarted; the dialog is reachable from Preferences → Desktop integration). Same feature table. Then `review-tools.snap-review` on that `.snap`: expected `Errors` lists exactly `declaration-snap-v2:slots_connection:dbus-orcshot:dbus` and nothing else.

- [ ] **Step 4: Flatpak on 26.04** — `gh run download … -n orcshot-flatpak`, `flatpak install --user -y`. First-run must show the `flatpak-gnome` dialog; clicking *Install extension* must produce GNOME's own dialog (spec verification item 1: note whether GNOME also enabled it — check `gsettings get org.gnome.shell enabled-extensions` before Orcshot's own write). Until Task 9 publishes it GNOME's install will report the UUID unknown — record that result verbatim and install from the zip for the feature pass. Spec verification item 4: record which bus name the call needed on GNOME 50 (and repeat the click on 24.04 for GNOME 46).

- [ ] **Step 5: Spec verification items 2 and 3** — item 2: in a scratch copy of the manifest set `--talk-name=org.gnome.Shell.Extensions` instead, rebuild locally, click *Install extension*; record pass/fail. Item 3: after `gnome-extensions install` on a live session, does `journalctl --user -o cat | grep "orcshot: extension enabled"` appear without logout? Record; adjust the `snap-gnome` dialog's step 3 wording accordingly (spec §7 says "closes by itself when the extension is running" — true either way, but add "after you log out and back in" if item 3 says so).

- [ ] **Step 6: Commit the evidence**

```bash
git add VERIFICATION.md
git commit -m "Record the live verification of the extension delivery on 26.04 and 24.04 (#205)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Publishing pipeline — `channels.yaml`, `RELEASING.md`, scripts, records

**Files:**
- Modify: `.orclab/publish/channels.yaml` (two new leaves; `requirements:` on `snap`/`flatpak`)
- Modify: `RELEASING.md` (two steps after step 2; renumber)
- Create: `scripts/spices-sync.sh`
- Modify: `VERIFICATION.md` (store-side scenarios), `BACKLOG.md` (#205 update)

**Interfaces:**
- Consumes: `scripts/pack-extension.sh` (Task 6).
- Produces: `scripts/spices-sync.sh <path-to-spices-fork>` — copies the applet into `<fork>/orcshot@orcshot.org/files/orcshot@orcshot.org/`, bumps `metadata.json` `version`, runs `<fork>/validate-spice orcshot@orcshot.org`.

- [ ] **Step 1: `channels.yaml` leaves**

Append at the top level (siblings of `desktop:`), keeping the file's comment style:

```yaml
# The GNOME Shell extension is a second artifact with its own store: extensions.gnome.org
# (EGO). Flatpak installs it from there (InstallRemoteExtension) and GNOME keeps every
# per-user copy on EGO's version - so EGO owns the version once published, and this leaf is
# the only place the extension is ever uploaded from. Its RELEASING.md step is deliberately
# not a gate on the app channels: EGO review is human and unbounded (297 in the queue on
# 2026-09-11). Spec: docs/superpowers/specs/2026-09-11-snap-compliant-extension-delivery-design.md §5.
gnome-shell-extension:
  js:
    linux:
      ego:
        prepare: "scripts/pack-extension.sh dist"
        artifact: "dist/orcshot@orcshot.org.shell-extension.zip"
        # `gnome-extensions upload` ships with GNOME Shell 50 (verified); the Mint host has no
        # gnome-extensions at all, so this runs where GNOME Shell lives - the 26.04 VM over SSH
        # (see the VM registry memory) or a GNOME machine. The password file is the EGO
        # account password, 0600, outside the repo, never printed (secret-hygiene).
        action: "gnome-extensions upload --user artificialorctelligence --password-file ${XDG_CONFIG_HOME:-$HOME/.config}/orcshot/ego-password --accept-tos dist/orcshot@orcshot.org.shell-extension.zip"
        confirm:
          url: "https://extensions.gnome.org/extension-query/?search=orcshot"
        metrics: "curl -sf 'https://extensions.gnome.org/extension-query/?search=orcshot' | python3 -c 'import sys,json; [print(e[\"uuid\"], e.get(\"downloads\")) for e in json.load(sys.stdin)[\"extensions\"] if e[\"uuid\"]==\"orcshot@orcshot.org\"]'"
        requirements:
          - "Only when the extension changed since the last upload: every upload is a human
             review. Bump metadata.json's version-name in the same commit as the change."
          - "Runs on a machine with GNOME Shell >= 50 (`gnome-extensions help upload` must
             succeed there). Not the Mint host."
          - "One-time: an EGO account for artificialorctelligence, and the first submission
             accepted (the confirm URL lists orcshot@orcshot.org). Until then this reports
             an error from the upload, which is correct."
        issues:
          - "Review lag is unbounded and prioritises small diffs; the app tolerates one
             release of extension skew via the capability handshake, so the app release
             never waits on this."

cinnamon-applet:
  js:
    linux:
      spices:
        # Cinnamon Spices publishes by pull request to linuxmint/cinnamon-spices-applets; this
        # syncs the applet into a local fork checkout and opens the PR. The fork path is the
        # one machine-local input; it is a working directory, not a credential.
        action: "scripts/spices-sync.sh ${ORCSHOT_SPICES_FORK:-$HOME/projects/cinnamon-spices-applets} && cd ${ORCSHOT_SPICES_FORK:-$HOME/projects/cinnamon-spices-applets} && git checkout -B orcshot-$(dpkg-parsechangelog -l$OLDPWD/debian/changelog --show-field Version) master && git add orcshot@orcshot.org && git commit -qm \"orcshot@orcshot.org: update to $(dpkg-parsechangelog -l$OLDPWD/debian/changelog --show-field Version)\" && git push -q -u origin HEAD && gh pr create --fill --repo linuxmint/cinnamon-spices-applets"
        confirm:
          url: "https://cinnamon-spices.linuxmint.com/applets/view/orcshot@orcshot.org"
        requirements:
          - "Only when the applet changed. One-time: fork linuxmint/cinnamon-spices-applets to
             the artificialorctelligence account, clone it to $ORCSHOT_SPICES_FORK, and have
             the first PR (with info.json, screenshot.png, README.md) merged."
        issues:
          - "Spices' README (2026-09-08) forbids directing users to code outside Spices; the
             applet's README says it needs the Orcshot app from the Software Manager (Flathub)
             or the PPA - package channels, not downloads. Expect a reviewer question, not a
             refusal (NordVPN/ExpressVPN/KDE Connect companion applets are precedent)."
```

Under `desktop.python.linux`, replace `snap: {}` and `flatpak: {}` with:

```yaml
      snap:
        requirements:
          - "Depends on gnome-shell-extension.js.linux.ego: the snap installs no extension
             itself; its first-run sends the user to extensions.gnome.org (spec 2026-09-11 §4).
             Until orcshot@orcshot.org is listed there, the snap's GNOME-Wayland features run
             on the portal fallback only."
      flatpak:
        requirements:
          - "Depends on gnome-shell-extension.js.linux.ego: InstallRemoteExtension fetches from
             extensions.gnome.org and nowhere else. And on cinnamon-applet.js.linux.spices for
             the tray on Cinnamon."
```

Run `/orc-publish --dry-run` (or `python3 <orclab>/skills/orc-publish/scripts/run.py --root . --dry-run` — check the skill for the exact invocation) — expected: the two new leaves listed with their actions, `snap`/`flatpak` still "not yet actionable", no YAML error.

- [ ] **Step 2: `scripts/spices-sync.sh`**

```bash
#!/usr/bin/env bash
# Syncs the Cinnamon applet into a local checkout of the cinnamon-spices-applets fork in
# the layout Spices requires (UUID/files/UUID/...), bumps metadata.json's version to the
# app version, and runs Mint's own validator. Usage: scripts/spices-sync.sh <fork-checkout>
set -euo pipefail
FORK="${1:?path to the cinnamon-spices-applets fork checkout}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UUID="orcshot@orcshot.org"
SRC="$ROOT/src/orcshot/resources/cinnamon-applets/$UUID"
DEST="$FORK/$UUID/files/$UUID"
VERSION="$(dpkg-parsechangelog -l"$ROOT/debian/changelog" --show-field Version | sed 's/-[^-]*$//')"
test -x "$FORK/validate-spice" || { echo "not a cinnamon-spices-applets checkout: $FORK" >&2; exit 1; }
mkdir -p "$DEST"
rsync -a --delete "$SRC/" "$DEST/"
python3 - "$DEST/metadata.json" "$VERSION" <<'PY'
import json, sys
p, v = sys.argv[1], sys.argv[2]
m = json.load(open(p)); m["version"] = v
json.dump(m, open(p, "w"), indent=2); open(p, "a").write("\n")
PY
for f in info.json screenshot.png README.md; do
  test -e "$FORK/$UUID/$f" || echo "missing $UUID/$f - required for the first submission" >&2
done
( cd "$FORK" && ./validate-spice "$UUID" )
echo "synced $UUID at version $VERSION into $FORK"
```

`chmod +x`. Test against a scratch clone: `git clone --depth=1 https://github.com/linuxmint/cinnamon-spices-applets /tmp/spices && scripts/spices-sync.sh /tmp/spices` — expected: `validate-spice` passes or lists exactly the three missing first-submission files.

- [ ] **Step 3: `RELEASING.md`**

Insert after `## 2. Full test suite`:

```markdown
## 3. Upload the GNOME Shell extension to extensions.gnome.org (only if it changed)

The extension is a second artifact with its own store. Flatpak installs it from there, Snap sends
users there, and GNOME keeps every per-user copy on EGO's version - EGO owns the version once
published (spec 2026-09-11 §5). This step is **not a gate**: EGO review is human, unbounded, and
prioritises small diffs; the app tolerates one release of extension skew via the capability
handshake. Skip it entirely when `git diff <last-tag> -- src/orcshot/resources/gnome-shell-extensions` is empty.

**One-time setup:** an extensions.gnome.org account for `artificialorctelligence`, its password in
`~/.config/orcshot/ego-password` (chmod 0600, never printed, never committed), and the first
submission accepted by EGO's reviewers. Check: `curl -sf 'https://extensions.gnome.org/extension-query/?search=orcshot' | grep -q orcshot@orcshot.org`.

**Preconditions:** `metadata.json`'s `version-name` was bumped in the commit that changed the
extension. This runs on a machine with GNOME Shell ≥ 50 (the 26.04 VM over SSH), not the Mint host.

**Run:** /orc-publish gnome-shell-extension.js.linux.ego

## 4. Open the Cinnamon Spices pull request (only if the applet changed)

The tray applet for Cinnamon is published through Mint's own applet library, by PR to
`linuxmint/cinnamon-spices-applets`, reviewed by Mint's team on first submission and on every
update (same-day to ~18 days measured 2026-09-11). Not a gate, same reasoning as step 3. Skip when
`git diff <last-tag> -- src/orcshot/resources/cinnamon-applets` is empty.

**One-time setup:** a fork of `linuxmint/cinnamon-spices-applets` under `artificialorctelligence`,
cloned to `$ORCSHOT_SPICES_FORK` (default `~/projects/cinnamon-spices-applets`), with the first
PR merged - it needs `orcshot@orcshot.org/{info.json,screenshot.png,README.md}` beside `files/`.
Check: `curl -sf https://cinnamon-spices.linuxmint.com/applets/view/orcshot@orcshot.org >/dev/null`.

**Run:** /orc-publish cinnamon-applet.js.linux.spices

Then, by hand: watch the PR for reviewer questions.
```

Renumber every later step (old 3 → 5 … old 12 → 14) and every cross-reference in the file (`step 6`, `step 9`, "see step 10" etc. — grep for `step [0-9]` and fix each). Then:

```bash
python3 /home/direflail/.claude/plugins/cache/orclab/orclab/*/skills/orc-release/scripts/run.py --root . steps | python3 -c 'import sys,json; s=json.load(sys.stdin); print([x["number"] for x in s]); assert [x["number"] for x in s]==list(range(1,len(s)+1))'
```

Expected: `[1, 2, ..., 14]` and no warning lines.

- [ ] **Step 4: `VERIFICATION.md` store-side scenarios and `BACKLOG.md`**

Add four scenarios to `VERIFICATION.md`, each with its check command: `dbus` declaration granted (`snap info orcshot` shows a channel map); EGO listing (`extension-query` search); Spices listing (the view URL returns 200); Flathub manifest lints clean without the filesystem grant (`flatpak-builder-lint … manifest`).

In `BACKLOG.md` #205, append (do not rewrite):

```markdown
**Update <date> — implemented, not yet resolved.** Tasks 1–8 of
`docs/superpowers/plans/2026-09-11-snap-compliant-extension-delivery.md` landed: one extension,
inverted direction, per-channel first-run, packaging without the plug/grant, the two publishing
leaves. Live-verified on 26.04 and 24.04 (VERIFICATION.md). Open until the EGO first submission and
the Spices PR are accepted (plan Task 9), which is when the Snap and Flatpak first-run redirects
point at something real; #198 then proceeds with `/orc-package snap` and `flatpak`.
```

- [ ] **Step 5: Commit**

```bash
git add .orclab/publish/channels.yaml RELEASING.md scripts/spices-sync.sh VERIFICATION.md BACKLOG.md
git commit -m "Publishing pipeline for the extension (EGO) and applet (Spices): channels.yaml leaves, RELEASING.md steps 3-4 (#205)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: First submissions — user-gated, then the real Flatpak flow

**Files:**
- Modify: `src/orcshot/ui/extension_install.py` (`EGO_URL`, `SPICES_URL` → the real listing pages)
- Modify: `BACKLOG.md` (#205 resolution), `VERIFICATION.md`

**Interfaces:** consumes Task 6's zip and Task 8's scripts. Produces the two live listings the first-run dialogs depend on.

- [ ] **Step 1: EGO account and first upload — the user does this**

Tell the user exactly: create the account at `https://extensions.gnome.org/accounts/register/` (or sign in), then on the 26.04 VM:

```bash
scp -i ~/.ssh/orcshot_dev_vm -P 2222 dist/orcshot@orcshot.org.shell-extension.zip ubuntu2604@localhost:~/
ssh -i ~/.ssh/orcshot_dev_vm -p 2222 ubuntu2604@localhost 'gnome-extensions upload --user artificialorctelligence --accept-tos ~/orcshot@orcshot.org.shell-extension.zip'
```

(interactive password prompt — the user types it in their own terminal; never `--password`). Expected: the upload succeeds and the extension appears at `https://extensions.gnome.org/review/` awaiting review. Read `https://gjs.guide/extensions/review-guidelines/review-guidelines.html` once more before uploading and fix anything it flags (the 2026-09-11 read found nothing blocking: forks must be renamed — ours is; `version` is EGO's — we never read it; `session-modes` dropped — we have none).

- [ ] **Step 2: Spices first PR — the user does this**

Fork `linuxmint/cinnamon-spices-applets` on GitHub, clone to `~/projects/cinnamon-spices-applets`, then `scripts/spices-sync.sh ~/projects/cinnamon-spices-applets`, add `orcshot@orcshot.org/info.json` (`{"author": "artificialorctelligence", "license": "GPL-3.0"}`), a `screenshot.png` of the applet on a Mint panel (needs a Mint VM — spec verification item 7; if none exists, a Cinnamon session on the host, which is Mint, is acceptable for a screenshot), and `README.md`:

```markdown
# Orcshot tray

The panel icon and menu for [Orcshot](https://github.com/artificialorctelligence/orcshot), a
screenshot capture and annotation tool. Requires the Orcshot app, available from the Software
Manager (Flathub) or the Orcshot PPA; without it the applet shows an empty menu. GPL-3.0-or-later.
```

Read `.github/copilot-instructions.md` in that repo (Spices' own review-agent guide) and check the applet against it before opening the PR. Open the PR from the user's account; watch for reviewer questions.

- [ ] **Step 3: When EGO lists it — real Flatpak install flow**

On the 26.04 VM with the Flatpak from Task 7 installed and no per-user copy of the extension: first-run → *Install extension* → GNOME's dialog → *Install*. Expected: extension installed under `~/.local/share/gnome-shell/extensions/orcshot@orcshot.org`, `Hello` closes Orcshot's dialog, tray appears. Record in `VERIFICATION.md`. Then the Snap flow the same way via Extension Manager (`sudo apt install gnome-shell-extension-manager`, search "Orcshot", install). Update `EGO_URL` to the listing page (`https://extensions.gnome.org/extension/<numeric id>/orcshot/`) and, once Spices merges, `SPICES_URL` to `https://cinnamon-spices.linuxmint.com/applets/view/<id>`.

- [ ] **Step 4: Resolve #205**

Per `backlog-discipline`: add `(RESOLVED <date>)` to #205's title and a **Resolved** paragraph citing the two listings, the Flatpak flow evidence, and the `review-tools` verdict. Update #198: its Snap half is unblocked; next is `/orc-package snap` and `/orc-package flatpak` with the ingredients in Orclab, then the `dbus` declaration forum post on the first upload (plan for `beta`).

```bash
git add src/orcshot/ui/extension_install.py BACKLOG.md VERIFICATION.md
git commit -m "Point first-run at the live EGO and Spices listings; resolve BACKLOG #205

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review against the spec

- §1 architecture → Tasks 1, 3, 4. §2 contract (Hello/GetRequest/Deliver, kinds table, version-name) → Tasks 1, 2, 4. §3 app side (bridge, per-call selection, health check, deletions) → Tasks 2, 3, 5. §4 delivery per channel (deb install list, packing script, Flatpak manifest + InstallRemoteExtension, Snap manifest + EGO redirect, Cinnamon Spices redirect, deletions, CI) → Tasks 4, 5, 6. §5 pipeline (two leaves, RELEASING steps, spices-sync, version rule, requirements on snap/flatpak) → Task 8. §6 testing → unit tests in 1/2/3/5, CI in 6, live in 7 and 9, store-side scenarios in 8. §7 wording → Task 5 verbatim. Verification items 1–4 → Task 7 Steps 4–5; item 5 (Spices metrics) → noted in Task 8's leaf as absent, to be added when the index is checked; item 6 → Task 8 requirement states ≥ 50; item 7 → Task 9 Step 2.
- Names used consistently: `ShellBridge.register(connection, object_path, action_map)`, `request_async(kind, params, on_result, on_error, timeout_ms)`, `request(kind, params, timeout_ms)`, `has(kind)`, `on_capabilities_changed(cb)`, `version_name`; kinds and result keys as in the Global Constraints table; `EXTENSION_UUID`; `plan_install`/`show_install_dialog`/`request_gnome_install`; `_finish_gnome_setup(settings_backend, desktop, parent)`.
- Known judgment calls left to the implementer, stated where they arise: the four `capture.js` handler bodies are translations of existing methods (Task 4 Step 3 says "write each body out in full"); the Preferences entry's exact placement (Task 5 Step 4); moving the `gnome-shell` install step in CI (Task 6 Step 4).
