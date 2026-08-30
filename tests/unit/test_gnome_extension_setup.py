"""Pure coverage for gnome_extension_setup.py - gnome_shell_present()
and the real Gio.Settings write are excluded for the same reason
hotkey_setup.py's equivalents are (see that module's docstring):
touching the real desktop is reserved for a user-confirmed dialog
click, never a test.
"""

from orcshot.gnome_extension_setup import (
    CLIPBOARD_EXTENSION_UUID,
    TRAY_EXTENSION_UUID,
    WINDOW_CALLS_EXTENSION_UUID,
    enable_extension,
    enabled_extensions_after_adding,
    gnome_shell_present,
)


class FakeSettingsBackend:
    def __init__(self, values=None):
        self._values = values or {}

    def get_strv(self, schema, path, key):
        return list(self._values.get((schema, path, key), []))

    def set_strv(self, schema, path, key, value):
        self._values[(schema, path, key)] = list(value)


class TestEnabledExtensionsAfterAdding:
    def test_adds_uuid_to_empty_list(self):
        assert enabled_extensions_after_adding([], "foo@bar") == ["foo@bar"]

    def test_appends_after_existing_entries(self):
        assert enabled_extensions_after_adding(["existing@x"], "foo@bar") == ["existing@x", "foo@bar"]

    def test_does_not_duplicate_if_already_present(self):
        assert enabled_extensions_after_adding(["foo@bar"], "foo@bar") == ["foo@bar"]

    def test_preserves_order_of_existing_entries(self):
        current = ["a@x", "b@y", "c@z"]
        assert enabled_extensions_after_adding(current, "d@w") == ["a@x", "b@y", "c@z", "d@w"]


class TestEnableExtension:
    def test_adds_the_extension_uuid(self):
        backend = FakeSettingsBackend()
        enable_extension(backend, WINDOW_CALLS_EXTENSION_UUID)
        assert backend.get_strv("org.gnome.shell", "/", "enabled-extensions") == [WINDOW_CALLS_EXTENSION_UUID]

    def test_preserves_other_already_enabled_extensions(self):
        backend = FakeSettingsBackend({("org.gnome.shell", "/", "enabled-extensions"): ["other@ext"]})
        enable_extension(backend, WINDOW_CALLS_EXTENSION_UUID)
        assert backend.get_strv("org.gnome.shell", "/", "enabled-extensions") == ["other@ext", WINDOW_CALLS_EXTENSION_UUID]

    def test_is_idempotent(self):
        backend = FakeSettingsBackend({("org.gnome.shell", "/", "enabled-extensions"): [WINDOW_CALLS_EXTENSION_UUID]})
        enable_extension(backend, WINDOW_CALLS_EXTENSION_UUID)
        assert backend.get_strv("org.gnome.shell", "/", "enabled-extensions") == [WINDOW_CALLS_EXTENSION_UUID]

    def test_can_enable_all_three_bundled_extensions_independently(self):
        backend = FakeSettingsBackend()
        enable_extension(backend, WINDOW_CALLS_EXTENSION_UUID)
        enable_extension(backend, CLIPBOARD_EXTENSION_UUID)
        enable_extension(backend, TRAY_EXTENSION_UUID)
        assert backend.get_strv("org.gnome.shell", "/", "enabled-extensions") == [
            WINDOW_CALLS_EXTENSION_UUID, CLIPBOARD_EXTENSION_UUID, TRAY_EXTENSION_UUID,
        ]


class TestGnomeShellPresent:
    def test_returns_false_when_no_default_schema_source(self, monkeypatch):
        """Confirmed live under Snap's strict confinement: get_default() can
        return None outright, not just fail to contain the org.gnome.shell
        schema. Must return False, not crash."""
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        monkeypatch.setattr(Gio.SettingsSchemaSource, "get_default", staticmethod(lambda: None))
        assert gnome_shell_present() is False
