"""CI: prove the extension<->app contract end to end under the real
sandbox (spec 2026-09-11 §6). Runs *inside* the confined app environment
(`snap run --shell orcshot -c 'python3 -'` / `flatpak run --command=python3
org.orcshot.Orcshot -`, fed on stdin because neither sandbox can read the
checkout), owns org.orcshot.Orcshot the way the real app does, and waits
for the headless GNOME Shell's extension to say Hello, then asks it for
list-windows - a Shell-privileged call (global.get_window_actors()) that
needs no user interaction, unlike every capture kind, which ends in the
Shell-side destination menu waiting for a click - and checks a JSON list
comes back. Exit 0 only if both happened.
"""

import os
import sys

os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/%d/bus" % os.getuid())

import gi  # noqa: E402

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from orcshot.capture.shell_bridge import ShellBridge  # noqa: E402

loop = GLib.MainLoop()
bridge = ShellBridge()
group = Gio.SimpleActionGroup()


def fail(msg):
    print("FAIL:", msg, flush=True)
    os._exit(1)


def on_bus(conn, name):
    conn.export_action_group("/org/orcshot/Orcshot", group)
    bridge.register(conn, "/org/orcshot/Orcshot", group)
    print("owning", name, "- waiting for Hello", flush=True)


def after_hello(caps):
    if "list-windows" not in caps or "tray" not in caps:
        fail(f"unexpected capabilities {sorted(caps)}")
    print("Hello ->", sorted(caps), "version-name", bridge.version_name, flush=True)

    def on_result(result):
        import json
        windows = json.loads(result["windows"])
        if not isinstance(windows, list):
            fail(f"list-windows returned {type(windows).__name__}")
        print(f"list-windows ok, {len(windows)} windows delivered", flush=True)
        loop.quit()

    bridge.request_async("list-windows", {}, on_result, lambda e: fail(f"list-windows: {e}"), timeout_ms=20000)


bridge.on_capabilities_changed(after_hello)
Gio.bus_own_name(Gio.BusType.SESSION, "org.orcshot.Orcshot", Gio.BusNameOwnerFlags.NONE, on_bus, None,
                 lambda c, n: fail("lost the bus name - is a real orcshot running?"))
GLib.timeout_add_seconds(45, lambda: fail("no Hello within 45s"))
loop.run()
sys.exit(0)
