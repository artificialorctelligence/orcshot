"""Cinnamon custom-keybinding configuration and collision-detection
logic, tested against a fake settings backend - never the real
Gio.Settings-backed adapter (GioSettingsBackend), which would write to
this machine's actual desktop configuration. See hotkey_setup.py's
module docstring for why that's deliberately never exercised by
anything in this project.

The media-keys screenshot key names and example values in these tests
(window-screenshot, screenshot-clip, etc.) are taken from actually
reading this dev machine's real Cinnamon gsettings before writing any
of this - see hotkey_setup.py's module docstring for the full findings
(all four of our default bindings turned out to already collide with
something real here).
"""

from greenshot_linux.hotkey_setup import (
    CUSTOM_KEYBINDING_PATH_TEMPLATE,
    CUSTOM_KEYBINDING_SCHEMA,
    CUSTOM_LIST_SCHEMA,
    GNOME_CUSTOM_KEYBINDING_PATH_TEMPLATE,
    GNOME_CUSTOM_KEYBINDING_SCHEMA,
    GNOME_CUSTOM_LIST_SCHEMA,
    GNOME_PROFILE,
    GNOME_SHELL_KEYBINDINGS_SCHEMA,
    MEDIA_KEYS_SCHEMA,
    BindingConflict,
    DEFAULT_HOTKEYS,
    HotkeyBinding,
    SettingsBackend,
    check_all_conflicts,
    clear_conflict,
    configure_all_hotkeys,
    configure_hotkey,
    find_conflicts,
    next_available_slot,
    resolve_hotkey_choices,
)


class FakeSettingsBackend:
    """An in-memory stand-in for Gio.Settings, keyed the same way the
    real adapter addresses it: (schema, path, key).
    """

    def __init__(self, initial=None):
        self._values = dict(initial or {})

    def get_strv(self, schema, path, key):
        return list(self._values.get((schema, path, key), []))

    def set_strv(self, schema, path, key, value):
        self._values[(schema, path, key)] = list(value)

    def get_string(self, schema, path, key):
        return self._values.get((schema, path, key), "")

    def set_string(self, schema, path, key, value):
        self._values[(schema, path, key)] = value


class TestNextAvailableSlot:
    def test_empty_list_gives_custom0(self):
        assert next_available_slot([]) == "custom0"

    def test_skips_taken_slots_in_order(self):
        assert next_available_slot(["custom0", "custom1"]) == "custom2"

    def test_fills_a_gap_rather_than_appending(self):
        assert next_available_slot(["custom0", "custom2"]) == "custom1"

    def test_order_of_the_input_list_does_not_matter(self):
        assert next_available_slot(["custom2", "custom0"]) == "custom1"


class TestConfigureHotkey:
    def test_satisfies_the_settings_backend_protocol(self):
        assert isinstance(FakeSettingsBackend(), SettingsBackend)

    def test_adds_a_binding_when_none_exists(self):
        backend = FakeSettingsBackend()

        added = configure_hotkey(backend, "Greenshot Linux - Region Capture", "Print", "greenshot-linux --capture-region")

        assert added is True
        assert backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list") == ["custom0"]
        path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        assert backend.get_string(CUSTOM_KEYBINDING_SCHEMA, path, "name") == "Greenshot Linux - Region Capture"
        assert backend.get_string(CUSTOM_KEYBINDING_SCHEMA, path, "command") == "greenshot-linux --capture-region"
        assert backend.get_strv(CUSTOM_KEYBINDING_SCHEMA, path, "binding") == ["Print"]

    def test_does_not_disturb_existing_custom_keybindings(self):
        existing_path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        backend = FakeSettingsBackend({
            (CUSTOM_LIST_SCHEMA, "/", "custom-list"): ["custom0"],
            (CUSTOM_KEYBINDING_SCHEMA, existing_path, "name"): "Full Screenshot",
            (CUSTOM_KEYBINDING_SCHEMA, existing_path, "command"): "shutter -f",
            (CUSTOM_KEYBINDING_SCHEMA, existing_path, "binding"): ["<Shift>Print"],
        })

        configure_hotkey(backend, "Greenshot Linux - Region Capture", "Print", "greenshot-linux --capture-region")

        assert backend.get_string(CUSTOM_KEYBINDING_SCHEMA, existing_path, "name") == "Full Screenshot"
        assert backend.get_string(CUSTOM_KEYBINDING_SCHEMA, existing_path, "command") == "shutter -f"
        assert set(backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list")) == {"custom0", "custom1"}

    def test_is_idempotent_when_already_configured(self):
        backend = FakeSettingsBackend()
        configure_hotkey(backend, "Greenshot Linux - Region Capture", "Print", "greenshot-linux --capture-region")

        added_again = configure_hotkey(backend, "Greenshot Linux - Region Capture", "Print", "greenshot-linux --capture-region")

        assert added_again is False
        assert backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list") == ["custom0"]

    def test_a_differently_named_existing_binding_does_not_block_configuration(self):
        existing_path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        backend = FakeSettingsBackend({
            (CUSTOM_LIST_SCHEMA, "/", "custom-list"): ["custom0"],
            (CUSTOM_KEYBINDING_SCHEMA, existing_path, "name"): "Something Else",
        })

        added = configure_hotkey(backend, "Greenshot Linux - Region Capture", "Print", "greenshot-linux --capture-region")

        assert added is True
        assert set(backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list")) == {"custom0", "custom1"}


class TestDefaultHotkeys:
    def test_has_all_four_windows_default_bindings(self):
        # REQUIREMENTS.md's Global Activation table, from the Windows
        # source's ICoreConfiguration.cs defaults.
        bindings = {hb.binding for hb in DEFAULT_HOTKEYS}
        assert bindings == {"Print", "<Alt>Print", "<Control>Print", "<Shift>Print"}

    def test_each_binding_has_a_matching_cli_flag(self):
        flags = {hb.cli_flag for hb in DEFAULT_HOTKEYS}
        assert flags == {
            "--capture-region", "--capture-active-window",
            "--capture-full-screen", "--capture-last-region",
        }


class TestFindConflicts:
    def test_empty_when_nothing_claims_the_binding(self):
        backend = FakeSettingsBackend()
        assert find_conflicts(backend, "Print") == []

    def test_detects_a_cinnamon_built_in_media_key_conflict(self):
        # Real data from this dev machine: window-screenshot is
        # Cinnamon's own "screenshot of the active window" action,
        # bound to <Alt>Print by default.
        backend = FakeSettingsBackend({
            (MEDIA_KEYS_SCHEMA, "/", "window-screenshot"): ["<Alt>Print"],
        })

        conflicts = find_conflicts(backend, "<Alt>Print")

        assert len(conflicts) == 1
        assert conflicts[0].binding == "<Alt>Print"
        assert "window-screenshot" in conflicts[0].source

    def test_detects_an_existing_custom_keybinding_conflict(self):
        # Real data from this dev machine: a pre-existing "Area
        # Screenshot" -> shutter -s custom binding on plain Print.
        path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom2")
        backend = FakeSettingsBackend({
            (CUSTOM_LIST_SCHEMA, "/", "custom-list"): ["custom2"],
            (CUSTOM_KEYBINDING_SCHEMA, path, "name"): "Area Screenshot",
            (CUSTOM_KEYBINDING_SCHEMA, path, "command"): "shutter -s",
            (CUSTOM_KEYBINDING_SCHEMA, path, "binding"): ["Print"],
        })

        conflicts = find_conflicts(backend, "Print")

        assert len(conflicts) == 1
        assert "Area Screenshot" in conflicts[0].source

    def test_ignore_names_excludes_our_own_previously_configured_binding(self):
        path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        backend = FakeSettingsBackend({
            (CUSTOM_LIST_SCHEMA, "/", "custom-list"): ["custom0"],
            (CUSTOM_KEYBINDING_SCHEMA, path, "name"): "Greenshot Linux - Region Capture",
            (CUSTOM_KEYBINDING_SCHEMA, path, "command"): "greenshot-linux --capture-region",
            (CUSTOM_KEYBINDING_SCHEMA, path, "binding"): ["Print"],
        })

        conflicts = find_conflicts(backend, "Print", ignore_names={"Greenshot Linux - Region Capture"})

        assert conflicts == []

    def test_reports_multiple_conflicts_for_the_same_binding(self):
        path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        backend = FakeSettingsBackend({
            (MEDIA_KEYS_SCHEMA, "/", "screenshot-clip"): ["<Control>Print"],
            (CUSTOM_LIST_SCHEMA, "/", "custom-list"): ["custom0"],
            (CUSTOM_KEYBINDING_SCHEMA, path, "name"): "Something",
            (CUSTOM_KEYBINDING_SCHEMA, path, "binding"): ["<Control>Print"],
        })

        conflicts = find_conflicts(backend, "<Control>Print")

        assert len(conflicts) == 2


class TestClearConflict:
    def test_clears_a_media_keys_conflict(self):
        backend = FakeSettingsBackend({(MEDIA_KEYS_SCHEMA, "/", "window-screenshot"): ["<Alt>Print"]})
        conflict = find_conflicts(backend, "<Alt>Print")[0]

        clear_conflict(backend, conflict)

        assert backend.get_strv(MEDIA_KEYS_SCHEMA, "/", "window-screenshot") == []

    def test_clears_a_custom_keybinding_conflict_without_deleting_it(self):
        path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom2")
        backend = FakeSettingsBackend({
            (CUSTOM_LIST_SCHEMA, "/", "custom-list"): ["custom2"],
            (CUSTOM_KEYBINDING_SCHEMA, path, "name"): "Area Screenshot",
            (CUSTOM_KEYBINDING_SCHEMA, path, "command"): "shutter -s",
            (CUSTOM_KEYBINDING_SCHEMA, path, "binding"): ["Print"],
        })
        conflict = find_conflicts(backend, "Print")[0]

        clear_conflict(backend, conflict)

        assert backend.get_strv(CUSTOM_KEYBINDING_SCHEMA, path, "binding") == []
        # name/command left alone - only the binding itself is freed
        assert backend.get_string(CUSTOM_KEYBINDING_SCHEMA, path, "name") == "Area Screenshot"
        assert backend.get_string(CUSTOM_KEYBINDING_SCHEMA, path, "command") == "shutter -s"


class TestConfigureAllHotkeys:
    def test_configures_every_default_binding(self):
        backend = FakeSettingsBackend()

        results = configure_all_hotkeys(backend, "greenshot-linux")

        assert set(results.values()) == {True}
        assert len(results) == 4
        assert set(backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list")) == {"custom0", "custom1", "custom2", "custom3"}

    def test_uses_the_given_executable_and_each_bindings_cli_flag(self):
        backend = FakeSettingsBackend()

        configure_all_hotkeys(backend, "/opt/greenshot-linux/bin/greenshot-linux")

        commands = set()
        for slot in backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list"):
            path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot=slot)
            commands.add(backend.get_string(CUSTOM_KEYBINDING_SCHEMA, path, "command"))
        assert commands == {
            "/opt/greenshot-linux/bin/greenshot-linux --capture-region",
            "/opt/greenshot-linux/bin/greenshot-linux --capture-active-window",
            "/opt/greenshot-linux/bin/greenshot-linux --capture-full-screen",
            "/opt/greenshot-linux/bin/greenshot-linux --capture-last-region",
        }

    def test_skips_bindings_whose_binding_is_in_skip(self):
        backend = FakeSettingsBackend()

        results = configure_all_hotkeys(backend, "greenshot-linux", skip={"<Alt>Print"})

        assert results["Greenshot Linux - Window Capture"] is False
        assert backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list") == ["custom0", "custom1", "custom2"]

    def test_only_configures_the_given_bindings_subset(self):
        backend = FakeSettingsBackend()
        just_one = (HotkeyBinding("Greenshot Linux - Region Capture", "Print", "--capture-region"),)

        results = configure_all_hotkeys(backend, "greenshot-linux", bindings=just_one)

        assert results == {"Greenshot Linux - Region Capture": True}
        assert backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list") == ["custom0"]


class TestCheckAllConflicts:
    def test_reports_no_conflicts_on_a_clean_system(self):
        backend = FakeSettingsBackend()

        result = check_all_conflicts(backend)

        assert set(result) == {hb.name for hb in DEFAULT_HOTKEYS}
        assert all(conflicts == [] for conflicts in result.values())

    def test_reports_a_conflict_for_the_affected_binding_only(self):
        backend = FakeSettingsBackend({(MEDIA_KEYS_SCHEMA, "/", "window-screenshot"): ["<Alt>Print"]})

        result = check_all_conflicts(backend)

        assert len(result["Greenshot Linux - Window Capture"]) == 1
        assert result["Greenshot Linux - Region Capture"] == []

    def test_does_not_flag_our_own_already_installed_bindings(self):
        backend = FakeSettingsBackend()
        configure_all_hotkeys(backend, "greenshot-linux")

        result = check_all_conflicts(backend)

        assert all(conflicts == [] for conflicts in result.values())


class TestResolveHotkeyChoices:
    def test_all_enabled_with_no_conflicts_skips_nothing_and_clears_nothing(self):
        conflicts = {hb.name: [] for hb in DEFAULT_HOTKEYS}
        enabled = {hb.name for hb in DEFAULT_HOTKEYS}

        skip, to_clear = resolve_hotkey_choices(enabled, conflicts)

        assert skip == set()
        assert to_clear == []

    def test_a_disabled_binding_is_skipped_and_nothing_is_cleared_for_it(self):
        conflicts = {hb.name: [] for hb in DEFAULT_HOTKEYS}
        enabled = {hb.name for hb in DEFAULT_HOTKEYS if hb.name != "Greenshot Linux - Window Capture"}

        skip, to_clear = resolve_hotkey_choices(enabled, conflicts)

        assert skip == {"<Alt>Print"}
        assert to_clear == []

    def test_enabling_a_conflicted_binding_queues_its_conflicts_for_clearing(self):
        conflict = BindingConflict("<Alt>Print", "Cinnamon's built-in \"window-screenshot\" shortcut", MEDIA_KEYS_SCHEMA, "/", "window-screenshot")
        conflicts = {hb.name: ([conflict] if hb.name == "Greenshot Linux - Window Capture" else []) for hb in DEFAULT_HOTKEYS}
        enabled = {hb.name for hb in DEFAULT_HOTKEYS}

        skip, to_clear = resolve_hotkey_choices(enabled, conflicts)

        assert skip == set()
        assert to_clear == [conflict]

    def test_leaving_a_conflicted_binding_disabled_does_not_clear_its_conflict(self):
        conflict = BindingConflict("<Alt>Print", "Cinnamon's built-in \"window-screenshot\" shortcut", MEDIA_KEYS_SCHEMA, "/", "window-screenshot")
        conflicts = {hb.name: ([conflict] if hb.name == "Greenshot Linux - Window Capture" else []) for hb in DEFAULT_HOTKEYS}
        enabled = {hb.name for hb in DEFAULT_HOTKEYS if hb.name != "Greenshot Linux - Window Capture"}

        skip, to_clear = resolve_hotkey_choices(enabled, conflicts)

        assert skip == {"<Alt>Print"}
        assert to_clear == []


class TestGnomeProfile:
    """GNOME's own analogue of the Cinnamon tests above, run through
    the exact same find_conflicts/configure_hotkey/clear_conflict/
    configure_all_hotkeys/check_all_conflicts entry points via
    profile=GNOME_PROFILE, covering the two real structural differences
    from Cinnamon confirmed live against a real GNOME/Wayland session
    (see hotkey_setup.py's own module docstring): GNOME's own custom-
    keybindings list stores full object paths, not bare "customN" slot
    names, and a GNOME custom keybinding's own "binding" field is a
    plain string, not an array like Cinnamon's (and like every built-in
    screenshot key on both desktops).
    """

    def test_adds_a_binding_with_gnome_s_own_path_and_string_binding_shape(self):
        backend = FakeSettingsBackend()

        added = configure_hotkey(
            backend, "Greenshot Linux - Region Capture", "Print", "greenshot-linux --capture-region",
            profile=GNOME_PROFILE,
        )

        assert added is True
        assert backend.get_strv(GNOME_CUSTOM_LIST_SCHEMA, "/", "custom-keybindings") == [
            GNOME_CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        ]
        path = GNOME_CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        assert backend.get_string(GNOME_CUSTOM_KEYBINDING_SCHEMA, path, "name") == "Greenshot Linux - Region Capture"
        assert backend.get_string(GNOME_CUSTOM_KEYBINDING_SCHEMA, path, "command") == "greenshot-linux --capture-region"
        # A plain string, not ["Print"] the way Cinnamon's own array-typed
        # binding field would be - see this class's own docstring.
        assert backend.get_string(GNOME_CUSTOM_KEYBINDING_SCHEMA, path, "binding") == "Print"

    def test_fills_the_next_available_slot_from_gnome_s_own_full_paths(self):
        existing_path = GNOME_CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        backend = FakeSettingsBackend({
            (GNOME_CUSTOM_LIST_SCHEMA, "/", "custom-keybindings"): [existing_path],
            (GNOME_CUSTOM_KEYBINDING_SCHEMA, existing_path, "name"): "greenshottest",
        })

        configure_hotkey(
            backend, "Greenshot Linux - Region Capture", "Print", "greenshot-linux --capture-region",
            profile=GNOME_PROFILE,
        )

        assert set(backend.get_strv(GNOME_CUSTOM_LIST_SCHEMA, "/", "custom-keybindings")) == {
            existing_path, GNOME_CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom1"),
        }

    def test_is_idempotent_when_already_configured(self):
        backend = FakeSettingsBackend()
        configure_hotkey(
            backend, "Greenshot Linux - Region Capture", "Print", "greenshot-linux --capture-region",
            profile=GNOME_PROFILE,
        )

        added_again = configure_hotkey(
            backend, "Greenshot Linux - Region Capture", "Print", "greenshot-linux --capture-region",
            profile=GNOME_PROFILE,
        )

        assert added_again is False
        assert len(backend.get_strv(GNOME_CUSTOM_LIST_SCHEMA, "/", "custom-keybindings")) == 1

    def test_detects_a_gnome_built_in_shortcut_conflict(self):
        # Real default from a fresh GNOME install (confirmed live,
        # Ubuntu 26.04 GNOME/Wayland VM): screenshot-window is GNOME's
        # own "screenshot of the focused window" action, <Alt>Print by
        # default - the same key combo this app's own "Window Capture"
        # (Active Window) default uses.
        backend = FakeSettingsBackend({
            (GNOME_SHELL_KEYBINDINGS_SCHEMA, "/", "screenshot-window"): ["<Alt>Print"],
        })

        conflicts = find_conflicts(backend, "<Alt>Print", profile=GNOME_PROFILE)

        assert len(conflicts) == 1
        assert "GNOME" in conflicts[0].source
        assert "screenshot-window" in conflicts[0].source

    def test_detects_an_existing_gnome_custom_keybinding_conflict(self):
        path = GNOME_CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        backend = FakeSettingsBackend({
            (GNOME_CUSTOM_LIST_SCHEMA, "/", "custom-keybindings"): [path],
            (GNOME_CUSTOM_KEYBINDING_SCHEMA, path, "name"): "greenshottest",
            (GNOME_CUSTOM_KEYBINDING_SCHEMA, path, "binding"): "<Control>j",
        })

        conflicts = find_conflicts(backend, "<Control>j", profile=GNOME_PROFILE)

        assert len(conflicts) == 1
        assert "greenshottest" in conflicts[0].source
        assert conflicts[0].binding_is_array is False

    def test_ignore_names_excludes_our_own_previously_configured_binding(self):
        path = GNOME_CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        backend = FakeSettingsBackend({
            (GNOME_CUSTOM_LIST_SCHEMA, "/", "custom-keybindings"): [path],
            (GNOME_CUSTOM_KEYBINDING_SCHEMA, path, "name"): "Greenshot Linux - Region Capture",
            (GNOME_CUSTOM_KEYBINDING_SCHEMA, path, "binding"): "Print",
        })

        conflicts = find_conflicts(
            backend, "Print", ignore_names={"Greenshot Linux - Region Capture"}, profile=GNOME_PROFILE,
        )

        assert conflicts == []

    def test_clears_a_gnome_built_in_conflict(self):
        backend = FakeSettingsBackend({
            (GNOME_SHELL_KEYBINDINGS_SCHEMA, "/", "show-screenshot-ui"): ["Print"],
        })
        conflict = find_conflicts(backend, "Print", profile=GNOME_PROFILE)[0]

        clear_conflict(backend, conflict)

        assert backend.get_strv(GNOME_SHELL_KEYBINDINGS_SCHEMA, "/", "show-screenshot-ui") == []

    def test_clears_a_gnome_custom_keybinding_conflict_via_set_string_not_set_strv(self):
        path = GNOME_CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        backend = FakeSettingsBackend({
            (GNOME_CUSTOM_LIST_SCHEMA, "/", "custom-keybindings"): [path],
            (GNOME_CUSTOM_KEYBINDING_SCHEMA, path, "name"): "greenshottest",
            (GNOME_CUSTOM_KEYBINDING_SCHEMA, path, "command"): "test",
            (GNOME_CUSTOM_KEYBINDING_SCHEMA, path, "binding"): "<Control>j",
        })
        conflict = find_conflicts(backend, "<Control>j", profile=GNOME_PROFILE)[0]

        clear_conflict(backend, conflict)

        assert backend.get_string(GNOME_CUSTOM_KEYBINDING_SCHEMA, path, "binding") == ""
        # name/command left alone - only the binding itself is freed
        assert backend.get_string(GNOME_CUSTOM_KEYBINDING_SCHEMA, path, "name") == "greenshottest"
        assert backend.get_string(GNOME_CUSTOM_KEYBINDING_SCHEMA, path, "command") == "test"

    def test_configure_all_hotkeys_configures_every_default_binding_on_gnome(self):
        backend = FakeSettingsBackend()

        results = configure_all_hotkeys(backend, "greenshot-linux", profile=GNOME_PROFILE)

        assert set(results.values()) == {True}
        assert len(backend.get_strv(GNOME_CUSTOM_LIST_SCHEMA, "/", "custom-keybindings")) == 4

    def test_check_all_conflicts_finds_gnome_s_own_fresh_install_defaults(self):
        # Real defaults from a fresh GNOME install (confirmed live,
        # Ubuntu 26.04 GNOME/Wayland VM): three of our four default
        # bindings collide with GNOME's own out-of-the-box screenshot
        # shortcuts before the user has touched anything.
        backend = FakeSettingsBackend({
            (GNOME_SHELL_KEYBINDINGS_SCHEMA, "/", "show-screenshot-ui"): ["Print"],
            (GNOME_SHELL_KEYBINDINGS_SCHEMA, "/", "screenshot-window"): ["<Alt>Print"],
            (GNOME_SHELL_KEYBINDINGS_SCHEMA, "/", "screenshot"): ["<Shift>Print"],
        })

        result = check_all_conflicts(backend, profile=GNOME_PROFILE)

        assert len(result["Greenshot Linux - Region Capture"]) == 1
        assert len(result["Greenshot Linux - Window Capture"]) == 1
        assert len(result["Greenshot Linux - Repeat Last Region"]) == 1
        assert result["Greenshot Linux - Full Screen Capture"] == []
