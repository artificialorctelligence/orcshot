"""The one-time first-run prompt: offers to enable autostart-on-login,
configure the four capture hotkeys (asking per-binding whether to
overwrite anything already using that key combo), and - on a GNOME
Wayland session specifically - enable the two bundled GNOME Shell
extensions this project ships: window-calls ("Capture Window" mode)
and orcshot-clipboard (reliable "Copy to Clipboard") - see
gnome_extension_setup.py and REQUIREMENTS.md's Wayland window-picker
and "Clipboard under Wayland" sections. See hotkey_setup.py's module
docstring for how real conflicts on the dev machine (every one of the
four defaults collided with something) motivated that question
existing at all - this dialog is the only place in this codebase where
the user actually answers it.

Hotkey auto-configuration runs on both Cinnamon and GNOME - the
desktop is detected via hotkey_setup.detect_profile() before touching
any of it, never assumed. Confirmed live that skipping this check is
fatal, not just wrong: reaching GioSettingsBackend for a keybinding
schema that isn't installed on the running desktop crashed the entire
app with an uncatchable GLib abort before this dialog even had a
chance to show. On any other desktop (XFCE, KDE, MATE, ...) -
including one with a third-party screenshot tool like Flameshot
already installed, since detecting and resetting arbitrary other
apps' bindings is out of scope (see hotkey_setup.py's module
docstring) - detect_profile() returns None and the dialog falls back
to the same manual, cut-and-pasteable CLI-flag cheat sheet either way.
Autostart is offered regardless (a plain XDG autostart .desktop entry,
tied to neither desktop's keybinding schema); when hotkeys aren't
available, the dialog says so and points to manual configuration via
the same CLI flags instead of silently doing nothing when "Enable" is
clicked.

Tracked via settings.py's first_run_setup_done flag so it only ever
asks once, matching REQUIREMENTS.md's "automatically on first run with
a one-time user confirmation". Whichever choices the user makes (or
even hitting "Not Now"), the flag is set either way - there's no
separate "ask me again later" path, since "one-time" means one-time.

This is the only place in this codebase meant to ever invoke
hotkey_setup.GioSettingsBackend, autostart.install_autostart_entry, or
gnome_extension_setup.enable_extension against the real live system -
and only because a human clicked a real confirmation button in their
own running app, not because anything here does so as a side effect of
being built or tested. The default ``settings_backend``/``executable``
are injectable specifically so the decision *logic* this dialog drives
(which lives in hotkey_setup.py - check_all_conflicts,
resolve_hotkey_choices, configure_all_hotkeys) can be fully unit
tested there without a live GTK dialog or a real desktop in the loop;
this file is just the thin GTK glue wiring user clicks to that logic.

Both extension checkboxes only appear at all on a session where they
could plausibly work (Wayland + gnome_extension_setup.gnome_shell_present())
- checked, not assumed, same empirical-first precedent as the hotkeys
section. Enabling either here only flips the gsettings flag; it does
NOT take effect in the current session - confirmed live that GNOME
Shell caches an extension's JS module and needs a full logout/login to
pick up a freshly-enabled one, not just a Shell restart or a
disable/enable toggle - hence the explicit note in the dialog rather
than implying it works immediately.

Not unit tested for the same reason editor_window.py/region_select.py
aren't: GTK dialog glue with no meaningful headless test. Verified by
running it and clicking through both the clean-conflict-free path and
the "overwrite an existing binding" path.
"""

from __future__ import annotations

import os
import shutil
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from orcshot.autostart import install_autostart_entry
from orcshot.gnome_extension_setup import (
    CLIPBOARD_EXTENSION_UUID,
    WINDOW_CALLS_EXTENSION_UUID,
    enable_extension,
    gnome_shell_present,
)
from orcshot.hotkey_setup import (
    DEFAULT_HOTKEYS,
    GioSettingsBackend,
    check_all_conflicts,
    clear_conflict,
    configure_all_hotkeys,
    detect_profile,
    resolve_hotkey_choices,
)
from orcshot.settings import is_first_run_setup_done, mark_first_run_setup_done


def _default_executable(which=shutil.which) -> str:
    """The command written into hotkey bindings and the autostart
    entry. Prefers the installed console-script binary
    (``orcshot``, on PATH once packaged - see pyproject.toml's
    ``[project.scripts]``) so a real .deb install doesn't keep wiring
    hotkeys/autostart to a dev-only ``python3 -m`` invocation; falls
    back to that form for a dev checkout with no such install.
    ``which`` is injectable for tests, matching this project's
    established convention for real-system-touching lookups.
    """
    installed = which("orcshot")
    if installed is not None:
        return installed
    return f"{sys.executable} -m orcshot.app"


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
    # Checked first and unconditionally: reaching GioSettingsBackend (or
    # check_all_conflicts, which calls it) on a desktop without a
    # matching keybinding schema is a hard, uncatchable process abort,
    # not a Python exception - confirmed live crashing the whole app
    # before this dialog even had a chance to show (see
    # hotkey_setup.detect_profile's docstring). Autostart itself doesn't
    # depend on either desktop's schema at all (a plain XDG autostart
    # .desktop file), so it's still offered either way.
    profile = detect_profile()
    hotkeys_available = profile is not None
    conflicts = check_all_conflicts(settings_backend, profile=profile) if hotkeys_available else {}

    dialog = Gtk.Dialog(title="Orcshot Setup", transient_for=parent)
    dialog.add_buttons(
        "Not Now", Gtk.ResponseType.CANCEL,
        "Enable", Gtk.ResponseType.OK,
    )
    dialog.set_default_response(Gtk.ResponseType.OK)

    content = dialog.get_content_area()
    content.set_border_width(12)
    content.set_spacing(8)

    intro = "Set up Orcshot to start automatically at login"
    intro += ", and enable its capture keyboard shortcuts?" if hotkeys_available else "?"
    content.pack_start(Gtk.Label(label=intro, wrap=True, xalign=0), False, False, 0)

    autostart_check = Gtk.CheckButton(label="Start automatically at login")
    autostart_check.set_active(True)
    content.pack_start(autostart_check, False, False, 0)

    content.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

    binding_checks = {}
    if hotkeys_available:
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
    else:
        # Neither Cinnamon nor GNOME detected (e.g. XFCE/KDE/MATE), or a
        # desktop where the user has their own screenshot tool already
        # bound to these keys - detecting/resetting arbitrary third-party
        # bindings is out of scope (see hotkey_setup.py's module
        # docstring). Honest about the gap rather than silently doing
        # nothing when "Enable" is clicked.
        manual_lines = "\n".join(f"  {hb.name}: {executable} {hb.cli_flag}" for hb in DEFAULT_HOTKEYS)
        content.pack_start(Gtk.Label(
            label="Automatic keyboard shortcut setup isn't available on this desktop. "
                  "You can bind shortcuts to these manually instead:\n"
                  + manual_lines,
            wrap=True, xalign=0,
        ), False, False, 0)

    # Both offered only on a session where they could plausibly work at
    # all - checked, not assumed (see
    # gnome_extension_setup.gnome_shell_present's docstring). "Capture
    # Window" has no other way to work correctly under Wayland (see
    # REQUIREMENTS.md's Wayland window-picker section); reliable
    # clipboard support under Wayland has no other way to work either
    # (see REQUIREMENTS.md's "Clipboard under Wayland" section) -
    # without this, captures still copy via the invisible-window
    # fallback in wayland_clipboard.py, just with its known window-list
    # reflow side effect.
    is_gnome_wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland" and gnome_shell_present()
    window_calls_check = None
    clipboard_check = None
    if is_gnome_wayland:
        content.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
        window_calls_check = Gtk.CheckButton(
            label="Enable window capture support (\"Capture Window\" mode)"
        )
        window_calls_check.set_active(True)
        content.pack_start(window_calls_check, False, False, 0)

        clipboard_check = Gtk.CheckButton(
            label="Enable reliable \"Copy to Clipboard\" support"
        )
        clipboard_check.set_active(True)
        content.pack_start(clipboard_check, False, False, 0)

        content.pack_start(Gtk.Label(
            label="Both require logging out and back in to take effect.",
            wrap=True, xalign=0,
        ), False, False, 0)

    dialog.show_all()
    response = dialog.run()

    if response == Gtk.ResponseType.OK:
        if autostart_check.get_active():
            install_autostart_entry(executable)

        if hotkeys_available:
            enabled_names = {name for name, check in binding_checks.items() if check.get_active()}
            skip, to_clear = resolve_hotkey_choices(enabled_names, conflicts)
            for conflict in to_clear:
                clear_conflict(settings_backend, conflict)
            configure_all_hotkeys(settings_backend, executable, skip=skip, profile=profile)

        if window_calls_check is not None and window_calls_check.get_active():
            enable_extension(settings_backend, WINDOW_CALLS_EXTENSION_UUID)

        if clipboard_check is not None and clipboard_check.get_active():
            enable_extension(settings_backend, CLIPBOARD_EXTENSION_UUID)

    mark_first_run_setup_done()
    dialog.destroy()
