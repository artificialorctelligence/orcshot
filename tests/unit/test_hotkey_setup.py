"""Cinnamon custom-keybinding configuration logic, tested against a
fake settings backend - never the real Gio.Settings-backed adapter
(GioSettingsBackend), which would write to this machine's actual
desktop configuration. See hotkey_setup.py's module docstring for why
that's deliberately never exercised by anything in this project.
"""

from greenshot_linux.hotkey_setup import (
    CUSTOM_KEYBINDING_PATH_TEMPLATE,
    CUSTOM_KEYBINDING_SCHEMA,
    CUSTOM_LIST_SCHEMA,
    HOTKEY_BINDING,
    HOTKEY_NAME,
    SettingsBackend,
    configure_hotkey,
    next_available_slot,
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

        added = configure_hotkey(backend, "greenshot-linux --capture-region")

        assert added is True
        assert backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list") == ["custom0"]
        path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        assert backend.get_string(CUSTOM_KEYBINDING_SCHEMA, path, "name") == HOTKEY_NAME
        assert backend.get_string(CUSTOM_KEYBINDING_SCHEMA, path, "command") == "greenshot-linux --capture-region"
        assert backend.get_strv(CUSTOM_KEYBINDING_SCHEMA, path, "binding") == [HOTKEY_BINDING]

    def test_does_not_disturb_existing_custom_keybindings(self):
        existing_path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        backend = FakeSettingsBackend({
            (CUSTOM_LIST_SCHEMA, "/", "custom-list"): ["custom0"],
            (CUSTOM_KEYBINDING_SCHEMA, existing_path, "name"): "Full Screenshot",
            (CUSTOM_KEYBINDING_SCHEMA, existing_path, "command"): "shutter -f",
            (CUSTOM_KEYBINDING_SCHEMA, existing_path, "binding"): ["<Shift>Print"],
        })

        configure_hotkey(backend, "greenshot-linux --capture-region")

        assert backend.get_string(CUSTOM_KEYBINDING_SCHEMA, existing_path, "name") == "Full Screenshot"
        assert backend.get_string(CUSTOM_KEYBINDING_SCHEMA, existing_path, "command") == "shutter -f"
        assert set(backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list")) == {"custom0", "custom1"}

    def test_is_idempotent_when_already_configured(self):
        backend = FakeSettingsBackend()
        configure_hotkey(backend, "greenshot-linux --capture-region")

        added_again = configure_hotkey(backend, "greenshot-linux --capture-region")

        assert added_again is False
        assert backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list") == ["custom0"]

    def test_a_differently_named_existing_binding_does_not_block_configuration(self):
        existing_path = CUSTOM_KEYBINDING_PATH_TEMPLATE.format(slot="custom0")
        backend = FakeSettingsBackend({
            (CUSTOM_LIST_SCHEMA, "/", "custom-list"): ["custom0"],
            (CUSTOM_KEYBINDING_SCHEMA, existing_path, "name"): "Something Else",
        })

        added = configure_hotkey(backend, "greenshot-linux --capture-region")

        assert added is True
        assert set(backend.get_strv(CUSTOM_LIST_SCHEMA, "/", "custom-list")) == {"custom0", "custom1"}
