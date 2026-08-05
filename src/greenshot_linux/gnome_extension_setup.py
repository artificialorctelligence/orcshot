"""Enabling the bundled window-calls GNOME Shell extension (see
THIRD_PARTY_NOTICES.md) - the window-capture equivalent of what
hotkey_setup.py does for Cinnamon keybindings: a real write to the
user's desktop settings that must only ever happen from their own
confirmation click, never as a side effect of installing or running
the app. The .deb only places the extension's files on disk (see
debian/greenshot-linux.install); this module is what actually flips it
on, and only ui/first_run_setup.py (or later, a Preferences action) is
meant to call enable_window_calls_extension for real.

Reuses hotkey_setup.SettingsBackend/GioSettingsBackend rather than
inventing a parallel settings adapter - it's already schema-agnostic
(get_strv/set_strv take schema/path/key), so there's nothing
Cinnamon-specific about reusing it here for a GNOME schema instead.

Enabling alone isn't enough to make the extension usable in the
current process - confirmed live that GNOME Shell caches the imported
JS module and won't pick up on a freshly-installed extension until the
next full login, not just a disable/enable toggle (see
REQUIREMENTS.md's Wayland window-picker section) - hence the "log out
and back in" messaging in the first-run dialog rather than claiming
this takes effect immediately.
"""

from __future__ import annotations

EXTENSION_UUID = "window-calls@domandoman.xyz"
_SHELL_SCHEMA = "org.gnome.shell"
_ENABLED_EXTENSIONS_KEY = "enabled-extensions"


def gnome_shell_present() -> bool:
    """Whether this looks like a GNOME Shell session at all - a
    read-only schema lookup, no Gio.Settings object constructed, same
    "check first, never assume" precedent as
    hotkey_setup.cinnamon_keybindings_available. Callers must check
    this before calling enable_window_calls_extension for real."""
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    return Gio.SettingsSchemaSource.get_default().lookup(_SHELL_SCHEMA, True) is not None


def enabled_extensions_after_adding(current: list, uuid: str) -> list:
    """Pure: the enabled-extensions list with ``uuid`` added, without
    duplicating it if already present. Order of the rest is preserved."""
    if uuid in current:
        return list(current)
    return list(current) + [uuid]


def enable_window_calls_extension(settings_backend) -> None:
    """The real write. Idempotent - safe to call even if already
    enabled."""
    current = settings_backend.get_strv(_SHELL_SCHEMA, "/", _ENABLED_EXTENSIONS_KEY)
    updated = enabled_extensions_after_adding(current, EXTENSION_UUID)
    if updated != current:
        settings_backend.set_strv(_SHELL_SCHEMA, "/", _ENABLED_EXTENSIONS_KEY, updated)
