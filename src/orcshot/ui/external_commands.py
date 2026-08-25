"""ExternalCommand-style destinations (task #110): named, persistently
stored shell commands, each becoming its own destination-picker entry
that runs against the just-captured screenshot's file path.

Faithful port of the real ExternalCommand plugin's core idea
(Greenshot.Plugin.ExternalCommand - ExternalCommandPlugin.cs,
ExternalCommandDestination.cs, SettingsForm.cs/SettingsFormDetail.cs),
confirmed via source during task #93's Plugins-tab audit: Commands is
a List<string> of names with parallel Dictionary<string, *> maps for
Commandline/Argument/RunInbackground, so it genuinely supports
multiple independently-configured, persistently-stored commands (not
a one-shot single command) - built-ins like "MS Paint"/"Paint.NET" are
just pre-populated entries in the same list. See settings.py's
ExternalCommand dataclass for the config shape.

Deliberately not ported from the real plugin:
- Per-command OutputFormat (ExternalCommand's own docstring - this
  port's save path is PNG-only).
- URI-detection-in-stdout-then-clipboard (ExternalCommandDestination
  .cs:149-164, config.OutputToClipboard/UriToClipboard) - a genuinely
  separate sub-feature (useful for a command that uploads somewhere
  and prints a URL), not core to "run a command with the screenshot's
  path". Left for later if wanted.
- The Windows "runas" elevation retry (CallExternalCommand's Win32Exception
  fallback) - a UAC-specific concept with no Linux equivalent.

Only build_command_argv and run_external_command are unit tested
(pure argv-building logic, plus the settings round-trip already
covered in test_settings.py) - the two dialogs below are GTK glue with
no meaningful headless test, same as destination_picker.py/printing.py
(see their own docstrings). Verified live: added a command pointing at
a real script, confirmed it ran with the exported screenshot's path as
its argument, confirmed stderr from a deliberately-failing command was
logged rather than silently swallowed.
"""

from __future__ import annotations

import configparser
import http.client
import json
import logging
import os
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from orcshot.core.update_check import is_newer_version
from orcshot.i18n import _
from orcshot.settings import (
    ExternalCommand,
    get_external_commands,
    is_default_external_commands_seeded,
    mark_default_external_commands_seeded,
    set_external_commands,
)
from orcshot.ui.file_export import orcshot_cache_dir, orcshot_visible_temp_dir, save_image_to_file

_LOG = logging.getLogger(__name__)
_DEFAULT_ARGUMENT_TEMPLATE = "{0}"
# Real Windows has no such cap (WaitForExit() blocks forever) - added
# here so a hung external process can't leak a background thread
# forever. Generous enough that no normal use (opening an app,
# running a quick upload script) should ever hit it.
_TIMEOUT_SECONDS = 300
_SNAPD_SOCKET = "/run/snapd.socket"
# XDG Desktop Entry lookup order (freedesktop spec): user's own
# launcher files take precedence over the system-wide ones on a
# filename collision.
_DESKTOP_APP_DIRS = (Path.home() / ".local/share/applications", Path("/usr/share/applications"))
_EXEC_FIELD_CODES = re.compile(r"%[fFuUdDnNickvm%]")


def _is_snap_command(commandline: str) -> bool:
    """Whether ``commandline`` (either a full path or a bare name
    resolved via $PATH, both valid per _validate below) is a Snap
    package's own CLI wrapper - task #166. Snap always installs these
    at /snap/bin/<name> regardless of the package, a reliable signal
    with no need to shell out to `snap` itself. shutil.which first so
    a bare name like "krita" resolves the same way _validate's own
    executable check already does, before checking the resolved path.

    abspath, not realpath - confirmed live (direflail, task #166):
    /snap/bin/<name> entries are themselves symlinks to /usr/bin/snap
    (snapd's own generic launcher, which inspects the symlink's own
    name to decide which snap to actually run), so realpath resolves
    straight past the one signal this needs to detect, following the
    symlink to a target that's never under /snap/ at all. abspath
    only normalizes the path string (., .., double slashes) without
    following symlinks, so the /snap/bin/ prefix survives.
    """
    resolved = shutil.which(commandline) or commandline
    return os.path.abspath(resolved).startswith("/snap/")


class _UnixSocketHTTPConnection(http.client.HTTPConnection):
    """A plain http.client.HTTPConnection pointed at a Unix domain
    socket instead of a TCP one - the standard trick for talking to a
    local daemon's own REST-style API (the same pattern Docker's own
    Python SDK uses for /var/run/docker.sock) - overriding just the
    one method that opens the underlying socket, "connect", is enough
    to reuse the whole HTTP request/response machinery unchanged, no
    third-party dependency needed for something the stdlib already
    covers with one method override.
    """

    def __init__(self, socket_path: str):
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._socket_path)


def _query_snapd(path: str) -> dict:
    """Raw JSON GET against snapd's own local REST API, task #166
    follow-up (the "Find App" search) - confirmed live this is purely
    local IPC, not a network call: /run/snapd.socket is a Unix domain
    socket (a local file, not an IP/port), the same daemon that
    already manages installed snaps on this machine. Thin I/O, no
    meaningful headless test beyond what _installed_snap_apps below
    already covers by mocking this function entirely.
    """
    connection = _UnixSocketHTTPConnection(_SNAPD_SOCKET)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return json.loads(response.read())
    finally:
        connection.close()


def _installed_snap_apps() -> list[tuple[str, str, str]]:
    """(name, title, version) for every installed Snap of type "app"
    that actually has something to launch - task #166 follow-up.
    Filters out "base"/"snapd"/"kernel"/"gadget" entries (confirmed
    live against this dev machine's real /v2/snaps: core22/snapd
    themselves show up there too, neither of which a user would ever
    pick as an external command). type == "app" alone isn't enough,
    though - live-confirmed (direflail, 2026-08-22): "gtk-common-
    themes" ("GTK Common Themes", installed by default on Ubuntu/
    Mint) is type "app" but a *content* snap with no launcher of its
    own, sharing GTK theme assets with other snaps - it has no
    /snap/bin/<name> at all, so picking it produced "Command not
    found" with OK stuck greyed out. snapd's own "apps" field lists a
    snap's actual runnable commands; a non-empty one is the real
    signal that there's a launcher to run, not just the type. Falls
    back to ``name`` when a snap has no ``title`` set. ``version`` is
    needed to pick the newer install when the same app is found in
    both Snap and Flatpak (see _find_best_installed_app below).
    Returns [] if snapd isn't reachable at all (not installed, not
    running) - graceful degradation, not an error surfaced to the
    user, matching _installed_flatpak_apps below.
    """
    try:
        data = _query_snapd("/v2/snaps")
    except OSError:
        return []
    return [
        (snap["name"], snap.get("title") or snap["name"], snap.get("version", ""))
        for snap in data.get("result", [])
        if snap.get("type") == "app" and snap.get("apps")
    ]


def _installed_flatpak_apps() -> list[tuple[str, str, str]]:
    """(name, application-id, version) for every installed Flatpak
    app - task #166 follow-up. ``--columns=name,application,version``
    is a real, scripting-oriented flag (not scraping flatpak's
    default human-readable table output), tab-separated per real
    Flatpak behavior. ``version`` is needed to pick the newer install
    when the same app is found in both Snap and Flatpak (see
    _find_best_installed_app below). Returns [] if flatpak isn't
    installed at all or the command fails for any reason - graceful
    degradation, matching _installed_snap_apps above.
    """
    try:
        result = subprocess.run(
            ["flatpak", "list", "--app", "--columns=name,application,version"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    apps = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            apps.append((parts[0], parts[1], parts[2]))
    return apps


def _parse_desktop_entry(path: Path) -> tuple[str, str, str] | None:
    """(display name, commandline, argument) from one .desktop launcher
    file (freedesktop Desktop Entry spec - the same plain-INI format
    every native package installs alongside its binary), or None if
    it's not a normal menu-visible application or its command isn't
    actually on $PATH. Field codes (%f/%U/etc, placeholders meant for
    a full desktop launch) are stripped rather than preserved - this
    port already appends the screenshot path as its own {0} argument,
    same as the Snap/Flatpak entries below.
    """
    try:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read(path, encoding="utf-8")
        entry = parser["Desktop Entry"]
        if entry.get("Type", "Application") != "Application":
            return None
        if entry.getboolean("NoDisplay", fallback=False) or entry.getboolean("Hidden", fallback=False):
            return None
        name = entry.get("Name")
        exec_line = entry.get("Exec")
        if not name or not exec_line:
            return None
        tokens = shlex.split(_EXEC_FIELD_CODES.sub("", exec_line))
        if not tokens or not shutil.which(tokens[0]):
            return None
        return name, tokens[0], " ".join(tokens[1:] + ["{0}"])
    except (OSError, UnicodeDecodeError, configparser.Error, KeyError, ValueError):
        return None


def _installed_native_apps() -> list[tuple[str, str, str]]:
    """(display name, commandline, argument) triples for native apps
    discovered via .desktop launcher files - the same curated,
    menu-visible app list GNOME Shell's own launcher reads, so it
    surfaces real installed apps without the noise a raw $PATH scan
    would have (every CLI tool, every venv shim, no app/non-app
    signal - shutil.which() only checks one known name at a time, it
    isn't a listing primitive). direflail's own ask: apps installed
    outside Snap/Flatpak should still show up in Find App search.
    """
    apps = []
    seen = set()
    for directory in _DESKTOP_APP_DIRS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.desktop")):
            if path.name in seen:
                continue
            seen.add(path.name)
            entry = _parse_desktop_entry(path)
            if entry is not None:
                apps.append(entry)
    return apps


@dataclass
class InstalledApp:
    """One "Find App" search result - task #166 follow-up. ``name``
    is what the user sees; ``commandline``/``argument`` are exactly
    what would go into an ExternalCommand's own same-named fields if
    this result is picked, already in the correct shape for each
    source (confirmed live, both real Krita installs - Snap and
    Flatpak - during this same task).
    """

    name: str
    source: str  # "snap", "flatpak", or "native"
    commandline: str
    argument: str


def list_installed_apps() -> list[InstalledApp]:
    """Every installed Snap, Flatpak, and native (.desktop) app,
    fetched once. Kept separate from search_installed_apps below so a
    caller fetches this a single time (e.g. when the Find App search
    box first gets used) and filters it in memory as the user types,
    rather than re-querying snapd/flatpak/disk on every keystroke.

    Sorted alphabetically by name across all three sources, not
    grouped by source then alphabetical within each group (direflail's
    own feedback: grouping made the combined list harder to scan) -
    each row's own label still shows its source ("Krita (flatpak)"),
    so nothing about where a result came from is lost.
    """
    apps = []
    for name, title, _version in _installed_snap_apps():
        apps.append(InstalledApp(name=title, source="snap", commandline=f"/snap/bin/{name}", argument="{0}"))
    for name, app_id, _version in _installed_flatpak_apps():
        apps.append(
            InstalledApp(name=name, source="flatpak", commandline="flatpak", argument=f"run {app_id} {{0}}")
        )
    for name, commandline, argument in _installed_native_apps():
        apps.append(InstalledApp(name=name, source="native", commandline=commandline, argument=argument))
    apps.sort(key=lambda app: app.name.lower())
    return apps


def search_installed_apps(query: str, apps: list[InstalledApp]) -> list[InstalledApp]:
    """Case-insensitive substring search over an already-fetched app
    list (see list_installed_apps) - task #166 follow-up ("Find App").
    An empty query returns every app rather than nothing - direflail's
    own revised spec, after live-testing the original "nothing shown
    when no letters" behavior and finding a blank list didn't make it
    obvious what Find App was for; the full list does.
    """
    query = query.strip().lower()
    if not query:
        return list(apps)
    return [
        app for app in apps
        if query in app.name.lower() or query in app.commandline.lower() or query in app.argument.lower()
    ]


def _find_best_installed_app(
    native_candidates: tuple[str, ...], snap_name: str, flatpak_app_id: str, extra_args: str = "",
) -> tuple[str, str, str | None] | None:
    """(commandline, argument, matched_native_candidate) for the best
    available install of one app across native/Snap/Flatpak - the
    shared tie-break behind the one-time LibreOffice/OpenOffice/Krita/
    GIMP destination seeding (see default_external_commands below). A
    native install wins outright if any of ``native_candidates`` is on
    $PATH - simplest case, nothing to compare (direflail's own spec:
    "checking native first (wins outright if present)"). Otherwise
    falls back to whichever of Snap/Flatpak is actually installed,
    picking the newer version when both are present (direflail's own
    call: "if one is discovered in both snap and flatpak, select the
    most current version") - matched by exact snap-name/flatpak-app-id,
    not fuzzy search, reusing core/update_check.py's own version
    comparison rather than a new implementation.

    ``matched_native_candidate`` is whichever entry of
    native_candidates matched (None when Snap/Flatpak won instead) -
    callers offering more than one native candidate (LibreOffice's
    "soffice" vs OpenOffice's "ooffice"/"openoffice.org") use this to
    pick the right display name. An empty snap_name/flatpak_app_id
    (OpenOffice has neither) is skipped rather than matched, so it can
    never accidentally match a real app with an empty identifier.
    Returns None when nothing was found at all.
    """
    suffix = f"{extra_args} {{0}}".strip() if extra_args else "{0}"

    for candidate in native_candidates:
        if shutil.which(candidate):
            return candidate, suffix, candidate

    snap_version = next((v for n, _t, v in _installed_snap_apps() if n == snap_name), None) if snap_name else None
    flatpak_version = (
        next((v for _n, a, v in _installed_flatpak_apps() if a == flatpak_app_id), None) if flatpak_app_id else None
    )

    if snap_version is None and flatpak_version is None:
        return None

    use_flatpak = flatpak_version is not None and (snap_version is None or _is_newer_ignoring_bad_versions(
        flatpak_version, snap_version
    ))
    if use_flatpak:
        return "flatpak", f"run {flatpak_app_id} {suffix}", None
    return f"/snap/bin/{snap_name}", suffix, None


def _is_newer_ignoring_bad_versions(candidate: str, current: str) -> bool:
    try:
        return is_newer_version(candidate, current)
    except ValueError:
        return False


def default_external_commands() -> list[ExternalCommand]:
    """LibreOffice/OpenOffice, Krita, and GIMP as ExternalCommand
    entries, for whichever of them are actually found on this system -
    the one-time seed (see maybe_seed_default_external_commands in
    app.py) that gives a fresh install real Office/Krita/GIMP
    destinations out of the box, the same native/Snap/Flatpak-aware
    detection Find App search itself uses.
    """
    commands = []

    office = _find_best_installed_app(
        ("soffice", "ooffice", "openoffice.org"), "libreoffice", "org.libreoffice.LibreOffice", extra_args="--draw",
    )
    if office is not None:
        commandline, argument, matched_native = office
        name = "OpenOffice" if matched_native in ("ooffice", "openoffice.org") else "LibreOffice"
        commands.append(ExternalCommand(name=name, commandline=commandline, argument=argument))

    krita = _find_best_installed_app(("krita",), "krita", "org.kde.krita")
    if krita is not None:
        commandline, argument, _matched = krita
        commands.append(ExternalCommand(name="Krita", commandline=commandline, argument=argument))

    gimp = _find_best_installed_app(("gimp",), "gimp", "org.gimp.GIMP")
    if gimp is not None:
        commandline, argument, _matched = gimp
        commands.append(ExternalCommand(name="GIMP", commandline=commandline, argument=argument))

    return commands


def maybe_seed_default_external_commands(path: Path = None) -> None:
    """Runs once, on the very first time the app ever starts (see
    app.py's do_startup) - direflail's own explicit call: "the user
    may never open the preferences tab ever - but i want them to have
    libreoffice and krita set as destinations if they have them
    installed", so this can't wait for Preferences to be opened the
    way is_first_run_setup_done's own wizard does. Merges
    default_external_commands()'s findings into the user's persisted
    External Commands list, skipping any name already present (never
    clobbers a same-named command the user already has, including one
    they deleted or renamed after an earlier install), then marks the
    seed done - a second call, even after a fresh Krita install or the
    user deleting the seeded entry, is a no-op.
    """
    if is_default_external_commands_seeded(path):
        return
    existing = get_external_commands(path)
    existing_names = {command.name for command in existing}
    new_commands = [command for command in default_external_commands() if command.name not in existing_names]
    if new_commands:
        set_external_commands(existing + new_commands, path)
    mark_default_external_commands_seeded(path)


def build_command_argv(command: ExternalCommand, file_path: str) -> list[str]:
    """The subprocess argv for running ``command`` against
    ``file_path`` - never a shell command string.

    Faithful-in-spirit port of ExternalCommandDestination.FormatArguments
    (ExternalCommandDestination.cs:288-311): Windows substitutes the
    path into a single argument *string*, then relies on a denylist of
    shell metacharacters to catch injection, because Process.Start's
    Arguments property is itself re-tokenized by a shell-like parser
    even with UseShellExecute=false. subprocess.Popen's list-of-args
    form has no such parser - each argv item goes straight to
    execve(), never reinterpreted - so splitting the template into
    tokens *before* substitution and formatting each token
    independently is injection-proof by construction: the file path
    can never be read back out as shell syntax, no matter what
    characters it contains. Porting that safety *property* here is
    more faithful than porting the exact *mechanism* (a regex
    blocklist) Windows needs to achieve it.
    """
    tokens = shlex.split(command.argument)
    return [command.commandline] + [token.format(file_path) for token in tokens]


def run_external_command(command: ExternalCommand, image: np.ndarray) -> None:
    """Faithful port of ExternalCommandDestination.ExportCapture's core
    (ExternalCommandDestination.cs:67-128): exports the screenshot to
    a temp file, then runs the configured command against it - on a
    background thread when ``run_in_background`` (the default,
    matching ExternalCommandConfigurationImpl's own fallback for a
    misconfigured entry), else blocking the calling thread until the
    process exits (the same UX tradeoff Windows itself has -
    WaitForExit() freezes its own UI thread in that mode too, this
    isn't a regression introduced here).

    Task #166: a Snap-confined target (_is_snap_command) gets its file
    under orcshot_visible_temp_dir instead of the usual
    orcshot_cache_dir - see that function's own docstring for why
    Snap's confinement needs a visible path. Either way, the file is
    deleted once the command has run (success, failure, or timeout -
    subprocess.run's own timeout already blocks until one of those
    happens), so a real, user-visible folder doesn't accumulate temp
    screenshots forever.
    """
    directory = orcshot_visible_temp_dir() if _is_snap_command(command.commandline) else orcshot_cache_dir()
    fd, path_str = tempfile.mkstemp(suffix=".png", prefix="orcshot-external-", dir=str(directory))
    os.close(fd)
    path = Path(path_str)
    save_image_to_file(image, path)
    argv = build_command_argv(command, str(path))

    def invoke() -> None:
        try:
            result = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS)
            if result.returncode != 0:
                _LOG.warning(
                    "External command %r exited %d: %s", command.name, result.returncode, result.stderr.strip()
                )
        except (OSError, subprocess.SubprocessError) as error:
            _LOG.warning("External command %r failed to run: %s", command.name, error)
        finally:
            path.unlink(missing_ok=True)

    if command.run_in_background:
        threading.Thread(target=invoke, name=f"external-command-{command.name}", daemon=True).start()
    else:
        invoke()


def _validate(name: str, commandline: str, argument: str, existing_name: str | None) -> str | None:
    """An error message, or None if the fields are ready to save -
    faithful-in-spirit port of SettingsFormDetail.OkButtonState
    (SettingsFormDetail.cs:134-201): name required and unique,
    command required and resolvable, arguments parseable.
    """
    if not name.strip():
        return _("Name is required.")
    other_names = {c.name for c in get_external_commands() if c.name != existing_name}
    if name in other_names:
        return _("A command with this name already exists.")
    if not commandline.strip():
        return _("Command is required.")
    if shutil.which(commandline) is None and not Path(commandline).is_file():
        # A real command is never a single argv item with a space in
        # it (confirmed live, task #166 follow-up: direflail's own
        # attempt pasting "flatpak run org.kde.krita" whole into this
        # field) - a much more specific, actionable signal than the
        # generic "not found" below covers, worth its own message.
        if " " in commandline.strip():
            return _("This looks like a full command line - put just the program name here, and the rest in Arguments.")
        return _("Command not found - check the path, or that it's on your PATH.")
    try:
        for token in shlex.split(argument):
            token.format("")
    except ValueError as error:
        return _("Invalid arguments: {}").format(error)
    return None


def _find_app_search_available() -> bool:
    """Whether "Find App" has anything to search at all - task #166
    follow-up. A cheap existence check (a socket file, a PATH lookup,
    whether any .desktop directory exists), not an actual query - just
    enough to decide whether to show the search UI or direflail's own
    requested empty-state message. Native .desktop discovery means
    this is true on almost any real desktop system, but a genuinely
    bare/headless one should still get the empty-state message rather
    than a search box that can never return anything.
    """
    return (
        Path(_SNAPD_SOCKET).exists()
        or shutil.which("flatpak") is not None
        or any(directory.is_dir() for directory in _DESKTOP_APP_DIRS)
    )


def _build_command_form(grid: Gtk.Grid, existing: ExternalCommand | None, parent_dialog: Gtk.Dialog) -> dict:
    """The Name/Command/Browse/Arguments/Run-in-background fields -
    shared by both the plain edit-a-command layout and the "Add
    Command" page of the add-flow's mode-switching stack (task #166
    follow-up), so the two never drift into two different forms for
    what's ultimately the same data. Returns the field widgets by name
    rather than returning several values positionally, since callers
    only ever need to read them back by name (revalidate, on save,
    "Find App" pre-filling them).
    """
    name_entry = Gtk.Entry()
    name_entry.set_text(existing.name if existing else "")
    grid.attach(Gtk.Label(label=_("Name:"), xalign=0), 0, 0, 1, 1)
    grid.attach(name_entry, 1, 0, 2, 1)

    command_entry = Gtk.Entry()
    command_entry.set_text(existing.commandline if existing else "")
    grid.attach(Gtk.Label(label=_("Command:"), xalign=0), 0, 1, 1, 1)
    grid.attach(command_entry, 1, 1, 1, 1)
    browse_button = Gtk.Button(label=_("Browse..."))

    def on_browse(_button) -> None:
        chooser = Gtk.FileChooserDialog(
            title=_("Select Command"), transient_for=parent_dialog, action=Gtk.FileChooserAction.OPEN,
        )
        chooser.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        try:
            if chooser.run() == Gtk.ResponseType.OK:
                command_entry.set_text(chooser.get_filename())
        finally:
            chooser.destroy()

    browse_button.connect("clicked", on_browse)
    grid.attach(browse_button, 2, 1, 1, 1)

    argument_entry = Gtk.Entry()
    argument_entry.set_text(existing.argument if existing else _DEFAULT_ARGUMENT_TEMPLATE)
    argument_entry.set_tooltip_text(_("{0} is replaced with the screenshot's exported file path."))
    grid.attach(Gtk.Label(label=_("Arguments:"), xalign=0), 0, 2, 1, 1)
    grid.attach(argument_entry, 1, 2, 2, 1)

    background_check = Gtk.CheckButton(label=_("Run in background"))
    background_check.set_active(existing.run_in_background if existing else True)
    grid.attach(background_check, 1, 3, 2, 1)

    return {
        "name": name_entry, "command": command_entry, "argument": argument_entry, "background": background_check,
    }


def show_command_detail_dialog(parent: Gtk.Window, existing: ExternalCommand | None) -> ExternalCommand | None:
    """Add/edit a single command. Returns the new/edited
    ExternalCommand, or None if cancelled. Faithful-in-spirit port of
    SettingsFormDetail (SettingsFormDetail.cs) - minus the OutputFormat
    dropdown (see this module's own docstring) and the Windows
    "Executables (*.exe, *.bat, *.com)" file filter, which has no
    Linux equivalent (executables carry no reserved extension here) -
    a plain unfiltered file chooser is offered instead.

    Task #166 follow-up: adding a *new* command (``existing is None``)
    gets a "Find App"/"Add Command" mode switch above the form -
    "Find App" searches installed Snap/Flatpak apps and fills the form
    in for the user to review before saving, "Add Command" is this
    same form used directly, for anything Find App won't cover (a
    plain binary, a script). Editing an existing command skips all of
    this and goes straight to the plain form, same as before this
    task - there's nothing to "find" when editing something that
    already exists, direflail's own explicit call on scope.
    """
    dialog = Gtk.Dialog(title=_("External Command"), transient_for=parent, modal=True)
    ok_button = dialog.add_button(_("OK"), Gtk.ResponseType.OK)
    dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    content = dialog.get_content_area()
    content.set_border_width(12)
    content.set_spacing(6)

    add_page = Gtk.Grid(row_spacing=6, column_spacing=6)
    fields = _build_command_form(add_page, existing, dialog)
    name_entry, command_entry, argument_entry, background_check = (
        fields["name"], fields["command"], fields["argument"], fields["background"]
    )

    # Both stay None for the Edit flow (existing is not None) - there's
    # no Find App page there at all. revalidate/on_response below check
    # for None rather than assuming these always exist.
    mode_combo: Gtk.ComboBoxText | None = None
    results_tree: Gtk.TreeView | None = None

    if existing is None:
        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mode_combo = Gtk.ComboBoxText()
        mode_combo.append("find", _("Find App"))
        mode_combo.append("add", _("Add Command"))
        mode_row.pack_start(mode_combo, False, False, 0)
        help_icon = Gtk.Image.new_from_icon_name("dialog-question-symbolic", Gtk.IconSize.BUTTON)
        help_icon.set_tooltip_text(
            _(
                "Find App searches your installed apps - Snap, Flatpak, and natively installed - "
                "and fills in the fields below for you. For anything else - a plain program or a "
                "script - use Add Command."
            )
        )
        mode_row.pack_start(help_icon, False, False, 0)
        content.pack_start(mode_row, False, False, 0)

        stack = Gtk.Stack()
        content.pack_start(stack, True, True, 0)

        find_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        if _find_app_search_available():
            search_entry = Gtk.SearchEntry()
            find_page.pack_start(search_entry, False, False, 0)
            results_store = Gtk.ListStore(str, str, str, str)  # display, name, commandline, argument
            results_tree = Gtk.TreeView(model=results_store, headers_visible=False)
            results_tree.append_column(Gtk.TreeViewColumn(_("App"), Gtk.CellRendererText(), text=0))
            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.set_min_content_height(160)
            scroller.add(results_tree)
            find_page.pack_start(scroller, True, True, 0)

            # Fetched once, immediately, then reused for every keystroke
            # from here on - snapd/flatpak/disk are only ever queried
            # once per dialog (direflail's own spec: these lists
            # "aren't saved permanently anywhere", pulled fresh only
            # "when they go to install a new package" - once per
            # add-flow, not once per letter typed).
            cached_apps = list_installed_apps()

            def refresh_results(query: str) -> None:
                results_store.clear()
                for app in search_installed_apps(query, cached_apps):
                    results_store.append([f"{app.name} ({app.source})", app.name, app.commandline, app.argument])

            search_entry.connect("search-changed", lambda entry: refresh_results(entry.get_text()))
            # Populated up front rather than left blank - direflail,
            # after live-testing: a blank list didn't make it obvious
            # what Find App was for, the full browsable list does.
            refresh_results("")

            def fill_form_from_result(row) -> None:
                name_entry.set_text(row[1])
                command_entry.set_text(row[2])
                argument_entry.set_text(row[3])
                # Switches to "Add Command" so the pre-filled fields
                # get the same review-before-saving step as typing
                # them by hand - picking a search result isn't a
                # separate, more-trusted save path (direflail's own
                # explicit call: this is a faster way to *fill* the
                # form, not to bypass reviewing it).
                mode_combo.set_active_id("add")

            results_tree.connect(
                "row-activated", lambda _tree, path, _column: fill_form_from_result(results_store[path])
            )
        else:
            find_page.pack_start(
                Gtk.Label(
                    label=_(
                        "No installed apps could be found to search.\n"
                        "Use Add Command instead."
                    ),
                    justify=Gtk.Justification.CENTER,
                ),
                True, True, 0,
            )
        stack.add_named(find_page, "find")
        stack.add_named(add_page, "add")

        mode_combo.connect("changed", lambda combo: stack.set_visible_child_name(combo.get_active_id()))
        mode_combo.set_active_id("find")
    else:
        content.pack_start(add_page, False, False, 0)

    error_label = Gtk.Label(xalign=0)
    content.pack_start(error_label, False, False, 0)

    def revalidate(*_args) -> None:
        # On the Find App page there's nothing in the Add Command
        # form yet to validate - showing _validate's "Name is
        # required" there read as a stuck error message about a form
        # the user hasn't touched (direflail, live-testing). OK's
        # sensitivity here tracks whether a result is selected instead
        # (see on_response below for what OK actually does with it).
        if mode_combo is not None and mode_combo.get_active_id() == "find":
            has_selection = results_tree is not None and results_tree.get_selection().get_selected()[1] is not None
            error_label.set_text("" if has_selection else _("Search the list of installed applications."))
            ok_button.set_sensitive(has_selection)
            return
        error = _validate(
            name_entry.get_text(), command_entry.get_text(), argument_entry.get_text(),
            existing.name if existing else None,
        )
        error_label.set_text(error or "")
        ok_button.set_sensitive(error is None)

    name_entry.connect("changed", revalidate)
    command_entry.connect("changed", revalidate)
    argument_entry.connect("changed", revalidate)
    if mode_combo is not None:
        mode_combo.connect("changed", lambda *_args: revalidate())
    if results_tree is not None:
        results_tree.get_selection().connect("changed", lambda *_args: revalidate())
    revalidate()

    def on_response(_dialog, response_id) -> None:
        # Single-click a Find App result then OK does the same thing
        # double-clicking it does (fill the form, switch to Add
        # Command for review) rather than closing the dialog outright
        # - direflail's own explicit call: picking a result is a
        # faster way to *fill* the form, never a bypass of reviewing
        # it. stop_emission_by_name keeps dialog.run()'s own internal
        # handler from ever seeing this response, so the modal loop
        # below simply doesn't exit for it.
        if response_id != Gtk.ResponseType.OK or mode_combo is None or mode_combo.get_active_id() != "find":
            return
        if results_tree is not None:
            model, tree_iter = results_tree.get_selection().get_selected()
            if tree_iter is not None:
                fill_form_from_result(model[tree_iter])
        dialog.stop_emission_by_name("response")

    dialog.connect("response", on_response)

    dialog.show_all()
    try:
        if dialog.run() != Gtk.ResponseType.OK:
            return None
        return ExternalCommand(
            name=name_entry.get_text(), commandline=command_entry.get_text(),
            argument=argument_entry.get_text(), run_in_background=background_check.get_active(),
        )
    finally:
        dialog.destroy()
