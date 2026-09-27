"""CI: prove the extension<->app contract end to end under the real
sandbox (spec 2026-09-11 §6). Runs *inside* the confined app environment
(`snap run --shell orcshot -c 'python3 -'` / `flatpak run --command=python3
org.orcshot.Orcshot -`, fed on stdin because neither sandbox can read the
checkout), owns org.orcshot.Orcshot the way the real app does, and waits
for the headless GNOME Shell's extension to say Hello, then asks it for
list-windows - a Shell-privileged call (global.get_window_actors()) that
needs no user interaction, unlike every *interactive* capture kind, which
ends in the Shell-side destination menu waiting for a click - and checks a
JSON list comes back.

Then a second phase for headless capture (BACKLOG #225): the extension
watches a second bus name, org.orcshot.Orcshot.Headless, so a scripted
`orcshot --capture-to` can reach it even while the tray app owns the main
one. This phase owns that name the same way, checks its Hello announces
the allowlist and nothing interactive, and asks for capture-rect-headless
- the one capture kind that returns bytes instead of waiting for a human.

Exit 0 only if every phase passed. What this still cannot prove is in
BACKLOG #225: a headless GNOME Shell has no real compositor behind it, so
a successful grab here does not establish that the same call behaves
correctly against real outputs from a connection with no visible UI.
"""

import os
import sys

os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/%d/bus" % os.getuid())

import gi  # noqa: E402

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from orcshot.capture.shell_bridge import (  # noqa: E402
    HEADLESS_ACTIONS_PATH,
    HEADLESS_BUS_NAME,
    HEADLESS_SHELL_OBJECT_PATH,
    ShellBridge,
)

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
        start_headless_phase()

    bridge.request_async("list-windows", {}, on_result, lambda e: fail(f"list-windows: {e}"), timeout_ms=20000)


# ---- phase 2: the headless bus name (BACKLOG #225) ------------------

headless_bridge = ShellBridge()
headless_group = Gio.SimpleActionGroup()

# Every kind that ends in pickDestinationAsync, i.e. waits for a human.
# None of them may be reachable over the headless bus: that bus exists
# for callers with nobody to click a menu, so an interactive kind
# appearing here would be a real regression, not a cosmetic one.
INTERACTIVE_KINDS = ("region-select", "window-picker", "eyedropper", "capture-rect")


def on_headless_bus(conn, name):
    conn.export_action_group(HEADLESS_ACTIONS_PATH, headless_group)
    headless_bridge.register(
        conn, HEADLESS_ACTIONS_PATH, headless_group, shell_object_path=HEADLESS_SHELL_OBJECT_PATH
    )
    print("owning", name, "- waiting for its Hello", flush=True)


def after_headless_hello(caps):
    if "capture-rect-headless" not in caps:
        fail(f"headless bus did not announce capture-rect-headless: {sorted(caps)}")
    reachable = [kind for kind in INTERACTIVE_KINDS if kind in caps]
    if reachable:
        fail(f"interactive kinds reachable on the headless bus: {reachable}")
    if "tray" in caps:
        fail("the headless bus must not offer the tray")
    print("headless Hello ->", sorted(caps), flush=True)

    def on_png(result):
        png = result.get("pngBytes")
        if not png:
            fail("capture-rect-headless returned no bytes")
        if bytes(png[:8]) != b"\x89PNG\r\n\x1a\n":
            fail("capture-rect-headless returned something that is not a PNG")
        print(f"capture-rect-headless ok, {len(png)} bytes of real PNG", flush=True)
        loop.quit()

    # A small rect at the origin: every stage has one, whatever the
    # headless Shell decided its size was.
    headless_bridge.request_async(
        "capture-rect-headless", {"x": 0, "y": 0, "width": 16, "height": 16},
        on_png, lambda e: fail(f"capture-rect-headless: {e}"), timeout_ms=20000,
    )


def start_headless_phase():
    headless_bridge.on_capabilities_changed(after_headless_hello)
    Gio.bus_own_name(
        Gio.BusType.SESSION, HEADLESS_BUS_NAME, Gio.BusNameOwnerFlags.NONE, on_headless_bus, None,
        lambda c, n: fail(f"lost {HEADLESS_BUS_NAME} - is another headless capture running?"),
    )
    GLib.timeout_add_seconds(45, lambda: fail("no Hello on the headless bus within 45s"))


bridge.on_capabilities_changed(after_hello)
Gio.bus_own_name(Gio.BusType.SESSION, "org.orcshot.Orcshot", Gio.BusNameOwnerFlags.NONE, on_bus, None,
                 lambda c, n: fail("lost the bus name - is a real orcshot running?"))
GLib.timeout_add_seconds(45, lambda: fail("no Hello within 45s"))
loop.run()
sys.exit(0)
