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

from orcshot.core.filename_pattern import DEFAULT_FILENAME_PATTERN

CONFIG_FILENAME = "config.json"
_OUTPUT_DIRECTORY_KEY = "output_directory"
_FIRST_RUN_SETUP_DONE_KEY = "first_run_setup_done"
_DEFAULT_EXTERNAL_COMMANDS_SEEDED_KEY = "default_external_commands_seeded"
_CAPTURE_MOUSE_CURSOR_KEY = "capture_mouse_cursor"
_PRINT_OPTIONS_KEY = "print_options"
_RECENT_COLORS_KEY = "recent_colors"
_EXTERNAL_EDITOR_KEY = "external_editor"
_SUPPRESS_SAVE_DIALOG_AT_CLOSE_KEY = "suppress_save_dialog_at_close"
_FILENAME_COUNTER_KEY = "filename_counter"
_FOOTER_PATTERN_KEY = "footer_pattern"
_EXTERNAL_COMMANDS_KEY = "external_commands"
_ICON_SIZE_KEY = "icon_size"
_USE_DEFAULT_PROXY_KEY = "use_default_proxy"
_UPDATE_CHECK_INTERVAL_DAYS_KEY = "update_check_interval_days"
_LAST_UPDATE_CHECK_KEY = "last_update_check"
_OUTPUT_SETTINGS_KEY = "output_settings"
_EXCLUDED_DESTINATIONS_KEY = "excluded_destinations"
_SHOW_MAGNIFIER_WHILE_SELECTING_KEY = "show_magnifier_while_selecting"
_LANGUAGE_KEY = "language"
_PLAY_CAPTURE_SOUND_KEY = "play_capture_sound"
_SHOW_CAPTURE_NOTIFICATION_KEY = "show_capture_notification"
_REUSE_EDITOR_KEY = "reuse_editor"
_DEFAULT_OUTPUT_DIRNAME = "Screenshots"
_DEFAULT_FOOTER_PATTERN = "%B %d, %Y %I:%M %p"
_DEFAULT_ICON_SIZE = 24
EXTERNAL_EDITOR_AUTO = "auto"


def config_file_path(config_home: Path = None) -> Path:
    """Where the settings file belongs, per the XDG Base Directory
    spec: $XDG_CONFIG_HOME/orcshot/config.json, defaulting to
    ~/.config/orcshot/config.json.
    """
    if config_home is None:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "orcshot" / CONFIG_FILENAME


def quit_marker_path(config_home: Path = None) -> Path:
    """Task #150 follow-up: a real, explicit "the user just quit"
    marker, next to config.json. Global capture hotkeys (hotkey_setup.py)
    are registered as OS-level "run this command" keybindings
    (Cinnamon/GNOME custom-keybindings), independent of whether an
    Orcshot process is currently running - direflail's own stated
    requirement ("when the user selects quit... it should not be
    running anymore... it should remain this way until the user
    restarts") can't be honored just by the process actually exiting
    (confirmed it already does, live, nothing left in `ps aux`), since
    the very next hotkey press launches a brand new instance from
    scratch regardless - live-reported: "pressing prtscr starts a
    capture in orcshot and then brings the icon back" after quitting.
    This marker is app.py's main()'s way of telling a hotkey-triggered
    relaunch apart from a real, intentional reopen (the two are
    otherwise indistinguishable from argv alone) - see main()'s own
    comment for the actual check.
    """
    if config_home is None:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "orcshot" / "quit.marker"


def write_quit_marker(path: Path = None) -> None:
    if path is None:
        path = quit_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def clear_quit_marker(path: Path = None) -> None:
    if path is None:
        path = quit_marker_path()
    path.unlink(missing_ok=True)


def is_quit_marker_set(path: Path = None) -> bool:
    if path is None:
        path = quit_marker_path()
    return path.exists()


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


def quick_save_filename(when: datetime, counter: int) -> str:
    """The filename a silent quick-save (destination picker's "Save",
    see ui/destination_picker.py) writes to. Matches Windows' own
    default OutputFileFilenamePattern timestamp format (yyyy-MM-dd
    HH_mm_ss) but deliberately drops its "-${title}" suffix - not
    every capture mode here has a single associated window title
    (region/full-screen capture don't).

    ``counter`` is this port's equivalent of Windows' ${NUM} filename
    token (OutputFileIncrementingNumber, ICoreConfiguration.cs:163-165)
    - always appended here rather than an opt-in pattern placeholder,
    since this port has no editable filename-pattern template. Callers
    get the value to pass from get_filename_counter (peek, e.g. for a
    Save As dialog's suggested name) or consume_filename_counter (peek
    + advance, for a save that's actually happening).
    """
    return f"{when.strftime('%Y-%m-%d %H_%M_%S')} ({counter:03d}).png"


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


def get_play_capture_sound(path: Path = None) -> bool:
    """Faithful port of Windows' "Play camera sound" Capture-tab
    checkbox (ICoreConfiguration.cs's PlayCameraSound) - see
    capture/capture_feedback.py for where this is actually applied (a
    themed system sound played once a capture completes, right before
    the destination-choosing UI appears - matching CaptureHelper.cs's
    own DoCaptureFeedback timing). Default False - a deliberate
    divergence from Windows' own default True, direflail's explicit
    call after noticing the sound audibly lags the picker's own
    appearance by a beat (GSound/canberra's first PulseAudio
    connection of the session, not a bug - see this port's own
    REQUIREMENTS.md for the full context)."""
    if path is None:
        path = config_file_path()
    return _load(path).get(_PLAY_CAPTURE_SOUND_KEY, False)


def set_play_capture_sound(enabled: bool, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_PLAY_CAPTURE_SOUND_KEY] = enabled
    _save(settings, path)


def get_reuse_editor(path: Path = None) -> bool:
    """Faithful port of Windows' "Reuse Editor" Expert-tab checkbox
    (IEditorConfiguration.ReuseEditor, EditorDestination.cs:96):
    when true, a new capture reuses the most-recently-opened still-open
    editor (OrcshotApplication.topmost_editor()) instead of opening a
    second window, but only if that editor has no unsaved changes
    (EditorWindow.is_modified) - see ui/destination_picker.py's
    _open_editor for where this is actually applied. Default False,
    matching real Greenshot's own default (BACKLOG #179)."""
    if path is None:
        path = config_file_path()
    return _load(path).get(_REUSE_EDITOR_KEY, False)


def set_reuse_editor(enabled: bool, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_REUSE_EDITOR_KEY] = enabled
    _save(settings, path)


def get_show_capture_notification(path: Path = None) -> bool:
    """Faithful port of Windows' "Show notification" Capture-tab
    checkbox (ICoreConfiguration.cs's ShowTrayNotification) - see
    capture/capture_feedback.py for where this is actually applied.
    Default False - a deliberate divergence from Windows' own default
    True, same reasoning as get_play_capture_sound's own default:
    direflail's explicit call after live-testing it fires the same
    system notification.oga sound already tracked down and defaulted
    off for the camera-shutter sound, and unlike Windows' own version
    (a real per-destination outcome message, "Saved to X") this port's
    simplified notification just says a capture happened - lower
    value, same noise, live-reported as unwanted at that price."""
    if path is None:
        path = config_file_path()
    return _load(path).get(_SHOW_CAPTURE_NOTIFICATION_KEY, False)


def set_show_capture_notification(enabled: bool, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_SHOW_CAPTURE_NOTIFICATION_KEY] = enabled
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


@dataclass(frozen=True)
class OutputSettings:
    """Faithful port of the Output tab's two groupboxes
    (SettingsForm.Designer.cs's groupbox_preferredfilesettings +
    groupbox_qualitysettings, backed by ICoreConfiguration.cs:126-160)
    - defaults match Windows' own. Bundled as one dataclass rather than
    separate get_x/set_x pairs, matching PrintOptions' own rationale:
    always edited together in one Preferences tab.

    ``filename_pattern`` uses core/filename_pattern.py's own unified
    token language (task #171) - Greenshot-style ``${TOKEN}``
    substitution and standard strftime ``%`` directives are both
    always active in the same pattern, not a mode-gated choice between
    them (see that module's own docstring for the full reasoning, and
    for why an earlier ``filename_pattern_mode`` field - since removed
    - could drift out of sync with the pattern text on its own).

    ``reduce_colors`` is persisted but not yet applied to a save - see
    _do_quick_save/_do_save's own notes; a real, documented gap rather
    than a fake control.
    """

    filename_pattern: str = DEFAULT_FILENAME_PATTERN  # OutputFileFilenamePattern (this port's own default, see the module docstring)
    primary_format: str = "png"  # OutputFileFormat
    copy_path_to_clipboard: bool = True  # OutputFileCopyPathToClipboard
    reduce_colors: bool = False  # OutputFileReduceColors
    always_show_quality_dialog: bool = False  # OutputFilePromptQuality
    jpeg_quality: int = 80  # OutputFileJpegQuality


def get_output_settings(path: Path = None) -> OutputSettings:
    if path is None:
        path = config_file_path()
    saved = _load(path).get(_OUTPUT_SETTINGS_KEY, {})
    defaults = asdict(OutputSettings())
    defaults.update({k: v for k, v in saved.items() if k in defaults})
    return OutputSettings(**defaults)


def set_output_settings(settings_: OutputSettings, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_OUTPUT_SETTINGS_KEY] = asdict(settings_)
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


def get_suppress_save_dialog_at_close(path: Path = None) -> bool:
    """Faithful port of IEditorConfiguration.SuppressSaveDialogAtClose
    (IEditorConfiguration.cs:83-85, default False) - whether closing an
    editor with unsaved changes skips the "Save image?" Yes/No/Cancel
    prompt (see ui/editor_window.py's EditorWindow._on_delete_event,
    a port of ImageEditorFormFormClosing, ImageEditorForm.cs:1004-1033).
    """
    if path is None:
        path = config_file_path()
    return _load(path).get(_SUPPRESS_SAVE_DIALOG_AT_CLOSE_KEY, False)


def set_suppress_save_dialog_at_close(enabled: bool, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_SUPPRESS_SAVE_DIALOG_AT_CLOSE_KEY] = enabled
    _save(settings, path)


def get_filename_counter(path: Path = None) -> int:
    """Faithful port of OutputFileIncrementingNumber (ICoreConfiguration
    .cs:163-165, default 1) - the number quick_save_filename appends to
    each generated filename. Use this (peek, no side effect) for
    display or a suggested-but-not-yet-committed filename (e.g. Save
    As's default name); use consume_filename_counter for a save that's
    actually about to happen.
    """
    if path is None:
        path = config_file_path()
    return _load(path).get(_FILENAME_COUNTER_KEY, 1)


def set_filename_counter(value: int, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_FILENAME_COUNTER_KEY] = value
    _save(settings, path)


def consume_filename_counter(path: Path = None) -> int:
    """Returns the counter value to use for the save happening right
    now, then persists it incremented by one - matches Windows' own
    doc comment on OutputFileIncrementingNumber: "is increased
    automatically after each save."
    """
    if path is None:
        path = config_file_path()
    current = get_filename_counter(path)
    set_filename_counter(current + 1, path)
    return current


def get_footer_pattern(path: Path = None) -> str:
    """Faithful-in-spirit port of Windows' "Printer footer pattern"
    Expert setting (ICoreConfiguration.cs:206-209,
    OutputPrintFooterPattern). Windows' own default is a token pattern
    (``${capturetime:d"D"} ${capturetime:d"T"} - ${title}``) resolved
    by its own template engine; this port has no such engine (nor a
    per-capture title to substitute - see ui/printing.py's
    _footer_text docstring), so the setting is a plain strftime format
    string instead. The default matches what ui/printing.py's
    _footer_text already hardcoded before this setting existed
    ("%B %d, %Y %I:%M %p"), so a fresh install prints the same footer
    as before.
    """
    if path is None:
        path = config_file_path()
    return _load(path).get(_FOOTER_PATTERN_KEY, _DEFAULT_FOOTER_PATTERN)


def set_footer_pattern(pattern: str, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_FOOTER_PATTERN_KEY] = pattern
    _save(settings, path)


def get_icon_size(path: Path = None) -> int:
    """Faithful-in-spirit port of Windows' "Icon size" Application
    setting (ICoreConfiguration.cs:365-368, IconSize, a 16x16 NativeSize
    scaled to DPI) - a single square px value here (this port renders
    its own icons rather than loading DPI-scaled bitmap resources, so
    there's no separate width/height to track). Default is 24, not
    Windows' 16 - matches ui/icons.py's own long-standing ICON_SIZE
    constant, which was already a deliberate, unrelated sizing choice
    for legibility on typical Linux displays; this setting makes that
    value configurable rather than changing what a fresh install looks
    like. Range (16-256 step 16) is Windows' own spinner's, enforced by
    the Preferences UI, not here.
    """
    if path is None:
        path = config_file_path()
    return _load(path).get(_ICON_SIZE_KEY, _DEFAULT_ICON_SIZE)


def set_icon_size(size: int, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_ICON_SIZE_KEY] = size
    _save(settings, path)


def get_use_default_proxy(path: Path = None) -> bool:
    """Faithful port of Windows' "Use your global proxy?" Network
    setting (ICoreConfiguration.cs:215-217, UseProxy, default True).
    Windows reads its "global proxy" from WinINet/IE's system proxy
    settings; the Linux equivalent this port actually honors when this
    is enabled is the standard `http_proxy`/`https_proxy`/`no_proxy`
    environment variables (what every well-behaved Linux HTTP client,
    including Python's own urllib/requests, already checks by default)
    - there is no single OS-wide GNOME/system proxy API as
    universally honored as Windows' WinINet is. Currently has nowhere
    to plug in (this port makes no network requests at all yet - see
    task #103's eventual update checker), ported now as a persisted,
    documented placeholder so #103's own eventual checker just reads
    an existing value rather than also inventing where it lives.
    """
    if path is None:
        path = config_file_path()
    return _load(path).get(_USE_DEFAULT_PROXY_KEY, True)


def set_use_default_proxy(enabled: bool, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_USE_DEFAULT_PROXY_KEY] = enabled
    _save(settings, path)


def get_update_check_interval_days(path: Path = None) -> int:
    """Faithful port of Windows' "How many days between every update
    check?" Network setting (ICoreConfiguration.cs:233-236,
    UpdateCheckInterval, default 14, 0=no checks). Stub - this port has
    no update-checking system at all yet (task #103); persisted now so
    #103's eventual checker reads an existing value rather than also
    inventing where it lives, matching get_check_unstable_updates.
    """
    if path is None:
        path = config_file_path()
    return _load(path).get(_UPDATE_CHECK_INTERVAL_DAYS_KEY, 14)


def set_update_check_interval_days(days: int, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_UPDATE_CHECK_INTERVAL_DAYS_KEY] = days
    _save(settings, path)


def get_last_update_check(path: Path = None) -> datetime | None:
    """Faithful port of Windows' own LastUpdateCheck
    (ICoreConfiguration.cs) - when the periodic checker (task #103,
    core/update_check.py's should_check_now) last actually ran, so a
    restart doesn't immediately re-check just because there's no
    in-memory state left. None means "never checked yet".
    """
    if path is None:
        path = config_file_path()
    raw = _load(path).get(_LAST_UPDATE_CHECK_KEY)
    return datetime.fromisoformat(raw) if raw else None


def set_last_update_check(when: datetime, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_LAST_UPDATE_CHECK_KEY] = when.isoformat()
    _save(settings, path)


@dataclass(frozen=True)
class ExternalCommand:
    """Faithful port of one entry in the ExternalCommand plugin's
    config (IExternalCommandConfiguration.cs:35-67: Commands is a
    List<string> of names, with Commandline/Argument/RunInbackground
    as parallel Dictionary<string, *> maps keyed by that same name) -
    collapsed into one dataclass per command here rather than three
    parallel dicts, since Python has no ini-section auto-binding to
    preserve and a list of these round-trips through JSON just as
    well. ``OutputFormat`` (per-command output file type) is dropped -
    this port's own save path always writes PNG (ui/file_export.py
    infers format from the target extension, and every caller here
    always asks for .png), so there's no per-command format to choose.

    ``argument`` is a Python str.format template - ``{0}`` is replaced
    with the exported screenshot's path (ui/external_commands.py's
    build_command_argv), matching Windows' own
    ``string.Format(arguments, safePath)`` (ExternalCommandDestination
    .cs:310) exactly, just spelled with Python's formatting syntax
    instead of C#'s.
    """

    name: str
    commandline: str
    argument: str = "{0}"
    run_in_background: bool = True


def get_external_commands(path: Path = None) -> list[ExternalCommand]:
    if path is None:
        path = config_file_path()
    saved = _load(path).get(_EXTERNAL_COMMANDS_KEY, [])
    return [ExternalCommand(**entry) for entry in saved]


def set_external_commands(commands: list[ExternalCommand], path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_EXTERNAL_COMMANDS_KEY] = [asdict(command) for command in commands]
    _save(settings, path)


def get_excluded_destinations(path: Path = None) -> set[str]:
    """Faithful port of Windows' "Comma separated list of destinations
    which should be disabled" (ExcludeDestinations, ICoreConfiguration.
    cs:230-231) - task #95's Destinations tab. An *exclude* list, not
    an include list, matching Windows exactly and deliberately: a
    newly-added destination (a future built-in, or a freshly-created
    ExternalCommand) is enabled by default without this needing an
    update, rather than silently invisible until the user opts it in.
    """
    if path is None:
        path = config_file_path()
    return set(_load(path).get(_EXCLUDED_DESTINATIONS_KEY, []))


def set_excluded_destinations(destination_ids: set[str], path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_EXCLUDED_DESTINATIONS_KEY] = sorted(destination_ids)
    _save(settings, path)


def get_show_magnifier_while_selecting(path: Path = None) -> bool:
    """Faithful port of Windows' "zoomer" setting (ZoomerEnabled,
    ICoreConfiguration.cs:318-320, default True) - task #95's Capture
    tab. Wired into ui/region_select.py's X11 path
    (RegionSelectWindow._on_draw's magnifier call); the Wayland Shell-
    native path (task #82's own GJS port of the same magnifier,
    RegionSelectOverlay in the bundled extension) does NOT read this
    yet - it's separate JS code with no channel to this JSON file
    without adding one to the D-Bus call that starts it, out of scope
    for this pass. A real, documented platform gap, not a silent one -
    the magnifier still always shows there regardless of this setting.
    """
    if path is None:
        path = config_file_path()
    return _load(path).get(_SHOW_MAGNIFIER_WHILE_SELECTING_KEY, True)


def set_show_magnifier_while_selecting(enabled: bool, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_SHOW_MAGNIFIER_WHILE_SELECTING_KEY] = enabled
    _save(settings, path)


def get_language(path: Path = None) -> str:
    """The user's language override for the Preferences "Language"
    picker (i18n phase 2) - "" (the default) means "System Default":
    follow the OS locale via gettext's own standard $LANGUAGE/$LC_ALL/
    $LC_MESSAGES/$LANG negotiation, same as before this setting
    existed. A non-empty value is a gettext language code (e.g. "es")
    read by orcshot.i18n at import time to override that negotiation -
    see that module's own docstring for why a *running* process can't
    pick this up live (every module-level _()-bound string, and there
    are hundreds, is fixed at its own import time), so changing this
    only takes effect after a restart, not immediately.
    """
    if path is None:
        path = config_file_path()
    return _load(path).get(_LANGUAGE_KEY, "")


def set_language(language: str, path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_LANGUAGE_KEY] = language
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


def is_default_external_commands_seeded(path: Path = None) -> bool:
    if path is None:
        path = config_file_path()
    return _load(path).get(_DEFAULT_EXTERNAL_COMMANDS_SEEDED_KEY, False)


def mark_default_external_commands_seeded(path: Path = None) -> None:
    if path is None:
        path = config_file_path()
    settings = _load(path)
    settings[_DEFAULT_EXTERNAL_COMMANDS_SEEDED_KEY] = True
    _save(settings, path)
