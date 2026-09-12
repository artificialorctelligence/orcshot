"""Enabling this project's GNOME Shell extension (orcshot@orcshot.org -
one extension carrying tray, capture and window-calls since the
2026-09-11 spec; the window-calls part is a third-party fork, see
THIRD_PARTY_NOTICES.md) - the equivalent of what hotkey_setup.py does for
Cinnamon keybindings: a real write to the user's desktop settings that
must only ever happen from their own confirmation click, never as a
side effect of installing or running the app. The .deb only places the
extensions' files on disk (see debian/orcshot.install); this
module is what actually flips one on, and only ui/first_run_setup.py
(or later, a Preferences action) is meant to call enable_extension for
real.

Reuses hotkey_setup.SettingsBackend/GioSettingsBackend rather than
inventing a parallel settings adapter - it's already schema-agnostic
(get_strv/set_strv take schema/path/key), so there's nothing
Cinnamon-specific about reusing it here for a GNOME schema instead.

Enabling has two distinct halves, and both are needed (task #150
follow-up - see enable_extension_live's own docstring for the live-
reproduced bug that revealed this): enable_extension's gsettings write
makes the setting *persist* for a future login, but does not reliably
make the *current* Shell process actually activate the extension -
enable_extension_live's direct EnableExtension D-Bus call is what
does that. This is separate from GNOME Shell's own, different, already
-documented caching gap (a Shell process that already loaded an
extension's JS module once this session keeps running that same
module even after the file on disk changes - see REQUIREMENTS.md's
extension-reload-caching note) - that one genuinely has no in-session
fix and does need a logout/login; a *never-before-loaded* extension,
this module's whole subject, does not.
"""

from __future__ import annotations

import json
from pathlib import Path

EXTENSION_UUID = "orcshot@orcshot.org"
# Transitional aliases - Task 5 of the 2026-09-11 plan deletes these with
# their last callers in ui/first_run_setup.py.
WINDOW_CALLS_EXTENSION_UUID = EXTENSION_UUID
CLIPBOARD_EXTENSION_UUID = EXTENSION_UUID
TRAY_EXTENSION_UUID = EXTENSION_UUID
_SHELL_SCHEMA = "org.gnome.shell"
_ENABLED_EXTENSIONS_KEY = "enabled-extensions"


def gnome_shell_present() -> bool:
    """Whether this looks like a GNOME Shell session at all - a
    read-only schema lookup, no Gio.Settings object constructed, same
    "check first, never assume" precedent as
    hotkey_setup.cinnamon_keybindings_available. Callers must check
    this before calling enable_extension for real.

    get_default() itself can return None, not just fail to contain the
    schema - confirmed live under Snap's strict confinement, where
    there is no default schema source in the sandbox's mount namespace
    at all. Treated the same as "schema not found" rather than letting
    the AttributeError propagate - this function's whole contract is a
    boolean answer to "is GNOME Shell present," and a sandboxed
    environment with zero schema sources genuinely has no GNOME Shell
    integration available, which is exactly what False already means
    here."""
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    source = Gio.SettingsSchemaSource.get_default()
    if source is None:
        return False
    return source.lookup(_SHELL_SCHEMA, True) is not None


def extensions_to_enable(is_gnome_wayland: bool) -> list:
    """One extension now carries tray, capture and window-calls (spec
    2026-09-11 section 2); the tray is wanted on X11 too, so the session
    type no longer changes the answer. Kept as a function so first-run
    setup's call site is unchanged."""
    return [EXTENSION_UUID]


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


def enabled_extensions_after_adding(current: list, uuid: str) -> list:
    """Pure: the enabled-extensions list with ``uuid`` added, without
    duplicating it if already present. Order of the rest is preserved."""
    if uuid in current:
        return list(current)
    return list(current) + [uuid]


def enable_extension(settings_backend, uuid: str) -> None:
    """The real write, for any bundled extension's UUID. Idempotent -
    safe to call even if already enabled. Only makes the setting
    persist for the *next* login on its own - see enable_extension_live
    for what actually activates it this session, and why both are
    needed."""
    current = settings_backend.get_strv(_SHELL_SCHEMA, "/", _ENABLED_EXTENSIONS_KEY)
    updated = enabled_extensions_after_adding(current, uuid)
    if updated != current:
        settings_backend.set_strv(_SHELL_SCHEMA, "/", _ENABLED_EXTENSIONS_KEY, updated)


def enable_extension_live(uuid: str) -> None:
    """Asks the *running* Shell to actually activate ``uuid`` right
    now, via its own org.gnome.Shell.Extensions.EnableExtension D-Bus
    method - not exercised by any test, real-system-only, same
    category as GioSettingsBackend itself (task #150 follow-up).

    .deb channel only, since the 2026-09-11 spec: this is the one
    remaining app->org.gnome.Shell call, and it is AppArmor-denied under
    a strict snap (#184) and unnecessary under Flatpak, where GNOME's
    own InstallRemoteExtension enables what it installs. On the .deb
    there is no sandbox, and the live-reproduced bug below is why it
    stays there rather than being deleted with the rest. Task 7 of the
    plan decides, on the VM, whether the gsettings write alone now
    suffices; delete this then if it does.

    This turned out to be the missing piece behind a long-standing,
    previously unexplained bug (the 2026-08-15 "extension-enable
    checkbox doesn't persist" finding elsewhere in this project, and a
    fresh recurrence the same night this function was added): writing
    enabled-extensions via enable_extension alone correctly persists
    the setting - confirmed live by reading the raw gsettings key -
    but does not reliably make Shell actually load/activate the
    extension, even on a genuinely fresh boot that's never touched
    this UUID before (which rules out a live change-notification
    timing explanation - a cold boot reads the setting fresh, there's
    no notification to race). The exact same UUID, in the exact same
    already-correct gsettings state, went from GetExtensionInfo
    reporting state=INITIALIZED/enabled=false to state=ENABLED/
    enabled=true immediately and reliably once asked for directly via
    this method instead - live-confirmed, not assumed from the method
    merely existing.

    Called in addition to enable_extension, not instead of it: the
    gsettings write is still what makes the setting survive a future
    login on its own (this method only affects the current session);
    this is what makes it actually work *this* session too, matching
    what this project's own first-run dialog copy already promises
    (no logout required - see REQUIREMENTS.md's "no longer an opt-in
    checkbox" section for why that promise is accurate for the
    underlying capture code, and this fix for why it's now accurate
    for the extension actually being live too).
    """
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    proxy = Gio.DBusProxy.new_for_bus_sync(
        Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None,
        # Deliberately "org.gnome.Shell", not the narrower
        # "org.gnome.Shell.Extensions" (tried and reverted, final-review
        # finding, 2026-08-31 - see org.orcshot.Orcshot.yaml's own
        # --talk-name comment for the live CI evidence). The narrower name
        # is not an owned/activatable bus name on a real, plain GNOME
        # Shell (GNOME 46.2, confirmed live in this project's own
        # flatpak/verify CI run): dialing it triggers D-Bus service
        # activation instead of routing to the already-running Shell
        # process, and there's no .service file to activate, so the call
        # fails outright with a real, named error
        # ("Failed to execute program org.gnome.Shell.Extensions: No such
        # file or directory") - the exact live-verification the review
        # itself flagged as missing, now done.
        "org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Extensions", None,
    )
    proxy.call_sync("EnableExtension", GLib.Variant("(s)", (uuid,)), Gio.DBusCallFlags.NONE, -1, None)
