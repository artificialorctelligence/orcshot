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

import subprocess

SERVICE_NAME = "orcshot.service"


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
    subprocess.run(["systemctl", "--user", "enable", "--now", SERVICE_NAME], check=True)


def disable_autostart() -> None:
    """Disables the unit so it won't start at the *next* login - does
    NOT stop whatever's running right now. This checkbox is typically
    toggled from within the app's own currently-open Preferences
    dialog; killing that process out from under the user while they're
    still looking at it would be a real regression from the old
    .desktop-based mechanism's own behavior (which never affected the
    current session at all, only future logins).
    """
    subprocess.run(["systemctl", "--user", "disable", SERVICE_NAME], check=True)
