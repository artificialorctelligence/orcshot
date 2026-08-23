"""Configuration of the four capture hotkeys (REQUIREMENTS.md's Global
Activation table, matching the Windows source's defaults) via each
desktop's own custom keybinding system - Cinnamon's
(org.cinnamon.desktop.keybindings) or GNOME's
(org.gnome.settings-daemon.plugins.media-keys) - rather than the app
holding its own raw X11 global key grabs, which would fight either
desktop's own default PrtScn-family bindings to its built-in
screenshot tool.

Schema/path layout for both confirmed against real running sessions
before writing any of this (read-only introspection via ``gsettings``,
never a write - see GNOME_PROFILE's own note below for how that
extended to GNOME specifically). Cinnamon: reading
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
This is real validation that conflict detection isn't hypothetical -
and the same is true on a fresh GNOME install, not just a customized
Cinnamon one: GNOME's own org.gnome.shell.keybindings defaults to
show-screenshot-ui=Print, screenshot-window=<Alt>Print, and
screenshot=<Shift>Print - three of our four defaults collide with
GNOME's own out-of-the-box bindings before the user has touched
anything (only <Control>Print, our Full Screen Capture default, is
free by default).

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
actually hold a PrintScreen-family binding (each desktop's own
built-in screenshot keys, plus existing custom keybindings) rather
than every gsettings schema on the system - both desktops have many
keybinding schemas (window manager actions, workspace switching, etc.)
that are extremely unlikely to ever be bound to a PrintScreen combo.
This is a deliberate scope boundary, not an oversight.

Desktops other than these two (XFCE, KDE, MATE, etc.) aren't detected
or auto-configured at all - deliberately out of scope, not an
oversight either. There's no way to reliably enumerate every possible
screenshot tool someone might already have installed there and safely
reclaim its bindings; anyone running one of those desktops presumably
already knows how to bind a keyboard shortcut to a command themselves,
so ui/first_run_setup.py falls back to showing the exact CLI commands
to bind manually instead (see DesktopKeybindingProfile's own use
there) rather than attempting anything more automatic.
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

# GNOME's own analogue of the four Cinnamon constants above - confirmed
# live (Ubuntu 26.04 GNOME/Wayland VM, read-only gsettings introspection
# plus reading the installed .gschema.xml files directly for the exact
# GVariant types, never a write): org.gnome.settings-daemon.plugins.
# media-keys.custom-keybinding is relocatable at
# /org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/
# customN/ - structurally the same "customN slot" convention Cinnamon's
# own fork of this uses, confirmed by adding one real custom shortcut
# through GNOME's own Settings app and reading back the exact path/
# values it created. Two real structural differences from Cinnamon,
# both schema-verified, not assumed from Cinnamon's own shape:
# 1. GNOME's own list key (custom-keybindings, on the *media-keys*
#    schema itself, not a separate list-holder schema the way
#    Cinnamon's CUSTOM_LIST_SCHEMA is) stores each entry as the full
#    object path, not a bare "customN" slot name - see
#    DesktopKeybindingProfile.list_stores_full_paths.
# 2. GNOME's own custom-keybinding "binding" key is a plain string
#    (type="s"), not an array of strings like Cinnamon's (type="as") -
#    see DesktopKeybindingProfile.custom_binding_is_array. GNOME's own
#    *built-in* screenshot keys (org.gnome.shell.keybindings) are still
#    arrays like Cinnamon's built-in ones, confirmed via the same
#    .gschema.xml read - only the *custom*-keybinding's own binding
#    field differs in type.
GNOME_CUSTOM_LIST_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_CUSTOM_KEYBINDING_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
GNOME_CUSTOM_KEYBINDING_PATH_TEMPLATE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/{slot}/"

GNOME_SHELL_KEYBINDINGS_SCHEMA = "org.gnome.shell.keybindings"
# Only the three screenshot-capture actions - not show-screen-recording-ui
# (screencasting, unrelated) or anything else in this schema (window
# management, workspace switching, etc. - see this module's own
# docstring on why that's a deliberate scope boundary).
_GNOME_SCREENSHOT_KEYS = ("show-screenshot-ui", "screenshot", "screenshot-window")


@dataclass(frozen=True)
class DesktopKeybindingProfile:
    """Which GSettings schemas/paths/GVariant types a desktop
    environment uses for its own custom keyboard shortcuts and its own
    built-in screenshot keybindings - what find_conflicts/
    configure_hotkey need to work with either Cinnamon or GNOME, not
    just the Cinnamon-only logic this module started as (see this
    module's own docstring for the two real structural differences
    ``list_stores_full_paths``/``custom_binding_is_array`` cover).
    """
    name: str
    custom_list_schema: str
    custom_list_key: str
    custom_keybinding_schema: str
    path_template: str  # "{slot}" placeholder
    list_stores_full_paths: bool
    custom_binding_is_array: bool
    builtin_schema: str
    builtin_checks: Tuple[Tuple[str, str], ...]  # (key, human-readable label) pairs


CINNAMON_PROFILE = DesktopKeybindingProfile(
    name="Cinnamon",
    custom_list_schema=CUSTOM_LIST_SCHEMA,
    custom_list_key="custom-list",
    custom_keybinding_schema=CUSTOM_KEYBINDING_SCHEMA,
    path_template=CUSTOM_KEYBINDING_PATH_TEMPLATE,
    list_stores_full_paths=False,
    custom_binding_is_array=True,
    builtin_schema=MEDIA_KEYS_SCHEMA,
    builtin_checks=tuple((key, key) for key in _MEDIA_KEYS_SCREENSHOT_KEYS),
)

GNOME_PROFILE = DesktopKeybindingProfile(
    name="GNOME",
    custom_list_schema=GNOME_CUSTOM_LIST_SCHEMA,
    custom_list_key="custom-keybindings",
    custom_keybinding_schema=GNOME_CUSTOM_KEYBINDING_SCHEMA,
    path_template=GNOME_CUSTOM_KEYBINDING_PATH_TEMPLATE,
    list_stores_full_paths=True,
    custom_binding_is_array=False,
    builtin_schema=GNOME_SHELL_KEYBINDINGS_SCHEMA,
    builtin_checks=tuple((key, key) for key in _GNOME_SCREENSHOT_KEYS),
)


@dataclass(frozen=True)
class HotkeyBinding:
    name: str
    binding: str
    cli_flag: str


# REQUIREMENTS.md's Global Activation table, from the Windows source's
# ICoreConfiguration.cs defaults.
DEFAULT_HOTKEYS = (
    HotkeyBinding("Orcshot - Region Capture", "Print", "--capture-region"),
    HotkeyBinding("Orcshot - Window Capture", "<Alt>Print", "--capture-active-window"),
    HotkeyBinding("Orcshot - Full Screen Capture", "<Control>Print", "--capture-full-screen"),
    HotkeyBinding("Orcshot - Repeat Last Region", "<Shift>Print", "--capture-last-region"),
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


def cinnamon_keybindings_available() -> bool:
    """Whether org.cinnamon.desktop.keybindings is actually installed on
    this system - a read-only Gio.SettingsSchemaSource lookup, no
    Gio.Settings object ever constructed here (same "read-only
    introspection, never a write" precedent this module's own docstring
    already established for verifying schema/path layout).

    Callers MUST check this before ever touching GioSettingsBackend or
    any of CUSTOM_LIST_SCHEMA/CUSTOM_KEYBINDING_SCHEMA/MEDIA_KEYS_SCHEMA
    for real. Gio.Settings.new() on a schema that isn't installed is a
    hard, uncatchable process abort, not a Python exception: confirmed
    live on a real (non-Cinnamon) GNOME desktop - GLib logs
    `GLib-GIO-ERROR **: Settings schema '...' is not installed` and
    unconditionally calls abort() afterward (that's what a GLib
    g_error()-level log message means), crashing the entire app with no
    Python traceback at all, before ui/first_run_setup.py's dialog even
    had a chance to show. This function is the fix: check first, skip
    hotkey auto-configuration entirely (still offer autostart, which is
    desktop-agnostic) rather than reaching Cinnamon-only schemas on a
    desktop that doesn't have them.
    """
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    return Gio.SettingsSchemaSource.get_default().lookup(CUSTOM_LIST_SCHEMA, True) is not None


def gnome_keybindings_available() -> bool:
    """GNOME's own analogue of cinnamon_keybindings_available - same
    mandatory-not-optional check, same reason (a missing schema is a
    hard, uncatchable Gio.Settings.new() process abort, not a Python
    exception)."""
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    return Gio.SettingsSchemaSource.get_default().lookup(GNOME_CUSTOM_LIST_SCHEMA, True) is not None


def detect_profile() -> DesktopKeybindingProfile | None:
    """Which desktop's own keybinding schema is actually present on
    this system right now, or None if neither is (some other desktop -
    see this module's own docstring for why that's out of scope for
    auto-configuration). The single entry point ui/first_run_setup.py
    uses instead of checking cinnamon_keybindings_available/
    gnome_keybindings_available itself - Cinnamon checked first since
    Cinnamon is this project's primary target (see REQUIREMENTS.md's
    "Platform priority"), though a session could only plausibly report
    one of these True in practice.
    """
    if cinnamon_keybindings_available():
        return CINNAMON_PROFILE
    if gnome_keybindings_available():
        return GNOME_PROFILE
    return None


def _custom_list_entries(backend: SettingsBackend, profile: DesktopKeybindingProfile) -> List[str]:
    return list(backend.get_strv(profile.custom_list_schema, "/", profile.custom_list_key))


def _slot_from_entry(entry: str, profile: DesktopKeybindingProfile) -> str:
    """The bare "customN" slot name for one entry of the custom-list -
    already bare for Cinnamon, but GNOME's own list stores full object
    paths (".../custom-keybindings/custom0/") instead, so the trailing
    path segment needs pulling out first (see DesktopKeybindingProfile.
    list_stores_full_paths)."""
    if not profile.list_stores_full_paths:
        return entry
    return entry.rstrip("/").rsplit("/", 1)[-1]


def _entry_for_slot(slot: str, profile: DesktopKeybindingProfile) -> str:
    """The inverse of _slot_from_entry - what to actually store in the
    custom-list for a given slot."""
    if profile.list_stores_full_paths:
        return profile.path_template.format(slot=slot)
    return slot


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
    clearing to free the combo - see clear_conflict. ``binding_is_array``
    defaults True (Cinnamon's own shape, and every desktop's built-in
    keys) - set False only for a GNOME custom keybinding's own
    "binding" field, a plain string there rather than an array (see
    DesktopKeybindingProfile.custom_binding_is_array).
    """
    binding: str
    source: str
    schema: str
    path: str
    key: str
    binding_is_array: bool = True


def find_conflicts(
    backend: SettingsBackend, binding: str, ignore_names: FrozenSet[str] = frozenset(),
    profile: DesktopKeybindingProfile = CINNAMON_PROFILE,
) -> List[BindingConflict]:
    """Every existing binding (``profile``'s own built-in screenshot
    actions, or an existing custom keybinding) that already claims
    ``binding``. ``ignore_names`` excludes custom keybindings by name -
    pass the names of our own DEFAULT_HOTKEYS so a hotkey we already
    installed ourselves doesn't get reported as a conflict against
    itself on a repeat run.
    """
    conflicts = []
    for key, label in profile.builtin_checks:
        if binding in backend.get_strv(profile.builtin_schema, "/", key):
            conflicts.append(BindingConflict(
                binding=binding, source=f"{profile.name}'s built-in \"{label}\" shortcut",
                schema=profile.builtin_schema, path="/", key=key,
            ))
    for entry in _custom_list_entries(backend, profile):
        slot = _slot_from_entry(entry, profile)
        path = profile.path_template.format(slot=slot)
        name = backend.get_string(profile.custom_keybinding_schema, path, "name")
        if name in ignore_names:
            continue
        if profile.custom_binding_is_array:
            matches = binding in backend.get_strv(profile.custom_keybinding_schema, path, "binding")
        else:
            matches = backend.get_string(profile.custom_keybinding_schema, path, "binding") == binding
        if matches:
            conflicts.append(BindingConflict(
                binding=binding, source=f"existing custom shortcut \"{name}\"",
                schema=profile.custom_keybinding_schema, path=path, key="binding",
                binding_is_array=profile.custom_binding_is_array,
            ))
    return conflicts


def clear_conflict(backend: SettingsBackend, conflict: BindingConflict) -> None:
    """Frees up ``conflict``'s key combo by clearing just that specific
    binding field. Whatever it belonged to - a built-in desktop action,
    or another custom keybinding's name/command - is left otherwise
    intact, just no longer bound to this key combo.
    """
    if conflict.binding_is_array:
        backend.set_strv(conflict.schema, conflict.path, conflict.key, [])
    else:
        backend.set_string(conflict.schema, conflict.path, conflict.key, "")


def configure_hotkey(
    backend: SettingsBackend, name: str, binding: str, command: str,
    profile: DesktopKeybindingProfile = CINNAMON_PROFILE,
) -> bool:
    """Idempotently ensures a ``profile``-specific custom keybinding
    exists for ``binding`` -> ``command``, named ``name`` - "ensures"
    now includes correcting an existing same-named entry's command/
    binding if they've drifted, not just confirming a name is present
    (task #150 follow-up). The name-only check used to treat any
    existing entry with a matching name as fully done regardless of
    what it actually pointed at - live-reproduced as a real bug: a
    stale entry from an old dev checkout (pointing at a since-deleted
    ``PYTHONPATH`` directory) has the exact same name a fresh run
    creates, so first-run-setup kept seeing "already configured" and
    never updated the command, no matter how many times it ran. This
    directly contradicted _default_executable's own documented intent
    (switch a dev-checkout hotkey over to the real installed binary
    once one exists) - `_default_executable` correctly returns the
    right executable, but nothing downstream ever acted on the change
    once a same-named entry already existed. Returns True if a new
    binding was added, False if one already existed by name (whether
    or not its command/binding needed correcting). Does not check for
    conflicts with *other* bindings first - call find_conflicts (and
    clear_conflict, if the caller decides to overwrite) before this.
    """
    entries = _custom_list_entries(backend, profile)

    for entry in entries:
        slot = _slot_from_entry(entry, profile)
        path = profile.path_template.format(slot=slot)
        if backend.get_string(profile.custom_keybinding_schema, path, "name") != name:
            continue
        if backend.get_string(profile.custom_keybinding_schema, path, "command") != command:
            backend.set_string(profile.custom_keybinding_schema, path, "command", command)
        if profile.custom_binding_is_array:
            if backend.get_strv(profile.custom_keybinding_schema, path, "binding") != [binding]:
                backend.set_strv(profile.custom_keybinding_schema, path, "binding", [binding])
        elif backend.get_string(profile.custom_keybinding_schema, path, "binding") != binding:
            backend.set_string(profile.custom_keybinding_schema, path, "binding", binding)
        return False

    slot = next_available_slot([_slot_from_entry(e, profile) for e in entries])
    path = profile.path_template.format(slot=slot)
    backend.set_string(profile.custom_keybinding_schema, path, "name", name)
    backend.set_string(profile.custom_keybinding_schema, path, "command", command)
    if profile.custom_binding_is_array:
        backend.set_strv(profile.custom_keybinding_schema, path, "binding", [binding])
    else:
        backend.set_string(profile.custom_keybinding_schema, path, "binding", binding)
    backend.set_strv(
        profile.custom_list_schema, "/", profile.custom_list_key,
        entries + [_entry_for_slot(slot, profile)],
    )
    return True


def configure_all_hotkeys(
    backend: SettingsBackend, executable: str,
    bindings: Sequence[HotkeyBinding] = DEFAULT_HOTKEYS, skip: FrozenSet[str] = frozenset(),
    profile: DesktopKeybindingProfile = CINNAMON_PROFILE,
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
        # Task #170: `systemctl --user start orcshot.service` first, not
        # instead of the direct exec - closes the race where a hotkey
        # fired while Orcshot isn't running would bare-exec it directly
        # and become an untracked "orphan" primary instance outside
        # systemd's own bookkeeping (confirmed live: Type=dbus, set on
        # the unit itself, makes this `start` block until the app has
        # actually acquired its D-Bus name, not just forked - see
        # debian/orcshot.user.service's own comment for the full
        # writeup). Wrapped in `sh -c` since the "command" GSettings
        # value is a single string the desktop's keybinding daemon
        # tokenizes itself (GLib's shell-word-splitting, not a real
        # shell) - it never interprets `;` as a command separator on
        # its own, only a real shell does that.
        command = f"sh -c 'systemctl --user start orcshot.service; exec {executable} {hb.cli_flag}'"
        results[hb.name] = configure_hotkey(
            backend, hb.name, hb.binding, command, profile=profile,
        )
    return results


def check_all_conflicts(
    backend: SettingsBackend, bindings: Sequence[HotkeyBinding] = DEFAULT_HOTKEYS,
    profile: DesktopKeybindingProfile = CINNAMON_PROFILE,
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
    return {
        hb.name: find_conflicts(backend, hb.binding, ignore_names=ignore_names, profile=profile)
        for hb in bindings
    }


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

    Caches one Gio.Settings instance per (schema, path) rather than
    constructing a fresh one on every call (task #150 follow-up - a
    real, evidence-based fix, not a guess). A read-modify-write like
    gnome_extension_setup.enable_extension's own (get_strv, compute,
    set_strv) is only self-consistent if the read and write go through
    the *same* Gio.Settings object - its own internal cache guarantees
    a set_strv() is visible to a get_strv() on that same instance
    immediately, with no round trip needed. Two independent instances
    racing on the same key have no such guarantee: the second's read
    depends on dconf's own commit-then-notify cycle from the first's
    write having actually completed, which isn't instant. Live-
    confirmed as the real cause of a long-standing, previously
    unexplained bug: calling enable_extension twice in a row (for
    window-calls then orcshot-clipboard, both writing the same
    `enabled-extensions` key) reliably left the second UUID missing -
    window-calls persisted, orcshot-clipboard silently didn't, on a
    real .deb install with no checkbox or dev-checkout complications
    involved this time. The same fragile pattern almost certainly
    explains the still-open "hotkey rewrite doesn't stick" symptom
    too, since configure_all_hotkeys drives multiple writes through
    this identical backend.
    """

    def __init__(self):
        self._cache = {}

    def _settings(self, schema: str, path: str):
        key = (schema, path)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        settings = Gio.Settings.new(schema) if path == "/" else Gio.Settings.new_with_path(schema, path)
        self._cache[key] = settings
        return settings

    def get_strv(self, schema: str, path: str, key: str) -> list:
        return list(self._settings(schema, path).get_strv(key))

    def set_strv(self, schema: str, path: str, key: str, value: list) -> None:
        self._settings(schema, path).set_strv(key, value)

    def get_string(self, schema: str, path: str, key: str) -> str:
        return self._settings(schema, path).get_string(key)

    def set_string(self, schema: str, path: str, key: str, value: str) -> None:
        self._settings(schema, path).set_string(key, value)
