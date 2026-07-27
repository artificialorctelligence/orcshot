"""Autostart-on-login .desktop entry generation and installation.

Unlike hotkey_setup.py's gsettings/dconf writes (global session state
with no safe way to test without touching the live system),
a .desktop autostart entry is just a plain file - install_autostart_entry
is exercised for real here, but only ever against a pytest tmp_path,
never the user's actual ~/.config/autostart/. Nothing in this codebase
calls it against the real default path automatically; enabling
autostart for real is a standing, persistent login-behavior change the
user (or a future session, explicitly asked to) should trigger.
"""

from greenshot_linux.autostart import (
    DESKTOP_ENTRY_FILENAME,
    autostart_desktop_entry,
    autostart_file_path,
    install_autostart_entry,
)


class TestAutostartDesktopEntry:
    def test_includes_the_exec_command(self):
        content = autostart_desktop_entry("/usr/bin/greenshot-linux --tray")
        assert "Exec=/usr/bin/greenshot-linux --tray" in content

    def test_is_a_valid_desktop_entry_header(self):
        content = autostart_desktop_entry("greenshot-linux")
        assert content.startswith("[Desktop Entry]\n")

    def test_has_the_fields_a_desktop_environment_expects(self):
        content = autostart_desktop_entry("greenshot-linux")
        assert "Type=Application" in content
        assert "Name=Greenshot Linux" in content
        assert "X-GNOME-Autostart-enabled=true" in content


class TestAutostartFilePath:
    def test_uses_xdg_config_home_when_given(self, tmp_path):
        path = autostart_file_path(config_home=tmp_path)
        assert path == tmp_path / "autostart" / DESKTOP_ENTRY_FILENAME

    def test_defaults_to_the_real_xdg_config_home_when_not_given(self):
        # Just confirms it resolves to *something* sensible without
        # touching the filesystem - the actual value depends on this
        # machine's environment, not asserted precisely here.
        path = autostart_file_path()
        assert path.name == DESKTOP_ENTRY_FILENAME
        assert path.parent.name == "autostart"


class TestInstallAutostartEntry:
    def test_writes_the_file_and_returns_its_path(self, tmp_path):
        result = install_autostart_entry("greenshot-linux --tray", autostart_dir=tmp_path / "autostart")

        assert result == tmp_path / "autostart" / DESKTOP_ENTRY_FILENAME
        assert result.exists()
        assert "Exec=greenshot-linux --tray" in result.read_text()

    def test_creates_the_autostart_directory_if_missing(self, tmp_path):
        target_dir = tmp_path / "does" / "not" / "exist" / "autostart"
        result = install_autostart_entry("greenshot-linux", autostart_dir=target_dir)
        assert result.exists()

    def test_overwrites_an_existing_entry(self, tmp_path):
        autostart_dir = tmp_path / "autostart"
        install_autostart_entry("old-command", autostart_dir=autostart_dir)
        result = install_autostart_entry("new-command", autostart_dir=autostart_dir)
        assert "Exec=new-command" in result.read_text()
        assert "old-command" not in result.read_text()
