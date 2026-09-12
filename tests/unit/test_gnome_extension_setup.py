"""Pure coverage for gnome_extension_setup.py - gnome_shell_present()
and the real Gio.Settings write are excluded for the same reason
hotkey_setup.py's equivalents are (see that module's docstring):
touching the real desktop is reserved for a user-confirmed dialog
click, never a test.
"""

from orcshot.gnome_extension_setup import (
    EXTENSION_UUID,
    bundled_version_name,
    enable_extension,
    enabled_extensions_after_adding,
    extensions_to_enable,
    gnome_shell_present,
    needs_relogin,
)

# The one UUID, under the names the older tests below used.
# The older tests below predate the merge and name the UUID by its old roles.
WINDOW_CALLS_EXTENSION_UUID = CLIPBOARD_EXTENSION_UUID = TRAY_EXTENSION_UUID = EXTENSION_UUID


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

    def test_enabling_the_one_extension_is_idempotent(self):
        backend = FakeSettingsBackend()
        enable_extension(backend, EXTENSION_UUID)
        enable_extension(backend, EXTENSION_UUID)
        assert backend.get_strv("org.gnome.shell", "/", "enabled-extensions") == [EXTENSION_UUID]


class TestExtensionsToEnable:
    """One extension carries tray, capture and window-calls since the
    2026-09-11 spec; the tray is wanted on X11 too, so the session type
    no longer changes the answer."""

    def test_wayland_enables_the_one_extension(self):
        assert extensions_to_enable(is_gnome_wayland=True) == [EXTENSION_UUID]

    def test_x11_enables_it_too_for_the_tray(self):
        assert extensions_to_enable(is_gnome_wayland=False) == [EXTENSION_UUID]


class TestVersionName:
    def test_bundled_version_name_is_a_dotted_version(self):
        name = bundled_version_name()
        assert name and all(part.isdigit() for part in name.split("."))

    def test_needs_relogin_when_live_is_older(self):
        assert needs_relogin("0.3.0", "0.4.0") is True

    def test_no_relogin_when_equal_or_newer(self):
        assert needs_relogin("0.4.0", "0.4.0") is False
        assert needs_relogin("0.5.0", "0.4.0") is False

    def test_no_relogin_when_no_extension_at_all(self):
        assert needs_relogin(None, "0.4.0") is False


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
