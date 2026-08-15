"""The persistent background application: a tray icon plus a
Gio.Application-based single-instance mechanism, so re-invoking this
entry point (e.g. from a hotkey binding) gets routed to the already-
running instance instead of spawning a duplicate process. This is
GIO's standard, built-in behavior for a fixed application_id - the
first ``run()`` registers a D-Bus name and owns it; a later ``run()``
with the same application_id detects that name is already owned and
forwards its command line to the running instance's do_command_line
instead of starting a new one. Verified empirically before writing
this file: a probe app running in one process, invoked a second time
from another process, showed both invocations landing in the first
process's PID, not two separate processes.

self.last_region tracks the absolute Rect from whichever capture mode
ran most recently (every start_*_capture wires its launch function's
on_captured callback to _remember_region), backing "Repeat Last
Region" - a fresh re-grab of that same spatial region, not cached
pixels, matching the Windows source's Shift+PrintScreen behavior. The
tray menu item is disabled until something's actually been captured.

Not unit tested for the same reason editor_window.py/region_select.py
aren't: GTK/GIO glue driving a live process and an on-screen tray icon,
with no meaningful headless test. Verified by actually running it.

do_startup calls ui.first_run_setup.maybe_run_first_run_setup(), which
shows a one-time confirmation dialog (REQUIREMENTS.md's "on first run
with a one-time user confirmation") offering to enable autostart and
the four capture hotkeys - see that module's docstring for why this is
the only place in the codebase allowed to write to the user's real
desktop configuration, and only via a human clicking a real button.
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from importlib.metadata import version as installed_version

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from orcshot.core.update_check import is_newer_version, should_check_now
from orcshot.settings import get_last_update_check, get_update_check_interval_days, set_last_update_check
from orcshot.ui.capture_modes import (
    start_active_window_capture,
    start_full_screen_capture,
    start_last_region_capture,
)
from orcshot.resources import LOGO_PATH
from orcshot.ui.first_run_setup import maybe_run_first_run_setup
from orcshot.ui.region_select import start_region_capture
from orcshot.ui.update_check import fetch_latest_release
from orcshot.ui.window_picker import start_window_picker

APPLICATION_ID = "org.orcshot.Orcshot"
CAPTURE_REGION_OPTION = "capture-region"
CAPTURE_FULL_SCREEN_OPTION = "capture-full-screen"
CAPTURE_ACTIVE_WINDOW_OPTION = "capture-active-window"
CAPTURE_WINDOW_PICKER_OPTION = "capture-window-picker"
CAPTURE_LAST_REGION_OPTION = "capture-last-region"
# Real Windows checks 20s after startup, not immediately
# (UpdateService.cs's BackgroundTask: "Initial delay, to make sure
# this doesn't happen at the startup") - avoids competing with the
# app's own startup/first-run dialog for attention or bandwidth.
_UPDATE_CHECK_STARTUP_DELAY_SECONDS = 20
# How often the periodic timer re-evaluates whether a check is due
# (core/update_check.py's should_check_now) - day-granularity
# interval settings don't need finer polling than this; simpler than
# reproducing UpdateService.cs's own dynamic TimeSpan rescheduling.
_UPDATE_CHECK_POLL_INTERVAL_SECONDS = 3600


def _rgba_to_color(rgba: Gdk.RGBA) -> tuple:
    return (round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255), round(rgba.alpha * 255))


def _log_session_info() -> None:
    """Logs which capture backend this run will actually use, once, at
    startup. Added after a real incident: X11 vs Wayland is decided by
    the display manager at login, not something this app (or a
    developer testing it) can see just by looking at the desktop - a
    VM that had been Wayland for an entire debugging session silently
    came back as X11 after being rebuilt from a crash (same installer,
    just more RAM/a different resolution), and every "it works" check
    made afterward was actually exercising the X11-native capture path,
    not the GNOME Shell extension path that session's actual bug fixes
    targeted. `region_select.py`/`window_picker.py`/`_build_tray_icon`
    already re-read `XDG_SESSION_TYPE` fresh at each decision point
    (correct - a session-type change always means a fresh login, which
    always means a fresh process via autostart, so there's nothing to
    watch for *during* a run) - what was actually missing was any way
    to see, after the fact, which path a given run took at all.
    """
    import sys

    session_type = os.environ.get("XDG_SESSION_TYPE", "<unset>")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "<unset>")
    if session_type == "wayland":
        from orcshot.capture.gnome_region_select import is_available as gnome_shell_capture_available

        extension = "available" if gnome_shell_capture_available() else "unavailable - falling back to portal-based capture"
        backend = f"Wayland, GNOME Shell extension {extension}"
    else:
        backend = f"{session_type} (X11-native capture path)"
    print(f"[orcshot] session_type={session_type} desktop={desktop} -> {backend}", file=sys.stderr, flush=True)


def _defer(action) -> None:
    """Runs ``action`` on the next main-loop iteration instead of
    synchronously from within the caller. Every tray-menu item's own
    "activate" handler used to call its capture-mode-starting method
    directly - confirmed live (task #134) as a real race on X11/Mint
    and Ubuntu 24.04/GNOME 46: the tray menu's own popdown/hide is
    itself just a request queued during that same signal emission, not
    something guaranteed to have reached the display server yet, and a
    capture that starts synchronously can grab a screenshot (or, for
    Window Picker, a specific window's frame rect) before that request
    has actually been processed - a fragment of the still-technically-
    visible menu ends up baked into the resulting image. Not
    reproducible on Ubuntu 26.04/GNOME 50 - almost certainly a relative-
    speed difference between display stacks rather than a different
    code path, since the exact same synchronous call pattern is used
    identically on both. Yielding one main-loop iteration here gives
    GTK's own popdown handling (and, on X11, the display flush) a
    chance to actually complete first, matching the standard fix for
    this class of "closed a menu and started new UI work in the same
    callback" race.
    """
    def run():
        action()
        return GLib.SOURCE_REMOVE

    GLib.idle_add(run)


class OrcshotApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APPLICATION_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self._tray_icon = None
        self.add_main_option(
            CAPTURE_REGION_OPTION, ord("r"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Start a region capture", None,
        )
        self.add_main_option(
            CAPTURE_FULL_SCREEN_OPTION, ord("f"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Capture the whole screen", None,
        )
        self.add_main_option(
            CAPTURE_ACTIVE_WINDOW_OPTION, ord("w"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Capture the active window", None,
        )
        self.add_main_option(
            CAPTURE_WINDOW_PICKER_OPTION, ord("p"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Pick a window to capture", None,
        )
        self.add_main_option(
            CAPTURE_LAST_REGION_OPTION, ord("l"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Repeat the last captured region", None,
        )
        self.last_region = None
        self._repeat_item = None
        self._open_editors = []

    def do_startup(self):
        Gtk.Application.do_startup(self)
        _log_session_info()
        Gtk.Window.set_default_icon_from_file(str(LOGO_PATH))
        self._tray_icon = self._build_tray_icon()
        maybe_run_first_run_setup()

        # "app.open-uri" backs every notification's default (click)
        # action below - Gio.Notification can only target a
        # registered GAction, there's no "just open this URL" built
        # in the way a plain callback would be.
        open_uri_action = Gio.SimpleAction.new("open-uri", GLib.VariantType.new("s"))
        open_uri_action.connect(
            "activate", lambda _action, param: Gio.AppInfo.launch_default_for_uri(param.get_string(), None)
        )
        self.add_action(open_uri_action)

        GLib.timeout_add_seconds(_UPDATE_CHECK_STARTUP_DELAY_SECONDS, self._start_periodic_update_checks)

    def do_command_line(self, command_line):
        self.activate()
        options = command_line.get_options_dict()
        if options.contains(CAPTURE_REGION_OPTION):
            self.start_region_capture()
        elif options.contains(CAPTURE_FULL_SCREEN_OPTION):
            self.start_full_screen_capture()
        elif options.contains(CAPTURE_ACTIVE_WINDOW_OPTION):
            self.start_active_window_capture()
        elif options.contains(CAPTURE_WINDOW_PICKER_OPTION):
            self.start_window_picker()
        elif options.contains(CAPTURE_LAST_REGION_OPTION):
            self.start_last_region_capture()
        else:
            # task #129: a file-manager double-click/"Open With" on a
            # .orcshot file (MimeType=application/x-orcshot in
            # debian/orcshot.desktop) execs `orcshot %u` - a URI, not
            # necessarily a plain path - which lands here as a
            # positional argument, same as any other CLI invocation.
            # Already routed through the same single-instance
            # do_command_line forwarding every capture option above
            # uses, so opening a file while Orcshot is already running
            # reaches this same running instance rather than spawning
            # a second one.
            for arg in command_line.get_arguments()[1:]:
                if not arg.startswith("-"):
                    self.open_file(arg)
        return 0

    def open_file(self, path_or_uri: str) -> None:
        from orcshot.ui.editor_window import open_orcshot_file_in_new_window

        path = Gio.File.new_for_commandline_arg(path_or_uri).get_path()
        if path is not None:
            open_orcshot_file_in_new_window(path)

    def do_activate(self):
        # Keeps the app alive with no window of its own; the tray icon
        # is the only always-visible UI. hold()/release() bracket the
        # app's lifetime independent of any window being open.
        self.hold()

    def start_capture(self) -> None:
        """Kept as the default single-click tray action - region
        select, matching Greenshot's Windows tray default. Mouse
        cursor forced off, same as every other tray-triggered capture
        below - see start_region_capture's docstring."""
        self.start_region_capture(capture_mouse_cursor=False)

    def _remember_region(self, rect) -> None:
        self.last_region = rect
        # Eager, not deferred to the tray menu's own "show" signal:
        # confirmed live that AppIndicator3 (Wayland) exports the menu
        # structure to the shell once and renders its own copy from
        # then on, so our local Gtk.Menu's "show" only ever fires at
        # construction time, never on a real subsequent open - "show"
        # is not a reliable place to refresh state for that mechanism.
        # Updating the item directly the moment last_region actually
        # changes works identically on both platforms instead.
        if self._repeat_item is not None:
            self._repeat_item.set_sensitive(True)

    def show_preferences(self) -> None:
        """Task #119: the tray icon's own "Preferences..." item. Uses
        the topmost open editor as the dialog's transient parent when
        one exists (nicer window stacking, same as opening it from
        that editor's own Edit menu would), falling back to no parent
        at all when none are open - the whole point of this task,
        since Preferences was previously only reachable from inside an
        already-open editor.
        """
        from orcshot.ui.editor_window import show_preferences_dialog

        parent = self._open_editors[-1] if self._open_editors else None
        show_preferences_dialog(parent)

    def register_editor_window(self, editor) -> None:
        self._open_editors.append(editor)

    def unregister_editor_window(self, editor) -> None:
        if editor in self._open_editors:
            self._open_editors.remove(editor)

    def _block_if_editor_open(self) -> bool:
        """True (after focusing the existing editor instead) if a new
        capture shouldn't start right now because one's already open.

        Without this, triggering a hotkey while EditorWindow is open
        produces a confusing, silent no-op - reported live: the
        capture overlay/destination-picker flow never visibly
        appeared, though the app didn't hang either. Root cause wasn't
        pinned down precisely (Cinnamon/Muffin focus-stealing
        prevention likely keeps the newly-created override-redirect
        overlay from actually receiving input while the editor already
        has focus), but disallowing overlapping captures avoids the
        whole scenario rather than chasing that edge case, and matches
        the reasonable expectation that starting a new capture
        mid-annotation isn't something you'd want to happen anyway.
        """
        if not self._open_editors:
            return False
        self._open_editors[-1].present()
        return True

    def start_region_capture(self, capture_mouse_cursor: bool = True) -> None:
        """``capture_mouse_cursor`` faithfully replicates Windows'
        own asymmetry (CaptureHelper.cs's ``_captureMouseCursor``
        parameter, see PluginHelper.cs:141): hotkey/CLI invocations
        (do_command_line, the default True here) defer to the
        Preferences "Capture mouse cursor" setting, but every
        tray-icon-triggered capture below passes False, hardcoding
        the cursor off regardless of that setting - matching
        MainForm.cs's tray context-menu handlers, which do the same.
        The reasoning carries over unchanged: by the time you've
        clicked the tray icon or one of its menu items, your mouse is
        over the icon/menu, not your content, so showing it there
        would be misleading. See ui/capture_modes.py's module
        docstring and REQUIREMENTS.md's cursor auto-capture section
        for the full citation trail.
        """
        if self._block_if_editor_open():
            return
        start_region_capture(on_captured=self._remember_region, capture_mouse_cursor=capture_mouse_cursor)

    def start_full_screen_capture(self, capture_mouse_cursor: bool = True) -> None:
        if self._block_if_editor_open():
            return
        start_full_screen_capture(on_captured=self._remember_region, capture_mouse_cursor=capture_mouse_cursor)

    def start_active_window_capture(self, capture_mouse_cursor: bool = True) -> None:
        if self._block_if_editor_open():
            return
        start_active_window_capture(on_captured=self._remember_region, capture_mouse_cursor=capture_mouse_cursor)

    def start_window_picker(self, capture_mouse_cursor: bool = True) -> None:
        if self._block_if_editor_open():
            return
        start_window_picker(on_captured=self._remember_region, capture_mouse_cursor=capture_mouse_cursor)

    def start_last_region_capture(self, capture_mouse_cursor: bool = True) -> None:
        if self._block_if_editor_open():
            return
        # Deliberately not chained through _remember_region: the
        # region being repeated already *is* self.last_region, so
        # there's nothing new to record.
        start_last_region_capture(self.last_region, capture_mouse_cursor=capture_mouse_cursor)

    def _build_tray_icon(self):
        """Returns a Gtk.StatusIcon (X11) or an AyatanaAppIndicator3.
        Indicator (Wayland) - deliberately not unified onto one
        mechanism for both platforms, see the branch below for why.
        """
        menu = self._build_tray_menu()

        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            # Gtk.StatusIcon relies on XEmbed, which doesn't exist
            # under Wayland - confirmed live it never actually embeds
            # (is_embedded() == False), and its internal icon-scaling
            # code throws a Gtk-CRITICAL (gtk_widget_get_scale_factor:
            # assertion 'GTK_IS_WIDGET' failed) trying to render an
            # icon with no real widget behind it (task #66). Ayatana
            # AppIndicator3 is the portable, D-Bus-based
            # (StatusNotifierItem) replacement that actually works
            # here - confirmed live, icon renders and the menu opens.
            #
            # Deliberately kept X11-only for Gtk.StatusIcon rather
            # than switching both platforms to this: confirmed live
            # that AppIndicator has no distinct left-click ("activate")
            # action once a menu is attached - the real desktop
            # indicator host shows the same menu regardless of which
            # button was clicked (a long-documented AppIndicator
            # design limitation, not something fixable from here - see
            # https://bugs.launchpad.net/bugs/1910521). Switching X11
            # over too would lose the left-click-for-instant-capture
            # shortcut that already works correctly there today
            # (matching Windows Greenshot's own tray default - see
            # start_capture's docstring) for no benefit, since nothing
            # is broken on X11 to begin with.
            import gi

            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3

            indicator = AyatanaAppIndicator3.Indicator.new(
                "orcshot", LOGO_PATH.stem, AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            )
            # set_icon (not set_icon_full/an installed icon-theme name):
            # this app ships one bundled PNG rather than installing
            # into the system icon theme - set_icon_theme_path points
            # the indicator at that file's own directory so the plain
            # name (no extension) it was constructed with resolves.
            indicator.set_icon_theme_path(str(LOGO_PATH.parent))
            indicator.set_title("Orcshot")
            indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
            indicator.set_menu(menu)
            return indicator

        icon = Gtk.StatusIcon()
        icon.set_from_file(str(LOGO_PATH))
        icon.set_tooltip_text("Orcshot")
        icon.connect("activate", lambda _icon: self.start_capture())
        icon.connect("popup-menu", lambda _icon, button, time: self._show_tray_menu(menu, button, time))
        return icon

    def _build_tray_menu(self) -> Gtk.Menu:
        # Task #137: real Windows Greenshot has an icon on every one of
        # these items too (MainForm.Designer.cs: contextmenu_capturearea.
        # Image, contextmenu_capturewindow.Image, contextmenu_settings.
        # Image, contextmenu_exit.Image, etc.) - this menu had never had
        # any, on any platform, confirmed live by direflail on Ubuntu
        # 24.04, 26.04, and X11/Mint alike. Capture-mode icons are hand-
        # drawn (icons.py's capture_mode_icon_image - no standardized
        # freedesktop name for "region select"/"active window", same
        # reasoning as the tool-palette icons in that file's own
        # docstring); Preferences/Quit reuse standard theme icon names,
        # matching editor_window.py's own menu_item helper and its
        # existing "preferences-system-symbolic" for the same action.
        from orcshot.ui.icons import capture_mode_icon_image

        menu = Gtk.Menu()
        icon_color = _rgba_to_color(Gtk.Window().get_style_context().get_color(Gtk.StateFlags.NORMAL))

        def menu_item(label: str, handler, *, icon_mode: str = None, icon_name: str = None) -> Gtk.MenuItem:
            # Gtk.ImageMenuItem, not a Gtk.MenuItem wrapping a hand-built
            # Gtk.Box(icon+label) - this menu (unlike editor_window.py's
            # own menu_item helper, which builds a purely local, X11/
            # Wayland-both-fine Gtk.Menu) gets exported over the
            # DBusMenu protocol by AyatanaAppIndicator3.Indicator.
            # set_menu() under Wayland, rendered by a *remote* process
            # (the Shell's own AppIndicator support), not drawn locally
            # at all. Confirmed live (task #137): the Box+Image+Label
            # version showed icons correctly on X11 (real local Gtk.Menu
            # rendering, understands arbitrary child widgets) but showed
            # none at all on Wayland/Ubuntu 26.04 - the DBusMenu exporter
            # only knows how to serialize icons from recognized GTK
            # properties (ImageMenuItem's own `image`), not by
            # introspecting a menu item's freeform widget tree. Same
            # underlying "cross-process menu rendering has its own rules"
            # class of issue task #133 already hit for the destination
            # picker, just a different mechanism (DBusMenu export here,
            # vs. that one's Shell-native PopupMenu). Deprecated since
            # GTK 3.10 but still functional - the deprecation is *why*
            # editor_window.py/destination_picker.py moved away from it
            # for their own (local-only) menus, not evidence it's broken.
            item = Gtk.ImageMenuItem(label=label)
            if icon_mode is not None:
                item.set_image(capture_mode_icon_image(icon_mode, icon_color))
            elif icon_name is not None:
                item.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU))
            item.set_always_show_image(True)
            # Icon side wants to be left on both platforms (task #137).
            # On Wayland this menu is DBusMenu-exported (see the comment
            # above) and ubuntu-appindicators@ubuntu.com's dbusMenu.js
            # hard-codes Clutter.ActorAlign.END for every item's icon,
            # with no DBusMenu property a client can set to override it
            # - confirmed by reading its actual source, not fixable from
            # here. An earlier attempt to force RTL direction on this
            # item to compensate broke icon display entirely on Wayland
            # (reverted - RTL evidently reorders GtkImageMenuItem's
            # internal image+label children, not just their rendering,
            # and the DBusMenu exporter's icon-extraction is order-
            # dependent). On X11 this menu is a genuine local Gtk.Menu
            # (never exported), and GtkImageMenuItem's icon side is
            # governed by gtk_widget_get_direction() - nothing here was
            # setting it explicitly, so it fell back to whatever the
            # live session's process-wide default resolved to. Forcing
            # LTR here is the opposite change from the one that broke
            # Wayland and is scoped to the X11-only branch, so it can't
            # repeat that regression.
            if os.environ.get("XDG_SESSION_TYPE") != "wayland":
                item.set_direction(Gtk.TextDirection.LTR)
            item.connect("activate", lambda _item: handler())
            return item

        region_item = menu_item(
            "Capture Region", lambda: _defer(lambda: self.start_region_capture(capture_mouse_cursor=False)),
            icon_mode="region",
        )
        menu.append(region_item)

        full_screen_item = menu_item(
            "Capture Full Screen",
            lambda: _defer(lambda: self.start_full_screen_capture(capture_mouse_cursor=False)),
            icon_mode="full_screen",
        )
        menu.append(full_screen_item)

        active_window_item = menu_item(
            "Capture Active Window",
            lambda: _defer(lambda: self.start_active_window_capture(capture_mouse_cursor=False)),
            icon_mode="active_window",
        )
        menu.append(active_window_item)

        window_picker_item = menu_item(
            "Capture Window...", lambda: _defer(lambda: self.start_window_picker(capture_mouse_cursor=False)),
            icon_mode="window_picker",
        )
        from orcshot.capture.backend_select import window_picker_supported

        if not window_picker_supported():
            window_picker_item.set_sensitive(False)
            window_picker_item.set_tooltip_text(
                "Not available on this Wayland session - enable window capture support "
                "in Preferences, or use Capture Region instead."
            )
        menu.append(window_picker_item)

        self._repeat_item = menu_item(
            "Repeat Last Region",
            lambda: _defer(lambda: self.start_last_region_capture(capture_mouse_cursor=False)),
            icon_mode="repeat_region",
        )
        self._repeat_item.set_sensitive(False)  # no region captured yet
        menu.append(self._repeat_item)

        menu.append(Gtk.SeparatorMenuItem())

        # Task #119: real Windows' own tray context menu has this too
        # (contextmenu_settings, MainForm.Designer.cs - labeled
        # "Preferences..." there, language-en-US.xml:62, matching
        # this port's own Edit menu wording already), sitting after
        # the capture items and before Exit, same relative position
        # used here. Before this task, Preferences was only reachable
        # from inside an already-open editor - this is the only way to
        # reach it with none open at all.
        preferences_item = menu_item(
            "Preferences...", self.show_preferences, icon_name="preferences-system-symbolic",
        )
        menu.append(preferences_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = menu_item("Quit", self.quit, icon_name="application-exit-symbolic")
        menu.append(quit_item)
        menu.show_all()
        return menu

    def _show_tray_menu(self, menu: Gtk.Menu, button: int, time: int) -> None:
        menu.popup(None, None, None, None, button, time)

    def _start_periodic_update_checks(self) -> bool:
        self._periodic_update_check_tick()
        GLib.timeout_add_seconds(_UPDATE_CHECK_POLL_INTERVAL_SECONDS, self._periodic_update_check_tick)
        return False  # one-shot: the recurring timer above takes over

    def _periodic_update_check_tick(self) -> bool:
        self._run_update_check(manual=False)
        return True  # GLib.timeout_add_seconds: keep repeating

    def check_for_updates_now(self, parent: Gtk.Window = None) -> None:
        """Help > Check for Updates... (task #103) - an Orcshot-only
        addition; real Windows' own UpdateService.cs has no manual
        trigger at all, purely the background timer this shares its
        machinery with (see REQUIREMENTS.md). Unlike the silent
        background check, a manual click always reports back - either
        way, not just when there's an update - since silence after a
        deliberate click would look broken. ``parent`` is the calling
        EditorWindow (its Help menu is the only place this is wired
        today), used as the result dialog's transient parent.
        """
        self._run_update_check(manual=True, parent=parent)

    def _run_update_check(self, *, manual: bool, parent: Gtk.Window = None) -> None:
        if not manual and not should_check_now(
            get_last_update_check(), get_update_check_interval_days(), datetime.now()
        ):
            return
        set_last_update_check(datetime.now())
        threading.Thread(target=self._fetch_and_report, args=(manual, parent), daemon=True).start()

    def _fetch_and_report(self, manual: bool, parent: Gtk.Window) -> None:
        # Runs on a background thread - urlopen() would otherwise
        # block the GTK main loop. GLib.idle_add hands the result back
        # to the main thread, since every call below it (dialogs,
        # notifications) needs to happen there.
        result = fetch_latest_release()
        GLib.idle_add(self._on_update_check_result, result, manual, parent)

    def _on_update_check_result(self, result: tuple | None, manual: bool, parent: Gtk.Window) -> bool:
        if result is None:
            if manual:
                self._show_update_check_failed_dialog(parent)
            return False  # GLib.idle_add: one-shot

        tag, url = result
        if is_newer_version(tag, installed_version("orcshot")):
            self._notify(
                "Orcshot update available",
                f"A newer version of Orcshot is available! Do you want to download Orcshot {tag}?",
                uri=url,
            )
        elif manual:
            self._show_up_to_date_dialog(parent)
        return False

    def _notify(self, title: str, body: str, *, uri: str = None) -> None:
        """Shared with task #126 (capture-complete notifications,
        still pending) - Gio.Notification works because this app is
        already a registered Gio.Application. A stable id means a
        second call replaces the first rather than stacking duplicate
        notifications.
        """
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        notification.set_icon(Gio.ThemedIcon.new("orcshot"))
        if uri is not None:
            notification.set_default_action_and_target("app.open-uri", GLib.Variant.new_string(uri))
        self.send_notification("orcshot-update-available", notification)

    def _show_update_check_failed_dialog(self, parent: Gtk.Window) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=parent, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
            text="Couldn't check for updates",
            secondary_text="No response from GitHub - check your network connection and try again.",
        )
        dialog.run()
        dialog.destroy()

    def _show_up_to_date_dialog(self, parent: Gtk.Window) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=parent, message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
            text="Orcshot is up to date",
            secondary_text=f"You're running the latest version ({installed_version('orcshot')}).",
        )
        dialog.run()
        dialog.destroy()


def main() -> int:
    # Explicit rather than relying on argv[0]-basename inference (GTK/
    # GLib's default): keeps WM_CLASS ("orcshot") matching the
    # packaged .desktop launcher's StartupWMClass regardless of how
    # this entry point actually gets invoked (bare command on PATH,
    # absolute path, a symlink, etc.) - a real gotcha for interpreted-
    # language GTK apps, confirmed via research before packaging.
    GLib.set_prgname("orcshot")
    app = OrcshotApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
