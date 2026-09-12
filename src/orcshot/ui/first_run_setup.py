"""The one-time first-run prompt: offers to enable autostart-on-login,
configure the four capture hotkeys (asking per-binding whether to
overwrite anything already using that key combo), and - on any real
GNOME Shell session - enable Orcshot's GNOME Shell extension
(orcshot@orcshot.org: tray icon/menu on any GNOME session, plus
Shell-native capture, clipboard and the window picker on Wayland - one
extension since the 2026-09-11 spec, see gnome_extension_setup.py).
Where the extension's *files* come from is per channel and lives in
ui/extension_install.py: the .deb installed them system-wide, Flatpak
asks GNOME to fetch them from extensions.gnome.org, Snap sends the user
there, and Flatpak on Cinnamon sends the user to Cinnamon Spices for
the applet. Nothing here writes into the user's home on any channel.
See hotkey_setup.py's module
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
hotkey_setup.GioSettingsBackend, autostart.enable_autostart, or
gnome_extension_setup.enable_extension against the real live system -
and only because a human clicked a real confirmation button in their
own running app, not because anything here does so as a side effect of
being built or tested. The default ``settings_backend``/``executable``
are injectable specifically so the decision *logic* this dialog drives
(which lives in hotkey_setup.py - check_all_conflicts,
resolve_hotkey_choices, configure_all_hotkeys) can be fully unit
tested there without a live GTK dialog or a real desktop in the loop;
this file is just the thin GTK glue wiring user clicks to that logic.

The extension is not offered as a checkbox at all - it is only ever
enabled on a session where it could plausibly work (any session with
gnome_extension_setup.gnome_shell_present()) - checked, not assumed,
same empirical-first precedent as the hotkeys section. Enabling it here
flips the gsettings flag; on the .deb enable_extension_live also asks
the running Shell to activate it now. A Shell that has already loaded
an older copy this session keeps it until logout/login (confirmed live)
- app.py's health check says so when Hello reports the stale version.

Not unit tested for the same reason editor_window.py/region_select.py
aren't: GTK dialog glue with no meaningful headless test. Verified by
running it and clicking through both the clean-conflict-free path and
the "overwrite an existing binding" path.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from orcshot.autostart import enable_autostart
from orcshot.channel_detect import detect_channel
from orcshot.gnome_extension_setup import (
    enable_extension,
    enable_extension_live,
    extensions_to_enable,
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
from orcshot.i18n import _
from orcshot.settings import is_first_run_setup_done, mark_first_run_setup_done
from orcshot.ui.extension_install import plan_install, show_install_dialog


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


def _finish_gnome_setup(settings_backend, desktop, parent=None) -> None:
    """Enables the extension in gsettings (works under every sandbox,
    proven), asks the running Shell to activate it on the .deb (the only
    channel whose files are already on disk and whose sandbox-free
    process may make that call - see enable_extension_live's docstring),
    and on the channels that cannot install the files themselves shows
    the redirect dialog for this channel/desktop."""
    channel = detect_channel()
    for uuid in extensions_to_enable(True):
        enable_extension(settings_backend, uuid)
        if channel == "deb":
            try:
                enable_extension_live(uuid)
            except GLib.Error as e:
                print(f"[orcshot] enable_extension_live({uuid!r}) failed: {e}", file=sys.stderr)
    plan = plan_install(channel, desktop)
    if plan is not None:
        show_install_dialog(plan, parent)


def _finish_cinnamon_setup(parent=None) -> None:
    """Cinnamon's tray is an applet; the .deb installed it, Flatpak sends
    the user to Cinnamon Spices, Snap does nothing (decided 2026-09-11)."""
    plan = plan_install(detect_channel(), "cinnamon")
    if plan is not None:
        show_install_dialog(plan, parent)


def maybe_run_first_run_setup(parent: Gtk.Window = None, executable: str = None, settings_backend=None) -> None:
    """Shows the first-run dialog if it hasn't run before; does
    nothing otherwise (checked via settings.is_first_run_setup_done).
    """
    if is_first_run_setup_done():
        return
    run_setup_dialog(parent, executable, settings_backend)


def run_setup_dialog(parent: Gtk.Window = None, executable: str = None, settings_backend=None) -> None:
    """Same dialog as the first-run prompt, but callable anytime (task
    #104's "Help > Set Up Hotkeys & Autostart..." menu item) - not
    gated by is_first_run_setup_done. Re-running this after a rename
    like task #105's Greenshot->Orcshot rebrand is the intended fix for
    hotkeys that stopped working because they were bound to a command
    that no longer exists: find_conflicts matches existing custom
    keybindings by binding key, not name, so a stale "Greenshot Linux -
    Region Capture" entry still occupying Print shows up as a conflict
    to overwrite here, the same as any other pre-existing binding
    would.
    """
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

    dialog = Gtk.Dialog(title=_("Orcshot Setup"), transient_for=parent)
    dialog.add_buttons(
        _("Not Now"), Gtk.ResponseType.CANCEL,
        _("Enable"), Gtk.ResponseType.OK,
    )
    dialog.set_default_response(Gtk.ResponseType.OK)

    content = dialog.get_content_area()
    content.set_border_width(12)
    content.set_spacing(8)

    # Ruling (final-review Critical fix, 2026-08-31): autostart cannot
    # work at all on the Flatpak channel - there's no systemd --user
    # access from inside the sandbox (confirmed live: enable_autostart's
    # own subprocess.run raises FileNotFoundError, "systemctl" doesn't
    # exist in org.gnome.Platform//50), and orcshot.service is a
    # debian/-shipped unit this channel doesn't even install. Offering a
    # default-checked box for a feature that provably cannot work is
    # exactly the "if it can't work correctly, don't ship it looking
    # like it works" bar this project already holds itself to elsewhere
    # (BACKLOG #185's own framing) - so the checkbox is hidden outright
    # on this channel rather than left to silently no-op. Same ruling
    # applied to the Preferences "Launch Orcshot on startup" checkbox
    # (ui/editor_window.py), which has the identical bug. Snap joined
    # Flatpak here on 2026-09-11 (BACKLOG #207): systemctl is not
    # executable inside strict confinement either - found on the snap's
    # first-ever GUI launch, where clicking Enable raised PermissionError.
    autostart_available = detect_channel() == "deb"

    # Kept as two full sentences (not built by concatenating a fixed
    # base with a conditional suffix fragment) so each is one complete,
    # independently-translatable unit - xgettext extracts a whole
    # msgid fine either way, but a translator working from disconnected
    # fragments ("...login" + ", and enable...?") has no way to
    # reorder words across the join the way many languages need to.
    if hotkeys_available and autostart_available:
        intro = _("Set up Orcshot to start automatically at login, and enable its capture keyboard shortcuts?")
    elif hotkeys_available:
        intro = _("Set up Orcshot's capture keyboard shortcuts?")
    elif autostart_available:
        intro = _("Set up Orcshot to start automatically at login?")
    else:
        intro = _("Set up Orcshot?")
    content.pack_start(Gtk.Label(label=intro, wrap=True, xalign=0), False, False, 0)

    autostart_check = None
    if autostart_available:
        autostart_check = Gtk.CheckButton(label=_("Start automatically at login"))
        autostart_check.set_active(True)
        content.pack_start(autostart_check, False, False, 0)

    content.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

    binding_checks = {}
    if hotkeys_available:
        for hb in DEFAULT_HOTKEYS:
            hb_conflicts = conflicts.get(hb.name, [])
            if hb_conflicts:
                sources = ", ".join(c.source for c in hb_conflicts)
                label = _("{} ({}) — overwrite {}?").format(hb.name, hb.binding, sources)
                default_active = False
            else:
                label = _("{} ({})").format(hb.name, hb.binding)
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
            label=_("Automatic keyboard shortcut setup isn't available on this desktop. "
                    "You can bind shortcuts to these manually instead:\n")
                  + manual_lines,
            wrap=True, xalign=0,
        ), False, False, 0)

    # The GNOME extension is not offered as a checkbox - it is
    # unconditionally enabled below whenever this dialog completes with
    # OK on any real GNOME Shell session (is_gnome); one extension since
    # the 2026-09-11 spec, so there is no Wayland/X11 split any more.
    # Checked live rather than assumed (see gnome_extension_setup.
    # gnome_shell_present's docstring), same as autostart/hotkeys aren't
    # re-litigated as individually skippable app-core-functionality
    # choices either. direflail, on why: "it's
    # ALWAYS going to be enabled, otherwise the program won't work...
    # why else would you install this program if you didn't want
    # clipboard support? it's a screenshot app" - and the same
    # reasoning was extended to window-calls (needed for "Capture
    # Window" mode to work correctly under Wayland at all - see
    # REQUIREMENTS.md's Wayland window-picker section) and to
    # orcshot-tray (Task 7's own fix, added after this reasoning was
    # first settled - the tray icon/menu is exactly as core to "why
    # you'd install a screenshot app" as clipboard support) once it was
    # clear none of these checkboxes was protecting anyone who wasn't
    # already going to check it.
    #
    # No "requires logging out" warning either (removed, not just
    # never added here) - it was stale: gnome_clipboard.is_available()
    # (both gnome_window_picker.is_available and gnome_region_select.
    # is_available delegate to it) is a live Ping() probe, called fresh
    # on every single capture attempt, not a value cached at startup -
    # confirmed by reading it, not assumed. Combined with GNOME Shell
    # activating a freshly-enabled extension in well under a second
    # (measured live: ~0.3s), a first-time user's actual first capture
    # attempt - which happens some real seconds after finishing this
    # dialog, not the same instant - already sees the extension as
    # available. Even a capture attempted within that sub-second window
    # just gracefully falls back to the portal/invisible-window path
    # instead of failing, so there was never a real "won't work without
    # a restart" case to warn about. orcshot-tray has neither property
    # (no Ping()-style live probe, no fallback if it hasn't activated
    # yet this session) - this reasoning doesn't cover it, a real,
    # already-ledgered gap (BACKLOG.md, Task 4/5 Ruling) this comment
    # isn't relitigating, just flagging so a future reader doesn't
    # assume the paragraph above also justifies skipping the warning
    # for the tray extension.
    #
    # orcshot@orcshot.org is this project's own extension (its windows.js
    # module is a bundled third-party patched fork, documented in
    # THIRD_PARTY_NOTICES.md and debian/copyright - real provenance
    # worth documenting there, unlike a checkbox that most users have
    # no context to evaluate).
    is_gnome = gnome_shell_present()

    dialog.show_all()
    response = dialog.run()

    if response == Gtk.ResponseType.OK:
        if autostart_check is not None and autostart_check.get_active():
            # Best-effort, same reasoning as the extension-enable calls
            # below: hotkeys/gsettings writes should still go through
            # even if enabling the systemd unit hits a real-system
            # hiccup (task #141 follow-up). CalledProcessError alone is
            # enough here (not also OSError/FileNotFoundError) because
            # autostart.enable_autostart() itself now converts the
            # "systemctl doesn't exist at all" case into a
            # CalledProcessError - see its own docstring. This branch is
            # dead on the Flatpak channel in practice (autostart_check
            # is None there), but the guard stays as real defense, not
            # decoration - not every future caller of enable_autostart()
            # is guaranteed to check the channel first.
            try:
                enable_autostart()
            except subprocess.CalledProcessError as e:
                print(f"[orcshot] enable_autostart() failed: {e}", file=sys.stderr)

        if hotkeys_available:
            enabled_names = {name for name, check in binding_checks.items() if check.get_active()}
            skip, to_clear = resolve_hotkey_choices(enabled_names, conflicts)
            for conflict in to_clear:
                clear_conflict(settings_backend, conflict)
            configure_all_hotkeys(settings_backend, executable, skip=skip, profile=profile)

        if is_gnome:
            _finish_gnome_setup(settings_backend, "gnome", parent)
        elif profile == "cinnamon":
            _finish_cinnamon_setup(parent)

    mark_first_run_setup_done()
    dialog.destroy()
