"""The one-time first-run prompt: offers to enable autostart-on-login
and configure the four capture hotkeys, asking per-binding whether to
overwrite anything already using that key combo. See
hotkey_setup.py's module docstring for how real conflicts on the dev
machine (every one of the four defaults collided with something)
motivated that question existing at all - this dialog is the only
place in this codebase where the user actually answers it.

Tracked via settings.py's first_run_setup_done flag so it only ever
asks once, matching REQUIREMENTS.md's "automatically on first run with
a one-time user confirmation". Whichever choices the user makes (or
even hitting "Not Now"), the flag is set either way - there's no
separate "ask me again later" path, since "one-time" means one-time.

This is the only place in this codebase meant to ever invoke
hotkey_setup.GioSettingsBackend or autostart.install_autostart_entry
against the real live system - and only because a human clicked a real
confirmation button in their own running app, not because anything
here does so as a side effect of being built or tested. The default
``settings_backend``/``executable`` are injectable specifically so the
decision *logic* this dialog drives (which lives in hotkey_setup.py -
check_all_conflicts, resolve_hotkey_choices, configure_all_hotkeys) can
be fully unit tested there without a live GTK dialog or a real desktop
in the loop; this file is just the thin GTK glue wiring user clicks to
that logic.

Not unit tested for the same reason editor_window.py/region_select.py
aren't: GTK dialog glue with no meaningful headless test. Verified by
running it and clicking through both the clean-conflict-free path and
the "overwrite an existing binding" path.
"""

from __future__ import annotations

import shutil
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from greenshot_linux.autostart import install_autostart_entry
from greenshot_linux.hotkey_setup import (
    DEFAULT_HOTKEYS,
    GioSettingsBackend,
    check_all_conflicts,
    clear_conflict,
    configure_all_hotkeys,
    resolve_hotkey_choices,
)
from greenshot_linux.settings import is_first_run_setup_done, mark_first_run_setup_done


def _default_executable(which=shutil.which) -> str:
    """The command written into hotkey bindings and the autostart
    entry. Prefers the installed console-script binary
    (``greenshot-linux``, on PATH once packaged - see pyproject.toml's
    ``[project.scripts]``) so a real .deb install doesn't keep wiring
    hotkeys/autostart to a dev-only ``python3 -m`` invocation; falls
    back to that form for a dev checkout with no such install.
    ``which`` is injectable for tests, matching this project's
    established convention for real-system-touching lookups.
    """
    installed = which("greenshot-linux")
    if installed is not None:
        return installed
    return f"{sys.executable} -m greenshot_linux.app"


def maybe_run_first_run_setup(parent: Gtk.Window = None, executable: str = None, settings_backend=None) -> None:
    """Shows the first-run dialog if it hasn't run before; does
    nothing otherwise (checked via settings.is_first_run_setup_done).
    """
    if is_first_run_setup_done():
        return
    if executable is None:
        executable = _default_executable()
    if settings_backend is None:
        settings_backend = GioSettingsBackend()

    _run_dialog(parent, executable, settings_backend)


def _run_dialog(parent, executable: str, settings_backend) -> None:
    conflicts = check_all_conflicts(settings_backend)

    dialog = Gtk.Dialog(title="Greenshot Linux Setup", transient_for=parent)
    dialog.add_buttons(
        "Not Now", Gtk.ResponseType.CANCEL,
        "Enable", Gtk.ResponseType.OK,
    )
    dialog.set_default_response(Gtk.ResponseType.OK)

    content = dialog.get_content_area()
    content.set_border_width(12)
    content.set_spacing(8)

    content.pack_start(Gtk.Label(
        label="Set up Greenshot Linux to start automatically at login, and enable "
              "its capture keyboard shortcuts?",
        wrap=True, xalign=0,
    ), False, False, 0)

    autostart_check = Gtk.CheckButton(label="Start automatically at login")
    autostart_check.set_active(True)
    content.pack_start(autostart_check, False, False, 0)

    content.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

    binding_checks = {}
    for hb in DEFAULT_HOTKEYS:
        hb_conflicts = conflicts.get(hb.name, [])
        if hb_conflicts:
            sources = ", ".join(c.source for c in hb_conflicts)
            label = f"{hb.name} ({hb.binding}) — overwrite {sources}?"
            default_active = False
        else:
            label = f"{hb.name} ({hb.binding})"
            default_active = True
        check = Gtk.CheckButton(label=label)
        check.set_active(default_active)
        content.pack_start(check, False, False, 0)
        binding_checks[hb.name] = check

    dialog.show_all()
    response = dialog.run()

    if response == Gtk.ResponseType.OK:
        if autostart_check.get_active():
            install_autostart_entry(executable)

        enabled_names = {name for name, check in binding_checks.items() if check.get_active()}
        skip, to_clear = resolve_hotkey_choices(enabled_names, conflicts)
        for conflict in to_clear:
            clear_conflict(settings_backend, conflict)
        configure_all_hotkeys(settings_backend, executable, skip=skip)

    mark_first_run_setup_done()
    dialog.destroy()
