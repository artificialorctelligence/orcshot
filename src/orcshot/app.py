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
from orcshot.i18n import _
from orcshot.ui.destination_picker import destinations_for_shell
from orcshot.settings import (
    clear_quit_marker, get_last_update_check, get_update_check_interval_days,
    is_quit_marker_set, set_last_update_check, write_quit_marker,
)
from orcshot.ui.capture_modes import (
    start_active_window_capture,
    start_full_screen_capture,
    start_last_region_capture,
)
from orcshot.autostart import remove_legacy_autostart_entry
from orcshot.resources import LOGO_PATH
from orcshot.ui.external_commands import maybe_seed_default_external_commands
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

    priority=GLib.PRIORITY_DEFAULT, not the plain GLib.idle_add(run)
    this used to be (task #150 follow-up): every capture mode routed
    through here ends up nesting request_screenshot()'s own blocking
    GLib.MainLoop().run() (capture/wayland_portal.py) one level inside
    this callback whenever the Shell extension isn't handling the
    capture - and GLib.idle_add's own default priority is
    PRIORITY_DEFAULT_IDLE, a *lower* priority than PRIORITY_DEFAULT,
    which this project's own established finding (portal-reentrancy
    note) already documented as capable of starving a deferred callback
    indefinitely under a continuous stream of other events. Live-
    observed as a real, if less severe, symptom of exactly that here:
    not a full hang, but the portal backend intermittently returning
    response_code=2 (PortalRequestFailed) for a request that succeeded
    every single time when made standalone, outside this idle-priority
    contention entirely - confirmed by calling the exact same
    request_screenshot() function directly, repeatedly, with no
    failures at all once it wasn't sharing an idle-priority slot with
    whatever else GNOME Shell/Mutter was scheduling at PRIORITY_DEFAULT
    or higher at that moment.
    """
    def run():
        action()
        return GLib.SOURCE_REMOVE

    GLib.idle_add(run, priority=GLib.PRIORITY_DEFAULT)


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
        self._tray_repeat_action = None
        self._tray_menu = None
        self._open_editors = []
        self._has_activated_before = False
        self._quit_after_editors_close = False
        self._restart_after_editors_close = False

    def do_startup(self):
        Gtk.Application.do_startup(self)
        _log_session_info()
        Gtk.Window.set_default_icon_from_file(str(LOGO_PATH))
        self._register_tray_actions()
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            # Best-effort, same reasoning as every other D-Bus call site
            # in this file (see first_run_setup.py's own
            # enable_extension_live calls for the same pattern): a
            # transient D-Bus hiccup here (get_dbus_connection()
            # returning None, or export_menu_model() raising) must not
            # silently skip everything else in do_startup - PyGObject
            # swallows an uncaught exception out of this vfunc, and this
            # call sits early enough that _build_tray_icon,
            # _check_shell_extension_health, and first-run setup would
            # all never run.
            try:
                self._export_tray_menu()
            except GLib.Error as e:
                print(f"[orcshot] _export_tray_menu() failed: {e}", file=sys.stderr)
        self._tray_icon = self._build_tray_icon()
        self._check_shell_extension_health()
        maybe_run_first_run_setup()
        # Separate from maybe_run_first_run_setup's own flag - this
        # must run on every very first app start regardless of
        # whether the user ever engages with the first-run wizard at
        # all (direflail's own explicit call).
        maybe_seed_default_external_commands()
        # Task #180: cleans up a stale pre-task-#141 autostart .desktop
        # entry, if one is still there, on every startup - naturally
        # idempotent (a no-op once removed), so unlike the seed call
        # above it doesn't need its own "already ran" flag, and it must
        # run for existing installs regardless of whether the user ever
        # touches the Preferences autostart checkbox again.
        remove_legacy_autostart_entry()

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

    _DESTINATIONS_IFACE_XML = """
    <node>
      <interface name="org.orcshot.Orcshot.Destinations">
        <method name="GetDestinations">
          <arg type="a(sss)" name="destinations" direction="out"/>
        </method>
      </interface>
    </node>
    """

    def do_dbus_register(self, connection, object_path):
        """Task #113: exposes destination_picker.py's own
        destinations_for_shell() as a real D-Bus method call (id,
        label, geometry_key) triples - not a GAction like
        _register_tray_actions above, since GAction.activate() is
        fire-and-forget with no return value (confirmed against
        extension.js's own _activateOrcshotAction docstring), and this
        needs an actual response. The Wayland Shell-native picker
        (pickDestinationAsync, orcshot-clipboard@orcshot.org) calls
        this instead of hardcoding its own destination list, so
        ExternalCommand entries show up there exactly like they
        already do in the X11 Gtk.Menu - confirmed live via a
        standalone GJS/Python D-Bus proof-of-concept before wiring
        this in for real.

        Must call the superclass implementation first - GApplication's
        own do_dbus_register is what exports every registered GAction
        at this same object_path via org.gtk.Actions (see
        _register_tray_actions's own docstring); skipping this would
        silently break every existing tray/capture action.
        """
        if not Gtk.Application.do_dbus_register(self, connection, object_path):
            return False
        node_info = Gio.DBusNodeInfo.new_for_xml(self._DESTINATIONS_IFACE_XML)
        interface_info = node_info.interfaces[0]

        def handle_method_call(connection, sender, path, iface, method, params, invocation):
            if method == "GetDestinations":
                invocation.return_value(GLib.Variant("(a(sss))", (destinations_for_shell(),)))

        connection.register_object(object_path, interface_info, handle_method_call)
        return True

    def do_command_line(self, command_line):
        # Task #161: snapshotted before self.activate() below (which
        # unconditionally sets it True every time, via do_activate) -
        # this is what lets the bare-invocation branch further down
        # tell "already running before this exact call" apart from
        # "just started running because of this exact call".
        was_already_running = self._has_activated_before
        self._has_activated_before = True
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
            opened_a_file = False
            for arg in command_line.get_arguments()[1:]:
                if not arg.startswith("-"):
                    self.open_file(arg)
                    opened_a_file = True
            # Task #161: the ONLY branch of this whole method that
            # doesn't already do something visible of its own - see
            # do_activate's own docstring for why this notification
            # exists and where it used to live (unconditionally, for
            # every branch above too - the actual bug).
            if not opened_a_file and was_already_running:
                self._notify(
                    _("Orcshot is already running"),
                    _("Look for its icon in the system tray."),
                    notification_id="orcshot-already-running",
                )
        return 0

    def open_file(self, path_or_uri: str) -> None:
        from orcshot.ui.editor_window import open_orcshot_file_in_new_window

        path = Gio.File.new_for_commandline_arg(path_or_uri).get_path()
        if path is not None:
            open_orcshot_file_in_new_window(path)

    def do_activate(self):
        # Keeps the app alive with no window of its own; the tray icon
        # is the only always-visible UI. hold()/release() bracket the
        # app's lifetime independent of any window being open. Only
        # ever reached via do_command_line's own self.activate() call
        # above - Gio.ApplicationFlags.HANDLES_COMMAND_LINE (set in
        # __init__) means GApplication itself never emits 'activate'
        # automatically, so there's no separate direct-launcher path
        # that skips do_command_line here to account for.
        #
        # Task #161: the "already running" notification that used to
        # live here fired completely unconditionally, on literally
        # every do_command_line invocation once this had already run
        # once - including every capture-hotkey press, since
        # do_command_line calls self.activate() before even checking
        # which option was given. Live-reported and precisely
        # diagnosed by direflail: "it's the same noise as Showing
        # Notifications plays - notification.oga", on every single
        # Print Screen press, "not sure when it started" (exactly
        # matching this bug's own shape: silent on the very first
        # activation of a session, firing on every one after that).
        # Moved to do_command_line's own bare-invocation branch, the
        # one case that doesn't already show something visible on its
        # own - see that method's own comment.
        self.hold()

    def start_capture(self) -> None:
        """Kept as the default single-click tray action - region
        select, matching Greenshot's Windows tray default. Mouse
        cursor forced off, same as every other tray-triggered capture
        below - see start_region_capture's docstring."""
        self.start_region_capture(capture_mouse_cursor=False)

    def _remember_region(self, rect) -> None:
        self.last_region = rect
        # Eager, not deferred to the tray menu's own "show" signal: X11's
        # local Gtk.Menu only ever fires "show" at construction time, not
        # on a real subsequent open when exported to a remote renderer -
        # not a reliable place to refresh state. Updating the item
        # directly the moment last_region actually changes works
        # identically on both platforms instead - on Wayland this means
        # flipping the GAction's own `enabled` property, which propagates
        # to orcshot-tray@orcshot.org automatically over the org.gtk.
        # Actions D-Bus interface (Gio.SimpleAction.set_enabled), no
        # export/refresh step of our own needed the way the menu
        # structure itself (_export_tray_menu) does.
        if self._repeat_item is not None:
            self._repeat_item.set_sensitive(True)
        if self._tray_repeat_action is not None:
            self._tray_repeat_action.set_enabled(True)

    def topmost_editor(self):
        """The most-recently-opened still-open editor, or None - the
        transient parent every dialog reachable with no editor
        necessarily open (tray icon, hotkey) should use: nicer window
        stacking when one exists, no parent at all when none are open,
        rather than each such call site duplicating this lookup."""
        return self._open_editors[-1] if self._open_editors else None

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

        show_preferences_dialog(self.topmost_editor())

    def open_file_from_tray(self) -> None:
        """The tray icon's own "Open File..." (task #140) - faithful to
        real Windows' own tray context menu, which has always had this
        (MainForm.Designer.cs:92's contextmenu_openfile, sitting right
        after the capture items in the real menu's AddRange order,
        MainForm.Designer.cs:83-103). Same topmost-open-editor-as-
        transient-parent reasoning as show_preferences just above.
        """
        from orcshot.ui.editor_window import choose_and_open_orcshot_file

        choose_and_open_orcshot_file(transient_for=self.topmost_editor())

    def register_editor_window(self, editor) -> None:
        self._open_editors.append(editor)

    def unregister_editor_window(self, editor) -> None:
        if editor in self._open_editors:
            self._open_editors.remove(editor)
        self._maybe_quit_after_upgrade_prep()
        self._maybe_restart_after_language_change()

    def _block_if_modal_dialog_open(self) -> bool:
        """True (after presenting the grabbing dialog instead) if a new
        capture shouldn't start right now because something else
        already holds a GTK grab.

        Real, reproduced live (task #138 follow-up): with the old,
        broader ``_block_if_editor_open`` removed (task #138 - multiple
        editors are meant to coexist, matching real Windows Greenshot),
        triggering a capture while e.g. EditorWindow's own close-time
        save prompt (``_on_delete_event``) was showing let a new
        capture overlay actually get created and shown (screen dims,
        crosshair cursor appears) but never receive any pointer input
        at all - reported live by direflail. Root cause:
        ``ui/region_select.py``'s overlay only ever grabs *keyboard*
        input via ``Gdk.Seat`` (see that module's own comment) - plain,
        ungrabbed button events are how its drag-select normally works,
        and ``Gtk.Dialog.run()`` (used by the save prompt, and 26 other
        ``Gtk.Dialog`` usages in ``editor_window.py`` alone -
        Preferences, Save As, text-entry dialogs, etc.) holds its own
        process-wide GTK grab for as long as it's open, intercepting
        that same pointer input first.

        Narrower than the removed ``_block_if_editor_open`` on purpose:
        that blocked on *any* open editor, even with nothing actually
        grabbing input, which is exactly what task #138 fixed. This
        only blocks when something concrete is actually grabbing right
        now, so multiple editor windows still coexist freely.
        """
        current = Gtk.grab_get_current()
        if current is None:
            return False
        current.get_toplevel().present()
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
        if self._block_if_modal_dialog_open():
            return
        self._run_capture(
            lambda: start_region_capture(on_captured=self._remember_region, capture_mouse_cursor=capture_mouse_cursor)
        )

    def start_full_screen_capture(self, capture_mouse_cursor: bool = True) -> None:
        if self._block_if_modal_dialog_open():
            return
        self._run_capture(lambda: start_full_screen_capture(
            on_captured=self._remember_region, capture_mouse_cursor=capture_mouse_cursor
        ))

    def start_active_window_capture(self, capture_mouse_cursor: bool = True) -> None:
        if self._block_if_modal_dialog_open():
            return
        self._run_capture(lambda: start_active_window_capture(
            on_captured=self._remember_region, capture_mouse_cursor=capture_mouse_cursor
        ))

    def start_window_picker(self, capture_mouse_cursor: bool = True) -> None:
        if self._block_if_modal_dialog_open():
            return
        self._run_capture(
            lambda: start_window_picker(on_captured=self._remember_region, capture_mouse_cursor=capture_mouse_cursor)
        )

    def start_last_region_capture(self, capture_mouse_cursor: bool = True) -> None:
        if self._block_if_modal_dialog_open():
            return
        # Deliberately not chained through _remember_region: the
        # region being repeated already *is* self.last_region, so
        # there's nothing new to record.
        self._run_capture(
            lambda: start_last_region_capture(self.last_region, capture_mouse_cursor=capture_mouse_cursor)
        )

    def _run_capture(self, action) -> None:
        """Runs a capture action, catching the one class of exception
        every capture entry point above can raise but none of them (nor
        anything downstream in region_select.py/window_picker.py/
        capture_modes.py) ever caught (task #150). All three portal
        exceptions (wayland_portal.py) come from the same source -
        capture_backend.grab() under Wayland when the Shell extension
        isn't handling the capture itself - a state that's completely
        normal, not a rare edge case: any Wayland session before
        first-run-setup enables orcshot-clipboard@orcshot.org, or any
        session where the user declined it, uses this portal path for
        every capture.

        Confirmed live as a real, always-reproducible crash before this
        fix: hitting Escape on the very first capture's permission
        dialog (PortalRequestCancelled, response_code=1 - the single
        most ordinary way to back out of a capture) crashed the whole
        app exactly the same as a genuine portal failure did
        (PortalRequestFailed, response_code=2, live-observed during
        task #145's verification - the crash that prompted this fix).

        PortalRequestCancelled is treated as a plain cancel - silently
        does nothing, the same as dismissing the region-select overlay
        or window-picker with Escape already does. PortalRequestFailed/
        PortalRequestTimedOut are surfaced via a real notification
        rather than silently swallowed, matching this class's own
        existing _notify() convention for other capture-adjacent
        failures above (e.g. the Shell-extension-fallback notice).
        """
        from orcshot.capture.wayland_portal import PortalRequestCancelled, PortalRequestFailed, PortalRequestTimedOut

        try:
            action()
        except PortalRequestCancelled:
            pass
        except (PortalRequestFailed, PortalRequestTimedOut) as e:
            self._notify(_("Screenshot failed"), _("The screenshot couldn't be taken.\n\n{}").format(e))

    def _tray_action_handlers(self) -> dict:
        """One handler per capture mode, keyed by the same mode string
        icons.py's capture_mode_icon_image() already uses - shared
        between _build_tray_menu's local Gtk.Menu (X11-only - see
        _build_tray_icon) and _register_tray_actions' GActions
        (activated by the Shell-native tray panel button in a
        *different* process on Wayland, see that method's own
        docstring), rather than defining the same five closures twice.
        """
        return {
            "region": lambda: self.start_region_capture(capture_mouse_cursor=False),
            "full_screen": lambda: self.start_full_screen_capture(capture_mouse_cursor=False),
            "active_window": lambda: self.start_active_window_capture(capture_mouse_cursor=False),
            "window_picker": lambda: self.start_window_picker(capture_mouse_cursor=False),
            "repeat_region": lambda: self.start_last_region_capture(capture_mouse_cursor=False),
        }

    def _register_tray_actions(self) -> None:
        """Exposes the same actions _tray_action_handlers backs as
        GActions, reachable over D-Bus with no custom interface code
        needed on this side - GApplication automatically exports
        every registered action at /org/orcshot/Orcshot (application_id
        with '.' replaced by '/') via the standard org.gtk.Actions
        interface, since this app is already a registered Gio.
        Application with a fixed application_id (see this file's own
        docstring). The Shell-native tray panel button
        (orcshot-tray@orcshot.org, rendering the menu
        _export_tray_menu publishes for it - see _build_tray_icon)
        lives in a separate process and activates these by name via
        Gio.DBusActionGroup instead of calling into this process
        directly - see that extension's own _activateTrayAction.
        """
        for mode, handler in self._tray_action_handlers().items():
            action = Gio.SimpleAction.new(f"tray-{mode}", None)
            action.connect("activate", lambda _action, _param, h=handler: _defer(h))
            self.add_action(action)
            if mode == "repeat_region":
                # Matches X11's own self._repeat_item.set_sensitive(False)
                # below - no region captured yet, nothing to repeat.
                # _remember_region flips this to enabled the moment a
                # real region capture actually happens (see its own
                # comment).
                self._tray_repeat_action = action
                action.set_enabled(False)
        open_file_action = Gio.SimpleAction.new("tray-open-file", None)
        open_file_action.connect("activate", lambda *_args: self.open_file_from_tray())
        self.add_action(open_file_action)
        preferences_action = Gio.SimpleAction.new("tray-preferences", None)
        preferences_action.connect("activate", lambda *_args: self.show_preferences())
        self.add_action(preferences_action)
        quit_action = Gio.SimpleAction.new("tray-quit", None)
        quit_action.connect("activate", lambda *_args: self._quit_and_hide_tray_button())
        self.add_action(quit_action)
        # Not "tray-*" - never appears in any menu, only ever invoked over
        # D-Bus by debian/orcshot.postinst (see prepare_for_upgrade below).
        prepare_for_upgrade_action = Gio.SimpleAction.new("prepare-for-upgrade", None)
        prepare_for_upgrade_action.connect("activate", lambda *_args: self.prepare_for_upgrade())
        self.add_action(prepare_for_upgrade_action)
        # Not "tray-*" either - task #158 follow-up. Invoked by the
        # bundled Shell extension's own pickDestinationAsync, right
        # before its destination-choosing menu opens, the same
        # Gio.DBusActionGroup.activate_action mechanism
        # _activateTrayAction already uses for tray clicks - see
        # capture/capture_feedback.py's own module docstring for why
        # the sound needs to fire from there instead of from Python's
        # own dispatch_destination (which only learns of a capture
        # *after* the Shell-native picker's own choice is already
        # made, too late to match X11's correct timing).
        from orcshot.capture.capture_feedback import play_capture_sound

        play_capture_sound_action = Gio.SimpleAction.new("play-capture-sound", None)
        play_capture_sound_action.connect("activate", lambda *_args: play_capture_sound())
        self.add_action(play_capture_sound_action)

    def _export_tray_menu(self) -> None:
        """Publishes the Wayland tray menu for orcshot-tray@orcshot.org
        to render - see gnome_tray_export.py's own module docstring
        for why this doesn't need a new bus name or action group, just
        the menu structure itself.

        Task 7 live-verification bug, root-caused: the built Gio.Menu
        must be kept alive for as long as it stays exported -
        g_dbus_connection_export_menu_model's own docs are explicit
        that "the data is owned by the caller of the method" (not
        the connection), and every known-good example of this API
        (this project's own earlier GMenu/GActionGroup prototype,
        gjs.guide's own D-Bus documentation) keeps the model as a
        persistent reference for exactly this reason. The first
        version of this method built `menu` as a plain local variable
        with nothing keeping it alive past this function returning -
        live-confirmed as the actual cause of a real bug: a
        Gio.DBusMenuModel client (orcshot-tray@orcshot.org's own
        panel button, and independently a brand-new test proxy
        created straight from Looking Glass) both got stuck at
        get_n_items() == 0 forever, never populating, despite a raw
        `gdbus call ... org.gtk.Menus.Start` against the same object
        path returning fully correct data - the export's answer to a
        one-off synchronous call still worked, but real GMenuModel
        client-side subscription/sync never completed. Storing it on
        self is what every other real usage of this API already does.
        """
        from orcshot.capture.gnome_tray_export import build_tray_menu, export_tray_menu

        labels = {
            "region": _("Capture Region"),
            "full_screen": _("Capture Full Screen"),
            "active_window": _("Capture Active Window"),
            "window_picker": _("Capture Window..."),
            "repeat_region": _("Repeat Last Region"),
            "open_file": _("Open File..."),
            "preferences": _("Preferences..."),
            "quit": _("Quit"),
        }
        color = _rgba_to_color(Gtk.Window().get_style_context().get_color(Gtk.StateFlags.NORMAL))
        # Kept alive on self for the app's whole lifetime - see this
        # method's own docstring above for why a local variable isn't
        # enough.
        self._tray_menu = build_tray_menu(labels, color)
        export_tray_menu(self, self._tray_menu)

    def _quit_and_hide_tray_button(self, write_marker: bool = True) -> None:
        """direflail: "when the user selects quit, i want all parts of
        the program to quit and vanish. it should not be running
        anymore... it should remain this way until the user
        restarts." (task #150 follow-up). self.quit() alone already
        fully terminates this process when nothing else is running a
        nested main loop - confirmed live, nothing was left in
        `ps aux` after a plain quit. No longer applicable: the old
        orcshot-clipboard@orcshot.org extension's own Shell-native tray
        panel button used to need an explicit best-effort Quitting()
        D-Bus call here so it would actually disappear instead of
        sticking around dimmed. The new orcshot-tray@orcshot.org
        extension (Backlog #184 follow-up) tears its own button down on
        its own via Gio.bus_watch_name's vanished callback the moment
        this process's D-Bus name drops, so there's nothing left for
        this method to notify.

        Task #169: live-confirmed (direflail, 2026-08-22) that Quit did
        nothing at all with Preferences open - root-caused via a
        minimal isolated repro (not a guess): Gtk.Dialog.run() runs
        its own nested GLib main loop, and Gio.Application.quit() only
        causes g_application_run()'s *outermost* loop to return once
        control actually gets back to it - it does not preempt an
        already-running nested one. With Preferences (or any other
        dialog.run()-based dialog in this codebase) open, self.quit()
        was requesting a return to a main loop that was never going to
        run again until that dialog closed on its own, which nothing
        was asking it to do - so nothing happened, forever, exactly
        matching the report. _close_open_modal_dialogs forces every
        currently-open Gtk.Dialog to respond before self.quit() runs,
        confirmed live to actually unwind the nested loop and let the
        real quit proceed. Every dialog.run() dialog reachable from
        the tray only ever has Close/Cancel-shaped responses that
        discard nothing (Preferences persists each field's setting
        immediately on change, not on close) - forcing a response is
        never a data-loss risk, just an early, deliberate close.

        Task #150 follow-up (round 2): also writes the quit marker
        main() checks before ever constructing a new instance - the
        process itself terminating fully was never the missing piece,
        the global capture hotkeys relaunching a fresh one regardless
        was (see main()'s own comment). ``write_marker=False`` is for
        _maybe_quit_after_upgrade_prep's own call below: a package
        upgrade quitting this process is not the user asking to stay
        quit "until the user restarts" - the whole point there is that
        it comes back (via systemd's own Restart=on-failure, or the
        next login) - so it must not leave the marker behind to
        incorrectly swallow the very next capture hotkey.
        """
        if write_marker:
            write_quit_marker()
        self._close_open_modal_dialogs()
        self.quit()

    def _close_open_modal_dialogs(self) -> None:
        """Forces every currently-visible Gtk.Dialog to respond (as if
        Cancel/Close had been clicked) - task #169. Gtk.Window.
        list_toplevels() is GTK's own registry of every realized
        top-level window, Dialogs included, so this reaches Preferences
        and every Add/Edit External Command dialog alike without this
        app needing to separately track each one - see
        _quit_and_hide_tray_button's own docstring for why this has to
        run before self.quit() rather than relying on it.
        """
        for window in Gtk.Window.list_toplevels():
            if isinstance(window, Gtk.Dialog) and window.get_visible():
                window.response(Gtk.ResponseType.CANCEL)

    def prepare_for_upgrade(self) -> None:
        """Best-effort package-upgrade hook (task #151 follow-up):
        debian/orcshot.postinst calls this (via `gdbus call ...
        org.gtk.Actions.Activate 'prepare-for-upgrade'`, the same
        mechanism the Shell-native tray button uses to invoke every
        other action here) on any already-running instance before
        replacing this package's files on disk, so an open editor with
        unsaved work doesn't just vanish under the user without a
        chance to save it.

        Deliberately does NOT block the postinst script that calls
        it, and postinst does NOT wait for this to finish - a root
        maintainer script blocking on a GUI action inside a logged-in
        user's session has no reliable way to know if or when anyone's
        watching to respond (unattended-upgrades, scripted installs,
        headless CI all run postinst with nobody there to click
        anything). Replacing this process's files while it keeps
        running is safe on Linux regardless - the already-running
        process just keeps executing the old code it already loaded
        into memory until it eventually exits on its own, same as any
        other program upgraded while running. This method is what
        makes "eventually" arrive promptly for the common case instead
        of leaving a stale instance silently squatting on the
        single-instance D-Bus name indefinitely (see do_activate's own
        "already running" notification for the other half of that same
        problem).
        """
        self._quit_after_editors_close = True
        for editor in list(self._open_editors):
            if editor.is_modified:
                editor.prompt_save_for_restart(_("New install incoming — save your work"))
            else:
                editor.close()
        self._maybe_quit_after_upgrade_prep()

    def _maybe_quit_after_upgrade_prep(self) -> None:
        if self._quit_after_editors_close and not self._open_editors:
            self._quit_and_hide_tray_button(write_marker=False)

    def restart_for_language_change(self) -> None:
        """Preferences' own language picker (task #183 follow-up) calls
        this once the user confirms they want to restart now rather
        than wait for the next natural one - mirrors
        prepare_for_upgrade's own "prompt-save any open editors, then
        act" shape, but the "act" here is a real self-restart rather
        than a quit, since the whole point is to come back running
        the new language immediately.
        """
        self._restart_after_editors_close = True
        for editor in list(self._open_editors):
            if editor.is_modified:
                editor.prompt_save_for_restart(_("Restarting Orcshot — save your work"))
            else:
                editor.close()
        self._maybe_restart_after_language_change()

    def _maybe_restart_after_language_change(self) -> None:
        """Task #183 follow-up, second attempt - direflail live-reported
        the first one ("os.execv in place") just quit instead of
        restarting. Root-caused outside this app entirely, not
        guessed: an isolated Type=dbus + BusName= systemd user unit
        (matching debian/orcshot.service's own config exactly)
        reproduced the identical failure - the moment execv's process-
        image replacement makes the D-Bus name transiently vanish,
        systemd's own Type=dbus tracking considers the unit "stopped"
        and tears it down before the freshly-exec'd image can get far
        enough to re-acquire the name and reach do_activate again.
        Spawning `systemctl --user restart` from inside this same
        process was tried next and has its own race: that subprocess
        inherits this unit's own cgroup, so it can be killed as
        collateral damage of the "stop" half of the very restart
        command it's trying to run.

        What actually works, confirmed the same way (same test unit,
        watched via journalctl): exiting with a non-zero status and
        letting the *existing* Restart=on-failure/RestartSec=2 already
        in debian/orcshot.service do the relaunch - the one restart
        path systemd's own Type=dbus supervision is actually built to
        support. Logged explicitly first since a bare non-zero exit
        looks identical to a real crash in journalctl otherwise.

        Third attempt, same live-testing round, no longer applicable: the
        old orcshot-clipboard@orcshot.org extension used to need an
        explicit _notify_tray_extension_quitting() D-Bus heads-up here so
        its own long-lived panel button would rebuild fresh on the next
        appear rather than staying stale. The new orcshot-tray@orcshot.org
        extension (Backlog #184 follow-up) has no such stale-build problem -
        it reads the tray menu live from the exported Gio.Menu/
        items-changed on every appear - so there's nothing left for this
        method to notify.
        """
        if self._restart_after_editors_close and not self._open_editors:
            print("[orcshot] restarting for a language change (exit 1 triggers systemd's Restart=on-failure)")
            sys.exit(1)

    def _check_shell_extension_health(self) -> None:
        """Surfaces one real, ordinary-but-easy-to-miss state
        _log_session_info can only log to a terminal nobody's watching
        (task #137 follow-up): the extension is running, but it's a
        *stale* cached copy from before an update - GNOME Shell caches
        an extension's JS module for the whole login session (see
        gnome_extension_setup.py's own docstring), so a package upgrade
        that changes extension.js leaves an already-running Shell
        serving the old module, Ping() included, until the user logs
        out and back in. First-run setup already tells a *new* user
        this ("Both require logging out and back in to take effect.")
        - nothing told an *existing*, upgrading user the same thing
        before this.

        Not installed/enabled at all is deliberately left alone here -
        that's the ordinary state on X11, or on Wayland before first-
        run setup has run at all, not something to nag about.
        """
        if os.environ.get("XDG_SESSION_TYPE") != "wayland":
            return
        from orcshot.capture.gnome_clipboard import EXPECTED_API_VERSION, get_live_api_version
        from orcshot.capture.gnome_region_select import is_available

        if not is_available():
            return

        live_version = get_live_api_version()
        if live_version is not None and live_version < EXPECTED_API_VERSION:
            self._notify(
                _("Orcshot's Wayland integration needs a restart"),
                _(
                    "An update changed how Orcshot's Shell extension works, but your session is "
                    "still running the previous version. Log out and back in to finish applying it."
                ),
            )

    def _build_tray_icon(self):
        """Returns a Gtk.StatusIcon (X11), or None (Wayland - see the
        branch below for why there's no local widget there at all).
        """
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            # No local widget at all, same reasoning as the old
            # Shell-native panel-button path this replaces (see
            # docs/superpowers/specs/2026-08-28-wayland-capture-redesign-design.md) -
            # orcshot-tray@orcshot.org owns the tray unconditionally
            # on Wayland now; unlike the extension it replaces, there
            # is no AppIndicator3 fallback to fall through to if it's
            # unavailable (first boot before a relogin, or the user
            # disabling extensions) - see _export_tray_menu's own
            # docstring for how that gap is surfaced instead.
            return None

        menu = self._build_tray_menu()

        icon = Gtk.StatusIcon()
        icon.set_from_file(str(LOGO_PATH))
        icon.set_tooltip_text("Orcshot")  # noqa: i18n (proper noun)
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
        from orcshot.ui.icons import capture_mode_icon_image, stock_icon_image

        menu = Gtk.Menu()
        icon_color = _rgba_to_color(Gtk.Window().get_style_context().get_color(Gtk.StateFlags.NORMAL))

        def menu_item(label: str, handler, *, icon_mode: str = None, icon_name: str = None) -> Gtk.MenuItem:
            # Gtk.ImageMenuItem, not a Gtk.MenuItem wrapping a hand-built
            # Gtk.Box(icon+label) - this menu is X11-only now (see
            # _build_tray_icon: Wayland returns None before this method
            # is ever called), but historically (task #137, before the
            # 2026-08-28 Wayland tray redesign replaced it entirely with
            # orcshot-tray@orcshot.org's Gio.Menu/GAction export) this
            # same Gtk.Menu was also handed to
            # AyatanaAppIndicator3.Indicator.set_menu() under Wayland and
            # rendered by a *remote* process (the Shell's own AppIndicator
            # support) over the DBusMenu protocol, not drawn locally at
            # all - that's why Gtk.ImageMenuItem was picked over a hand-
            # built Gtk.Box(icon+label): the DBusMenu exporter only knew
            # how to serialize icons from recognized GTK properties
            # (ImageMenuItem's own `image`), not by introspecting a menu
            # item's freeform widget tree. Deprecated since GTK 3.10 but
            # still functional - the deprecation is *why*
            # editor_window.py/destination_picker.py moved away from it
            # for their own (local-only) menus, not evidence it's broken -
            # and X11 still needs it kept for consistent icon rendering
            # here regardless of the Wayland history above.
            item = Gtk.ImageMenuItem(label=label)
            if icon_mode is not None:
                item.set_image(capture_mode_icon_image(icon_mode, icon_color))
            elif icon_name is not None:
                item.set_image(stock_icon_image(icon_name, icon_color, size=16))
            item.set_always_show_image(True)
            # Forcing LTR here is X11-only (this branch never runs on
            # Wayland - see _build_tray_icon). Historical context for why
            # this exists at all (task #137): back when this same
            # Gtk.Menu was also DBusMenu-exported to Wayland (see the
            # comment above - no longer true today), an attempt to force
            # RTL direction on these items to match Wayland's then
            # right-aligned icons broke icon display entirely there
            # (reverted - RTL evidently reorders GtkImageMenuItem's
            # internal image+label children, not just their rendering,
            # and the DBusMenu exporter's icon-extraction was order-
            # dependent). GtkImageMenuItem's icon side is governed by
            # gtk_widget_get_direction() - nothing here was setting it
            # explicitly, so it fell back to whatever the live session's
            # process-wide default resolved to, which on X11/Mint put
            # icons on the right. Forcing LTR here is what actually fixes
            # that for X11, and stays scoped to the X11-only branch below
            # regardless of how Wayland's own tray icon is built.
            if os.environ.get("XDG_SESSION_TYPE") != "wayland":
                item.set_direction(Gtk.TextDirection.LTR)
            item.connect("activate", lambda _item: handler())
            return item

        handlers = self._tray_action_handlers()

        region_item = menu_item(
            _("Capture Region"), lambda: _defer(handlers["region"]), icon_mode="region",
        )
        menu.append(region_item)

        full_screen_item = menu_item(
            _("Capture Full Screen"), lambda: _defer(handlers["full_screen"]), icon_mode="full_screen",
        )
        menu.append(full_screen_item)

        active_window_item = menu_item(
            _("Capture Active Window"), lambda: _defer(handlers["active_window"]), icon_mode="active_window",
        )
        menu.append(active_window_item)

        window_picker_item = menu_item(
            _("Capture Window..."), lambda: _defer(handlers["window_picker"]), icon_mode="window_picker",
        )
        from orcshot.capture.backend_select import window_picker_supported

        if not window_picker_supported():
            window_picker_item.set_sensitive(False)
            window_picker_item.set_tooltip_text(
                _(
                    "Not available on this Wayland session - enable window capture support "
                    "in Preferences, or use Capture Region instead."
                )
            )
        menu.append(window_picker_item)

        self._repeat_item = menu_item(
            _("Repeat Last Region"), lambda: _defer(handlers["repeat_region"]), icon_mode="repeat_region",
        )
        self._repeat_item.set_sensitive(False)  # no region captured yet
        menu.append(self._repeat_item)

        menu.append(Gtk.SeparatorMenuItem())

        # Task #140: real Windows' own tray context menu has always had
        # this (contextmenu_openfile, MainForm.Designer.cs:92), sitting
        # right after the capture items in the real AddRange order
        # (MainForm.Designer.cs:83-103) - this port had no equivalent
        # until now, meaning opening a file required already having an
        # editor open (its own File > Open) or going through the file
        # manager.
        open_file_item = menu_item(
            _("Open File..."), self.open_file_from_tray, icon_name="document-open-symbolic",
        )
        menu.append(open_file_item)

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
            _("Preferences..."), self.show_preferences, icon_name="preferences-system-symbolic",
        )
        menu.append(preferences_item)

        menu.append(Gtk.SeparatorMenuItem())

        # _quit_and_hide_tray_button, not bare self.quit - task #150
        # follow-up's quit marker (main()'s own comment) has to be
        # written on every quit path, and this local X11-only menu item
        # was the one path that bypassed it (the Shell-native panel
        # button's own "tray-quit" GAction already routes through it
        # correctly).
        quit_item = menu_item(_("Quit"), self._quit_and_hide_tray_button, icon_name="application-exit-symbolic")
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
                _("Orcshot update available"),
                _("A newer version of Orcshot is available! Do you want to download Orcshot {}?").format(tag),
                uri=url,
            )
        elif manual:
            self._show_up_to_date_dialog(parent)
        return False

    def _notify(
        self, title: str, body: str, *, uri: str = None, notification_id: str = "orcshot-update-available"
    ) -> None:
        """Shared with task #126 (capture-complete notifications,
        still pending) - Gio.Notification works because this app is
        already a registered Gio.Application. A stable id means a
        second call *with the same id* replaces the first rather than
        stacking duplicate notifications; notification_id defaults to
        this method's original single caller's id so that call site
        didn't need updating when a second, unrelated notification
        (task #151 follow-up's "already running" one) started sharing
        this method - the two must use different ids, or an "already
        running" notification could silently swallow a real pending
        update notification and vice versa.
        """
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        notification.set_icon(Gio.ThemedIcon.new("orcshot"))
        if uri is not None:
            notification.set_default_action_and_target("app.open-uri", GLib.Variant.new_string(uri))
        self.send_notification(notification_id, notification)

    def _show_update_check_failed_dialog(self, parent: Gtk.Window) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=parent, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
            text=_("Couldn't check for updates"),
            secondary_text=_("No response from GitHub - check your network connection and try again."),
        )
        dialog.run()
        dialog.destroy()

    def _show_up_to_date_dialog(self, parent: Gtk.Window) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=parent, message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
            text=_("Orcshot is up to date"),
            secondary_text=_("You're running the latest version ({}).").format(installed_version("orcshot")),
        )
        dialog.run()
        dialog.destroy()


_CAPTURE_CLI_FLAGS = tuple(
    f"--{opt}" for opt in (
        CAPTURE_REGION_OPTION, CAPTURE_FULL_SCREEN_OPTION, CAPTURE_ACTIVE_WINDOW_OPTION,
        CAPTURE_WINDOW_PICKER_OPTION, CAPTURE_LAST_REGION_OPTION,
    )
)


def main() -> int:
    # Explicit rather than relying on argv[0]-basename inference (GTK/
    # GLib's default): keeps WM_CLASS ("orcshot") matching the
    # packaged .desktop launcher's StartupWMClass regardless of how
    # this entry point actually gets invoked (bare command on PATH,
    # absolute path, a symlink, etc.) - a real gotcha for interpreted-
    # language GTK apps, confirmed via research before packaging.
    GLib.set_prgname("orcshot")

    # Task #150 follow-up: the global capture hotkeys (hotkey_setup.py)
    # are OS-level "run this command" keybindings, independent of
    # whether an Orcshot process is currently alive - so the very next
    # hotkey press after an explicit Quit launches a brand new instance
    # from scratch regardless, contradicting direflail's own stated
    # requirement ("it should not be running anymore... it should
    # remain this way until the user restarts") - live-reported:
    # pressing a capture hotkey after quitting both did the capture and
    # brought the tray icon back. Checked here, before the
    # Gio.Application is even constructed, so a hotkey-triggered
    # relaunch never gets far enough to build a tray icon or do
    # anything visible. A capture-flag invocation while the marker is
    # still set can only BE a hotkey-triggered relaunch - every genuine
    # manual reopen (Applications menu, a bare `orcshot` from a
    # terminal, a .orcshot file double-click) never carries one of
    # these flags, matching hotkey_setup.py's own HotkeyBinding table -
    # so that's the one unambiguous signal available from argv alone.
    # A manual reopen instead clears the marker and proceeds normally,
    # which is what "restarts" (task #150's own wording) means here.
    # Deliberately not touched when the marker isn't set at all (the
    # overwhelmingly common case): quit_marker_path() would otherwise
    # do a real filesystem stat on every single launch for no reason.
    if is_quit_marker_set():
        if sys.argv[1:] and any(flag in sys.argv[1:] for flag in _CAPTURE_CLI_FLAGS):
            return 0
        clear_quit_marker()

    app = OrcshotApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
