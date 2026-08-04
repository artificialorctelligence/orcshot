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
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

CONFIG_FILENAME = "config.json"
_OUTPUT_DIRECTORY_KEY = "output_directory"
_FIRST_RUN_SETUP_DONE_KEY = "first_run_setup_done"
_CAPTURE_MOUSE_CURSOR_KEY = "capture_mouse_cursor"
_PRINT_OPTIONS_KEY = "print_options"
_RECENT_COLORS_KEY = "recent_colors"
_EXTERNAL_EDITOR_KEY = "external_editor"
_DEFAULT_OUTPUT_DIRNAME = "Screenshots"
EXTERNAL_EDITOR_AUTO = "auto"


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


def get_capture_mouse_cursor(path: Path = None) -> bool:
    """Whether to draw the mouse cursor into new captures - faithful
    port of Windows' "Capture mousepointer" Preferences checkbox
    (ICoreConfiguration.cs:79-81, default True). See
    ui/capture_modes.py etc. for where this is actually applied, and
    app.py's tray-menu-vs-hotkey asymmetry, which this setting alone
    doesn't fully determine.
    """
    if path is None:
        path = config_file_path()
    return _load(path).get(_CAPTURE_MOUSE_CURSOR_KEY, True)


def set_capture_mouse_cursor(enabled: bool, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_CAPTURE_MOUSE_CURSOR_KEY] = enabled
    _save(settings, path)


def get_recent_colors(path: Path = None) -> list:
    """Up to 12 (RECENT_COLORS_MAX, core/color_palette.py) most-
    recently-picked colors from the editor's color dialog, newest
    first - faithful port of IEditorConfiguration.RecentColors
    (IEditorConfiguration.cs:36-42), an ini-backed list that survives
    app restarts on Windows too. Stored as JSON lists (no tuple type
    in JSON), converted back to (r, g, b, a) tuples on load to match
    core/color_palette.py's Color type.
    """
    if path is None:
        path = config_file_path()
    saved = _load(path).get(_RECENT_COLORS_KEY, [])
    return [tuple(color) for color in saved]


def set_recent_colors(colors: list, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_RECENT_COLORS_KEY] = [list(color) for color in colors]
    _save(settings, path)


@dataclass(frozen=True)
class PrintOptions:
    """Faithful port of PrintOptionsDialog's settings
    (Greenshot/Forms/PrintOptionsDialog.cs, backed by
    ICoreConfiguration.cs:166-209) - defaults match Windows' own.
    Bundled as one dataclass rather than 9 separate get_x/set_x pairs,
    since they're always edited together in one dialog
    (ui/printing.py) and applied together to one print job.
    """

    prompt_options: bool = True  # OutputPrintPromptOptions
    allow_shrink: bool = True  # OutputPrintAllowShrink
    allow_enlarge: bool = False  # OutputPrintAllowEnlarge
    allow_rotate: bool = False  # OutputPrintAllowRotate
    center: bool = True  # OutputPrintCenter
    footer: bool = True  # OutputPrintFooter
    grayscale: bool = False  # OutputPrintGrayscale
    monochrome: bool = False  # OutputPrintMonochrome
    monochrome_threshold: int = 127  # OutputPrintMonochromeThreshold
    inverted: bool = False  # OutputPrintInverted


def get_print_options(path: Path = None) -> PrintOptions:
    if path is None:
        path = config_file_path()
    saved = _load(path).get(_PRINT_OPTIONS_KEY, {})
    defaults = asdict(PrintOptions())
    defaults.update({k: v for k, v in saved.items() if k in defaults})
    return PrintOptions(**defaults)


def set_print_options(options: PrintOptions, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_PRINT_OPTIONS_KEY] = asdict(options)
    _save(settings, path)


def get_external_editor_preference(path: Path = None) -> str:
    """Which editor ui/editor_window.py's "Open in External Editor"
    button should prefer - a name from EditorWindow's own
    _EXTERNAL_EDITOR_CANDIDATES (e.g. "Krita", "GIMP"), or
    EXTERNAL_EDITOR_AUTO (the default) for the original try-Krita-
    then-GIMP behavior. Not a Windows setting - this whole feature is
    a new addition, not a port (see editor_window.py's own comment on
    _EXTERNAL_EDITOR_CANDIDATES).
    """
    if path is None:
        path = config_file_path()
    return _load(path).get(_EXTERNAL_EDITOR_KEY, EXTERNAL_EDITOR_AUTO)


def set_external_editor_preference(name: str, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_EXTERNAL_EDITOR_KEY] = name
    _save(settings, path)


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
