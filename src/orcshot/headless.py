"""Orcshot's scripting face: capture to a path and exit (BACKLOG #225).

`orcshot --capture-to PATH [--window TITLE]` writes a PNG, prints the
path, exits 0. `orcshot --can-capture` answers silently with its exit
status. Anything else on the command line belongs to the GUI app and is
left alone.

Why this bypasses GApplication entirely, rather than adding two more
flags beside the existing five: GLib's single-instance forwarding hands a
CLI invocation to whichever process already owns org.orcshot.Orcshot. On
a machine with the tray app running, `orcshot --capture-to /tmp/x.png`
would be executed *there* - with that process's environment and working
directory - while the calling process got exit 0 back immediately with no
way to learn what happened or whether the file exists. For a GUI action
that is fine. For a script it is unusable. So main() calls
parse_headless_request before OrcshotApplication is ever constructed,
following the quit-marker gate's own precedent.

That also means GLib's option parser is unavailable here - add_main_option
lives on the application object this path exists to avoid - hence plain
argparse, deliberately tolerant of every flag it does not own.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Optional, Sequence

EXIT_OK = 0
# One failure code, not a taxonomy: Orclab asked for "exits non-zero with
# one line on stderr saying why", and nothing in the request branches on
# which kind of failure it was - only on whether it failed. Split this
# into distinct codes if a caller ever needs to react differently to
# "minimised" than to "no such window".
EXIT_FAILED = 1

_HEADLESS_FLAGS = ("--capture-to", "--can-capture")


@dataclass(frozen=True)
class HeadlessRequest:
    capture_to: Optional[str]
    window: Optional[str]
    can_capture: bool


def parse_headless_request(argv: Sequence[str]) -> Optional[HeadlessRequest]:
    """The headless request this command line asks for, or None if it
    asks for the ordinary GUI app.

    The cheap substring check first, mirroring main()'s own
    _CAPTURE_CLI_FLAGS scan, so a plain tray launch never even builds a
    parser. add_help=False and parse_known_args together keep this from
    claiming --help or objecting to GLib's own flags, both of which still
    have to reach the application when this declines.
    """
    arguments = list(argv[1:])
    if not any(flag in argument for flag in _HEADLESS_FLAGS for argument in arguments):
        return None

    parser = argparse.ArgumentParser(prog="orcshot", add_help=False)
    parser.add_argument("--capture-to")
    parser.add_argument("--window")
    parser.add_argument("--can-capture", action="store_true")
    known, _unknown = parser.parse_known_args(arguments)
    if known.capture_to is None and not known.can_capture:
        return None
    return HeadlessRequest(capture_to=known.capture_to, window=known.window, can_capture=known.can_capture)


def run(request: HeadlessRequest) -> int:
    """Perform ``request`` and return the process's exit status."""
    if request.window is not None and request.capture_to is None:
        return _fail("--window needs --capture-to: there is nowhere to put the capture")

    if request.can_capture:
        # Silent on purpose: a backend chooser asks this constantly and
        # wants an exit status, not output.
        return EXIT_OK if _can_capture() else EXIT_FAILED

    try:
        _capture_and_write(request.capture_to, request.window)
    except Exception as error:  # noqa: BLE001 - every failure is one stderr line, never a traceback
        return _fail(error)

    # Only once the file really exists: a caller doing
    # PATH=$(orcshot --capture-to ...) must never be handed a path to
    # something that was not written.
    print(request.capture_to)
    return EXIT_OK


def _fail(reason) -> int:
    print(f"orcshot: {reason}", file=sys.stderr)
    return EXIT_FAILED


def _is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE") == "wayland"


def _can_capture() -> bool:
    """Whether a capture could be taken here, right now.

    X11 needs only a display, the same reasoning backend_select's
    window_picker_supported already uses. GNOME needs the Shell
    extension, because the desktop portal categorically cannot serve a
    process with no focused window of its own - it answers "Only the
    focused app is allowed to show a system access dialog", proven by
    this project's own SpikePortalGnome (BACKLOG, 2026-09).
    """
    if not _is_wayland():
        from orcshot.capture.x11 import X11CaptureBackend

        try:
            X11CaptureBackend()
        except Exception:  # noqa: BLE001 - no display, in whatever form the backend reports it
            return False
        return True

    from orcshot.capture.gnome_headless import CAPABILITY
    from orcshot.capture.shell_bridge import HeadlessSessionUnavailable, HeadlessShellSession

    session = HeadlessShellSession()
    try:
        bridge = session.open(timeout_ms=2000)
    except HeadlessSessionUnavailable:
        return False
    finally:
        session.close()
    return bridge.has(CAPABILITY)


def _capture_and_write(capture_to: str, window: Optional[str]) -> None:
    if _is_wayland():
        from orcshot.capture.gnome_headless import capture_png_to

        capture_png_to(capture_to, window)
        return
    from orcshot.capture.headless_x11 import capture_to_file

    capture_to_file(capture_to, window)
