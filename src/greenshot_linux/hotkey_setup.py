"""Configuration of the four capture hotkeys (REQUIREMENTS.md's Global
Activation table, matching the Windows source's defaults) via
Cinnamon's custom keybinding system
(org.cinnamon.desktop.keybindings), rather than the app holding its
own raw X11 global key grabs - which would fight Cinnamon's own
default PrtScn-family bindings to its built-in screenshot tool.

Schema/path layout confirmed against this machine's real Cinnamon
settings before writing any of this (read-only introspection via
``gsettings``, never a write): reading
org.cinnamon.desktop.keybindings.media-keys showed Cinnamon's own
built-in screenshot actions and their key names (area-screenshot,
area-screenshot-clip, screenshot, screenshot-clip, window-screenshot,
window-screenshot-clip); reading the pre-existing custom keybindings
(org.cinnamon.desktop.keybindings.custom-keybinding, relocatable at
/org/cinnamon/desktop/keybindings/custom-keybindings/customN/) showed
this dev machine already had three - two of which are exactly the kind
of thing find_conflicts below needs to catch. Concretely, on this
machine, *every one* of our four default bindings already collided
with something real:
- Print            -> a custom "Area Screenshot" binding (shutter -s)
- <Alt>Print       -> Cinnamon's built-in window-screenshot action
- <Control>Print   -> Cinnamon's built-in screenshot-clip action
- <Shift>Print     -> a custom "Full Screenshot" binding (shutter -f)
This is real validation that conflict detection isn't hypothetical.

configure_hotkey/configure_all_hotkeys take an injectable settings
backend (ports-and-adapters, same shape as every other backend in this
project) so the logic is unit tested against a fake - see
SettingsBackend and the FakeSettingsBackend in the test file. The real
Gio.Settings-backed adapter (GioSettingsBackend) is written and
manually verified (read-only) against this machine's real schema, but
deliberately never invoked against the live system by anything in this
codebase or its tests: writing to the user's actual desktop keybinding
configuration is a real system settings change, not something to do as
a side effect of building the feature. The only place in this codebase
that's meant to ever call GioSettingsBackend for real is
ui/first_run_setup.py's confirmation dialog - triggered by the user
running the app and clicking through it themselves, not by anything
here.

find_conflicts deliberately only scans the schemas most likely to
actually hold a PrintScreen-family binding (media-keys' screenshot
keys, plus existing custom keybindings) rather than every gsettings
schema on the system - Cinnamon/Muffin have many keybinding schemas
(window manager actions, workspace switching, etc.) that are extremely
unlikely to ever be bound to a PrintScreen combo. This is a deliberate
scope boundary, not an oversight.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Protocol, Sequence, Set, Tuple, runtime_checkable

CUSTOM_LIST_SCHEMA = "org.cinnamon.desktop.keybindings"
CUSTOM_KEYBINDING_SCHEMA = "org.cinnamon.desktop.keybindings.custom-keybinding"
CUSTOM_KEYBINDING_PATH_TEMPLATE = "/org/cinnamon/desktop/keybindings/custom-keybindings/{slot}/"

MEDIA_KEYS_SCHEMA = "org.cinnamon.desktop.keybindings.media-keys"
_MEDIA_KEYS_SCREENSHOT_KEYS = (
    "area-screenshot", "area-screenshot-clip", "screenshot",
    "screenshot-clip", "window-screenshot", "window-screenshot-clip",
)


@dataclass(frozen=True)
class HotkeyBinding:
    name: str
    binding: str
    cli_flag: str


# REQUIREMENTS.md's Global Activation table, from the Windows source's
# ICoreConfiguration.cs defaults.
DEFAULT_HOTKEYS = (
    HotkeyBinding("Greenshot Linux - Region Capture", "Print", "--capture-region"),
    HotkeyBinding("Greenshot Linux - Window Capture", "<Alt>Print", "--capture-active-window"),
    HotkeyBinding("Greenshot Linux - Full Screen Capture", "<Control>Print", "--capture-full-screen"),
    HotkeyBinding("Greenshot Linux - Repeat Last Region", "<Shift>Print", "--capture-last-region"),
)


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


@dataclass(frozen=True)
class BindingConflict:
    """A key combo we want that's already claimed by something else.
    ``schema``/``path``/``key`` locate exactly the value that needs
    clearing to free the combo - see clear_conflict.
    """
    binding: str
    source: str
    schema: str
    path: str
    key: str


def find_conflicts(backend: SettingsBackend, binding: str, ignore_names: FrozenSet[str] = frozenset()) -> List[BindingConflict]:
    """Every existing binding (Cinnamon's own built-in screenshot
    actions, or an existing custom keybinding) that already claims
    ``binding``. ``ignore_names`` excludes custom keybindings by name -
    pass the names of our own DEFAULT_HOTKEYS so a hotkey we already
    installed ourselves doesn't get reported as a conflict against
    itself on a repeat run.
    """
    conflicts = []
    for key in _MEDIA_KEYS_SCREENSHOT_KEYS:
        if binding in backend.get_strv(MEDIA_KEYS_SCHEMA, "/", key):
            conflicts.append(BindingConflict(
                binding=binding, source=f"Cinnamon's built-in \"{key}\" shortcut",
                schema=MEDIA_KEYS_SCHEMA, path="/", key=key,
            ))
    for slot in backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list"):
        path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot=slot)
        name = backend.get_string(CUSTOM_KEYBINDING_SCHEMA, path, "name")
        if name in ignore_names:
            continue
        if binding in backend.get_strv(CUSTOM_KEYBINDING_SCHEMA, path, "binding"):
            conflicts.append(BindingConflict(
                binding=binding, source=f"existing custom shortcut \"{name}\"",
                schema=CUSTOM_KEYBINDING_SCHEMA, path=path, key="binding",
            ))
    return conflicts


def clear_conflict(backend: SettingsBackend, conflict: BindingConflict) -> None:
    """Frees up ``conflict``'s key combo by clearing just that specific
    binding field. Whatever it belonged to - a Cinnamon built-in action,
    or another custom keybinding's name/command - is left otherwise
    intact, just no longer bound to this key combo.
    """
    backend.set_strv(conflict.schema, conflict.path, conflict.key, [])


def configure_hotkey(backend: SettingsBackend, name: str, binding: str, command: str) -> bool:
    """Idempotently ensures a Cinnamon custom keybinding exists for
    ``binding`` -> ``command``, named ``name``. Returns True if a new
    binding was added, False if one already existed (matched by name)
    and nothing changed. Does not check for conflicts with *other*
    bindings first - call find_conflicts (and clear_conflict, if the
    caller decides to overwrite) before this.
    """
    custom_list = list(backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list"))

    for slot in custom_list:
        path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot=slot)
        if backend.get_string(CUSTOM_KEYBINDING_SCHEMA, path, "name") == name:
            return False

    slot = next_available_slot(custom_list)
    path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot=slot)
    backend.set_string(CUSTOM_KEYBINDING_SCHEMA, path, "name", name)
    backend.set_string(CUSTOM_KEYBINDING_SCHEMA, path, "command", command)
    backend.set_strv(CUSTOM_KEYBINDING_SCHEMA, path, "binding", [binding])
    backend.set_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list", custom_list + [slot])
    return True


def configure_all_hotkeys(
    backend: SettingsBackend, executable: str,
    bindings: Sequence[HotkeyBinding] = DEFAULT_HOTKEYS, skip: FrozenSet[str] = frozenset(),
) -> Dict[str, bool]:
    """Configures every binding in ``bindings`` whose .binding isn't in
    ``skip`` - the caller resolves conflicts (e.g. a confirmation
    dialog via find_conflicts/clear_conflict) and passes which key
    combos to leave alone. Returns {name: True/False} for whether each
    was newly added.
    """
    results = {}
    for hb in bindings:
        if hb.binding in skip:
            results[hb.name] = False
            continue
        results[hb.name] = configure_hotkey(backend, hb.name, hb.binding, f"{executable} {hb.cli_flag}")
    return results


def check_all_conflicts(
    backend: SettingsBackend, bindings: Sequence[HotkeyBinding] = DEFAULT_HOTKEYS,
) -> Dict[str, List[BindingConflict]]:
    """Every binding in ``bindings`` mapped to its conflict list (empty
    if none) - the one-shot check ui/first_run_setup.py's dialog needs
    to decide what to ask the user about before calling
    configure_all_hotkeys. Automatically excludes each binding's own
    name from its own conflict search (see find_conflicts'
    ignore_names), so a hotkey this app already installed on a
    previous run never shows up as colliding with itself.
    """
    ignore_names = {hb.name for hb in bindings}
    return {hb.name: find_conflicts(backend, hb.binding, ignore_names=ignore_names) for hb in bindings}


def resolve_hotkey_choices(
    enabled_names: FrozenSet[str], conflicts: Dict[str, List[BindingConflict]],
    bindings: Sequence[HotkeyBinding] = DEFAULT_HOTKEYS,
) -> Tuple[Set[str], List[BindingConflict]]:
    """Turns a first-run dialog's per-binding checkbox state into what
    configure_all_hotkeys/clear_conflict need: ``skip`` (the .binding
    key combos to leave alone - anything not in ``enabled_names``) and
    ``to_clear`` (the conflicts to actually free up - only for bindings
    that *are* enabled, since checking "enable" on a binding that had a
    conflict is how the dialog expresses "yes, overwrite it").
    """
    skip = {hb.binding for hb in bindings if hb.name not in enabled_names}
    to_clear = []
    for hb in bindings:
        if hb.name in enabled_names:
            to_clear.extend(conflicts.get(hb.name, []))
    return skip, to_clear


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
