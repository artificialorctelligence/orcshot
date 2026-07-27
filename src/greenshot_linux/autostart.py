"""Autostart-on-login .desktop entry, so the tray icon is always
present after login - matching the Windows source's "run at startup"
behavior (REQUIREMENTS.md's Global activation section).

Unlike hotkey_setup.py's gsettings/dconf writes (global session state
with no safe way to test without touching the live system), a
.desktop autostart entry is just a plain file per the XDG Desktop
Entry / Autostart specs - install_autostart_entry is real, working
code, exercised for real in tests (against a temp directory, never the
real default path). Nothing in this codebase calls it against the
actual default ~/.config/autostart/ automatically: enabling autostart
for real is a standing, persistent login-behavior change, the same
category of action hotkey_setup.py's module docstring explains the
project's general caution around - the user (or a future session,
explicitly asked to) should trigger it themselves.
"""

from __future__ import annotations

import os
from pathlib import Path

from greenshot_linux.resources import LOGO_PATH

DESKTOP_ENTRY_FILENAME = "greenshot-linux.desktop"


def autostart_desktop_entry(exec_command: str) -> str:
    """The .desktop file content for autostart-on-login."""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Greenshot Linux\n"
        "Comment=Screenshot capture and annotation tool\n"
        f"Exec={exec_command}\n"
        f"Icon={LOGO_PATH}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def autostart_file_path(config_home: Path = None) -> Path:
    """Where the autostart entry belongs, per the XDG Base Directory
    spec: $XDG_CONFIG_HOME/autostart/, defaulting to ~/.config/autostart/.
    """
    if config_home is None:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "autostart" / DESKTOP_ENTRY_FILENAME


def install_autostart_entry(exec_command: str, autostart_dir: Path = None) -> Path:
    """Writes the autostart entry, creating the directory if needed,
    and returns the path written. ``autostart_dir`` is injectable (for
    tests); the default resolves to the real XDG autostart directory.
    """
    if autostart_dir is None:
        autostart_dir = autostart_file_path().parent
    autostart_dir.mkdir(parents=True, exist_ok=True)
    path = autostart_dir / DESKTOP_ENTRY_FILENAME
    path.write_text(autostart_desktop_entry(exec_command))
    return path
