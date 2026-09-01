"""Autostart-on-login, via a systemd --user service (task #141) -
replaces the previous plain XDG autostart .desktop entry. That
mechanism only ever launched once at login; if orcshot.app crashed
later, nothing relaunched it, and since the Wayland tray panel button
now lives in the Shell extension independently of the Python process
(task #137 follow-up), a dead process left a seemingly-functional but
non-responsive tray icon - hovering/opening the menu still worked, but
clicking anything did nothing, with no error shown anywhere. systemd's
own Restart=on-failure (debian/orcshot.service) handles automatic
respawn as a native OS feature, with zero custom watchdog code needed
here.

Unlike the .desktop-writing functions this replaces, debian/
orcshot.service is a static file shipped by the package itself
(installed to /usr/lib/systemd/user/ via debhelper's
dh_installsystemduser, discovered automatically from its
debian/<package>.service naming - no debian/orcshot.install entry
needed). There's no exec_command to inject per-install the way the old
.desktop entry took one; the unit's own ExecStart is fixed at
packaging time. This module's job is now only to flip the *enabled*
state of that already-installed unit.

Real, live `systemctl --user` calls - no safe way to test without a
real systemd user manager and a real installed unit, same category as
gnome_extension_setup.enable_extension_live and hotkey_setup.py's
GioSettingsBackend (see either module's own docstring). The same
standing rule applies: nothing in this codebase calls these
automatically. Only a real user click (ui/first_run_setup.py, or the
Preferences "Launch Orcshot on startup" checkbox) is meant to trigger
a real enable/disable.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SERVICE_NAME = "orcshot.service"

_LEGACY_DESKTOP_ENTRY_FILENAME = "orcshot.desktop"


def is_autostart_enabled() -> bool:
    """Whether the systemd user service is currently enabled. Treats
    any failure (systemctl missing, unit not installed, no systemd
    user manager running) as "not enabled" rather than raising -
    matches this module's own previous file-based "existence alone is
    the signal" convention, now expressed as "is-enabled alone is the
    signal" instead. Called unconditionally whenever the Preferences
    dialog opens (to set the checkbox's initial state), so it must
    never raise.
    """
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", SERVICE_NAME],
            capture_output=True, text=True,
        )
    except (FileNotFoundError, OSError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "enabled"


def _run_systemctl_user(*args: str) -> None:
    """Shared by enable_autostart/disable_autostart: runs `systemctl
    --user <args> SERVICE_NAME`, converting "systemctl doesn't exist at
    all" (FileNotFoundError - confirmed live inside a real Flatpak
    build of org.gnome.Platform//50, which ships no systemd binaries)
    into the same subprocess.CalledProcessError shape a real systemctl
    failure already raises. Root-caused here once rather than widening
    both call sites' `except subprocess.CalledProcessError` clauses
    independently - matches is_autostart_enabled's own "systemctl
    missing" handling above, just expressed as "raise the one thing
    callers already catch" instead of "return a safe default", since
    an enable/disable call has real work to fail at and its callers
    (ui/first_run_setup.py, ui/editor_window.py's Preferences checkbox)
    already print/report that failure - swallowing it silently here
    the way is_autostart_enabled does would hide it entirely.
    """
    try:
        subprocess.run(["systemctl", "--user", *args, SERVICE_NAME], check=True)
    except FileNotFoundError as e:
        raise subprocess.CalledProcessError(returncode=127, cmd=e.filename or "systemctl") from e


def enable_autostart() -> None:
    """Enables the already-installed orcshot.service unit so it starts
    at the next login - `--now` also starts it immediately, matching
    real Windows' own "Launch on startup" checkbox not requiring a
    restart to take effect. Safe even if an instance is already
    running: GApplication's own single-instance handling just forwards
    the new invocation to the existing process and exits (see
    OrcshotApplication.do_activate's own "already running" handling,
    task #151 follow-up) rather than starting a genuine second copy.
    """
    _run_systemctl_user("enable", "--now")


def remove_legacy_autostart_entry(config_home: Path = None) -> None:
    """Task #180: removes the pre-task-#141 XDG autostart .desktop
    entry (``$XDG_CONFIG_HOME/autostart/orcshot.desktop``) if one is
    still present, left over from before this module was rewritten to
    manage a systemd unit instead of writing that file directly. That
    migration only ever changed what *new* installs do; an existing
    install that had autostart enabled before it kept the old file, and
    GNOME session's own XDG-autostart mechanism launches it
    independently of - and racing against - orcshot.service at every
    boot, reproducing task #170's exact orphaned-process symptom from a
    third launch path #170's own fix never touched. Found live on a
    real VM reboot, see BACKLOG.md's resolved #180 entry.

    Naturally idempotent (a no-op if the file, or even the whole
    directory, was never there) so this is safe to call unconditionally
    on every app startup - unlike ``maybe_seed_default_external_commands``,
    there's no "already ran once" state to track separately.
    """
    if config_home is None:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    (config_home / "autostart" / _LEGACY_DESKTOP_ENTRY_FILENAME).unlink(missing_ok=True)


def disable_autostart() -> None:
    """Disables the unit so it won't start at the *next* login - does
    NOT stop whatever's running right now. This checkbox is typically
    toggled from within the app's own currently-open Preferences
    dialog; killing that process out from under the user while they're
    still looking at it would be a real regression from the old
    .desktop-based mechanism's own behavior (which never affected the
    current session at all, only future logins).
    """
    _run_systemctl_user("disable")
