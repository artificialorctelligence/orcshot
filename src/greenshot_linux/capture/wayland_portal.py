"""Screen capture via the XDG Desktop Portal's Screenshot interface
(org.freedesktop.portal.Screenshot), for sessions where a direct
root-window read doesn't work - Wayland's compositor blocks that by
design as a core anti-spying security feature, confirmed live: on
Ubuntu 26.04/GNOME, X11CaptureBackend.grab() (via XWayland) returned a
fully black image instead of raising or erroring.

Screenshot, not ScreenCast+PipeWire: this app needs one-shot capture,
not a video stream, and Screenshot is the portal purpose-built for
exactly that - confirmed against the real interface spec
(flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Screenshot.html,
v3) rather than assumed. No new dependency beyond Gio, already used
throughout this project for GSettings (hotkey_setup.py).

The portal call is inherently async: Screenshot() returns a Request
object path immediately, but the actual result only arrives later, as
a Response signal on that path - fired once the user's permission
dialog resolves (if one appears at all; confirmed live that calling
the portal from an unsandboxed process didn't show one here, unlike
what a Flatpak-sandboxed caller would typically get). Bridged to a
synchronous call via a nested GLib.MainLoop, the same category of
trick Gtk.Dialog.run() already relies on elsewhere in this codebase -
callers see a plain blocking function, not a callback.

Confirmed live against the real portal backend (Mutter, Ubuntu 26.04)
before writing this module: a raw prototype of this exact call
sequence returned response_code=0 and a real, valid PNG uri
(file:///home/.../Pictures/Screenshot.png, 1366x768 RGBA) - not
assumed from the spec alone.
"""

from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
SCREENSHOT_INTERFACE = "org.freedesktop.portal.Screenshot"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"

# org.freedesktop.portal.Screenshot's target is a single value, not a
# bitmask (confirmed against the v3 spec) - Screen/Window/Area/
# ActiveWindow are mutually exclusive per call, not combinable.
TARGET_SCREEN = 1
TARGET_WINDOW = 2
TARGET_AREA = 4
TARGET_ACTIVE_WINDOW = 8

# Response signal's response code (org.freedesktop.portal.Request):
# 0 = success, 1 = user cancelled, 2 = other/unspecified error.
_RESPONSE_SUCCESS = 0
_RESPONSE_CANCELLED = 1

_handle_token_counter = 0


class PortalRequestCancelled(RuntimeError):
    """The user dismissed the permission/selection dialog."""


class PortalRequestFailed(RuntimeError):
    """The portal reported failure for a reason other than cancellation."""


class PortalRequestTimedOut(RuntimeError):
    """No Response signal arrived within the timeout - the dialog may
    still be open, waiting on the user, or the portal service may be
    unavailable entirely."""


def _next_handle_token() -> str:
    # Must be a valid D-Bus object path element (alphanumeric/underscore
    # only) and unique enough not to collide with a previous, possibly
    # still-pending request from this same process.
    global _handle_token_counter
    _handle_token_counter += 1
    return f"greenshot_linux_{_handle_token_counter}"


def _parse_response(response_code: int, results: dict) -> str:
    """The pure part of handling a Request::Response signal - split out
    from request_screenshot so response-code handling has unit coverage
    that doesn't need a real portal call to exercise."""
    if response_code == _RESPONSE_CANCELLED:
        raise PortalRequestCancelled("screenshot request was cancelled")
    if response_code != _RESPONSE_SUCCESS:
        raise PortalRequestFailed(f"screenshot portal returned response code {response_code}")
    return results["uri"]


def request_screenshot(target: int = TARGET_SCREEN, interactive: bool = False, timeout_seconds: int = 120) -> str:
    """Blocks until the portal responds, returns the file:// URI it
    hands back. Raises PortalRequestCancelled/PortalRequestFailed/
    PortalRequestTimedOut on anything other than success.

    The returned path is a normal, fully-accessible file for an
    unsandboxed caller like this app (confirmed live: a real path
    under ~/Pictures, not the read-only /run/user/<uid>/doc/... FUSE
    mount a Flatpak-sandboxed caller would get from the document
    portal) - safe to load directly, no special handling needed.
    """
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    options = {
        "handle_token": GLib.Variant("s", _next_handle_token()),
        "interactive": GLib.Variant("b", interactive),
        "target": GLib.Variant("u", target),
    }

    reply = bus.call_sync(
        PORTAL_BUS_NAME,
        PORTAL_OBJECT_PATH,
        SCREENSHOT_INTERFACE,
        "Screenshot",
        GLib.Variant("(sa{sv})", ("", options)),
        GLib.VariantType("(o)"),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )
    (handle_path,) = reply.unpack()

    result = {}
    loop = GLib.MainLoop()

    def on_response(connection, sender_name, object_path, interface_name, signal_name, parameters, user_data):
        result["response_code"], result["results"] = parameters.unpack()
        loop.quit()

    subscription_id = bus.signal_subscribe(
        PORTAL_BUS_NAME, REQUEST_INTERFACE, "Response", handle_path,
        None, Gio.DBusSignalFlags.NONE, on_response, None,
    )
    timeout_id = GLib.timeout_add_seconds(timeout_seconds, loop.quit)
    try:
        loop.run()
    finally:
        bus.signal_unsubscribe(subscription_id)
        GLib.source_remove(timeout_id)

    if "response_code" not in result:
        raise PortalRequestTimedOut(f"no response from the screenshot portal within {timeout_seconds}s")

    return _parse_response(result["response_code"], result["results"])
