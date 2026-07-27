"""First-run auto-configuration of the region-capture hotkey via
Cinnamon's custom keybinding system (org.cinnamon.desktop.keybindings),
rather than the app holding its own raw X11 global key grab - which
would fight Cinnamon's own default PrtScn binding to its built-in
screenshot tool.

Schema/path layout confirmed against this machine's real Cinnamon
settings before writing any of this: a pre-existing custom binding
(`<Shift>Print` -> `shutter -f`) showed the exact relocatable-schema id
(`org.cinnamon.desktop.keybindings.custom-keybinding`) and dconf path
layout (`/org/cinnamon/desktop/keybindings/custom-keybindings/customN/`),
read via `dconf dump`/`gsettings get` - read-only introspection, not a
system settings change.

Scope: only PrintScreen -> region capture is wired here, since region
capture is the only capture mode that exists so far. REQUIREMENTS.md's
Alt/Ctrl/Shift+PrintScreen variants need Window/Full-screen/Last-region
capture modes that aren't built yet - adding their bindings is just
more calls to configure_hotkey once those exist, not a design change.

configure_hotkey takes an injectable settings backend (ports-and-
adapters, same shape as every other backend in this project) so the
logic is unit tested against a fake - see SettingsBackend and
FakeSettingsBackend. The real Gio.Settings-backed adapter
(GioSettingsBackend) is written and manually verified against this
machine's real schema, but deliberately never invoked against the live
system by anything in this codebase or its tests: writing to the
user's actual desktop keybinding configuration is a real system
settings change, not something to do as a side effect of building the
feature. Wiring first-run auto-configuration to actually call it (with
the "one-time user confirmation" REQUIREMENTS.md specifies) is future
UI work, not part of this module.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

CUSTOM_LIST_SCHEMA = "org.cinnamon.desktop.keybindings"
CUSTOM_KEYBINDING_SCHEMA = "org.cinnamon.desktop.keybindings.custom-keybinding"
CUSTOM_KEYBINDING_PATH_TEMPLATE = "/org/cinnamon/desktop/keybindings/custom-keybindings/{slot}/"

HOTKEY_NAME = "Greenshot Linux - Region Capture"
HOTKEY_BINDING = "Print"


def next_available_slot(existing_slots: Sequence[str]) -> str:
    """The first customN slot not already in ``existing_slots`` (e.g.
    ["custom0", "custom2"] -> "custom1", since custom1 is the gap).
    """
    used = set(existing_slots)
    n = 0
    while f"custom{n}" in used:
        n += 1
    return f"custom{n}"


@runtime_checkable
class SettingsBackend(Protocol):
    def get_strv(self, schema: str, path: str, key: str) -> list:
        ...

    def set_strv(self, schema: str, path: str, key: str, value: list) -> None:
        ...

    def get_string(self, schema: str, path: str, key: str) -> str:
        ...

    def set_string(self, schema: str, path: str, key: str, value: str) -> None:
        ...


def configure_hotkey(backend: SettingsBackend, command: str) -> bool:
    """Idempotently ensure a Cinnamon custom keybinding exists for
    PrintScreen -> region capture, running ``command``. Returns True if
    a new binding was added, False if one already existed (matched by
    name) and nothing changed.
    """
    custom_list = list(backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list"))

    for slot in custom_list:
        path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot=slot)
        if backend.get_string(CUSTOM_KEYBINDING_SCHEMA, path, "name") == HOTKEY_NAME:
            return False

    slot = next_available_slot(custom_list)
    path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot=slot)
    backend.set_string(CUSTOM_KEYBINDING_SCHEMA, path, "name", HOTKEY_NAME)
    backend.set_string(CUSTOM_KEYBINDING_SCHEMA, path, "command", command)
    backend.set_strv(CUSTOM_KEYBINDING_SCHEMA, path, "binding", [HOTKEY_BINDING])
    backend.set_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list", custom_list + [slot])
    return True


class GioSettingsBackend:
    """The real adapter - manually verified against this machine's
    actual Cinnamon gsettings schema, but not exercised by any test or
    calling code in this project (see the module docstring).
    """

    def _settings(self, schema: str, path: str):
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        if path == "/":
            return Gio.Settings.new(schema)
        return Gio.Settings.new_with_path(schema, path)

    def get_strv(self, schema: str, path: str, key: str) -> list:
        return list(self._settings(schema, path).get_strv(key))

    def set_strv(self, schema: str, path: str, key: str, value: list) -> None:
        self._settings(schema, path).set_strv(key, value)

    def get_string(self, schema: str, path: str, key: str) -> str:
        return self._settings(schema, path).get_string(key)

    def set_string(self, schema: str, path: str, key: str, value: str) -> None:
        self._settings(schema, path).set_string(key, value)
