"""Persistent app settings: currently just the screenshot save
directory (configurable from the editor - see ui/editor_window.py's
save-location button, and used by the destination picker's silent
"Save" action - see ui/destination_picker.py) and a one-time "first-run
setup already ran" flag (see ui/first_run_setup.py, which prompts once
to enable autostart + the capture hotkeys).

Same testing approach as autostart.py's .desktop entry: a plain JSON
file per the XDG Base Directory spec, real file I/O exercised for real
in tests against a temp path - no injectable backend abstraction
needed the way hotkey_setup.py's gsettings writes require, since a
JSON file (unlike global desktop session state) is safe to read/write
for real without touching anything outside this app.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

CONFIG_FILENAME = "config.json"
_OUTPUT_DIRECTORY_KEY = "output_directory"
_FIRST_RUN_SETUP_DONE_KEY = "first_run_setup_done"
_DEFAULT_OUTPUT_DIRNAME = "Screenshots"


def config_file_path(config_home: Path = None) -> Path:
    """Where the settings file belongs, per the XDG Base Directory
    spec: $XDG_CONFIG_HOME/greenshot-linux/config.json, defaulting to
    ~/.config/greenshot-linux/config.json.
    """
    if config_home is None:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "greenshot-linux" / CONFIG_FILENAME


def default_output_directory() -> Path:
    """~/Pictures/Screenshots if a Pictures folder exists (the common
    convention across Linux desktops), else ~/Screenshots.
    """
    pictures = Path.home() / "Pictures"
    base = pictures if pictures.is_dir() else Path.home()
    return base / _DEFAULT_OUTPUT_DIRNAME


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save(settings: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2))


def get_output_directory(path: Path = None) -> Path:
    if path is None:
        path = config_file_path()
    value = _load(path).get(_OUTPUT_DIRECTORY_KEY)
    return Path(value) if value is not None else default_output_directory()


def set_output_directory(directory: Path, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_OUTPUT_DIRECTORY_KEY] = str(directory)
    _save(settings, path)


def quick_save_filename(when: datetime) -> str:
    """The filename a silent quick-save (destination picker's "Save",
    see ui/destination_picker.py) writes to. Matches Windows' own
    default OutputFileFilenamePattern timestamp format (yyyy-MM-dd
    HH_mm_ss) but deliberately drops its "-${title}" suffix - not
    every capture mode here has a single associated window title
    (region/full-screen capture don't).
    """
    return when.strftime("%Y-%m-%d %H_%M_%S") + ".png"


def is_first_run_setup_done(path: Path = None) -> bool:
    if path is None:
        path = config_file_path()
    return _load(path).get(_FIRST_RUN_SETUP_DONE_KEY, False)


def mark_first_run_setup_done(path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_FIRST_RUN_SETUP_DONE_KEY] = True
    _save(settings, path)
