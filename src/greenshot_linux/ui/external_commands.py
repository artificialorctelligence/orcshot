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

import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from greenshot_linux.settings import ExternalCommand, get_external_commands, set_external_commands
from greenshot_linux.ui.file_export import greenshot_linux_cache_dir, save_image_to_file

_LOG = logging.getLogger(__name__)
_DEFAULT_ARGUMENT_TEMPLATE = "{0}"
# Real Windows has no such cap (WaitForExit() blocks forever) - added
# here so a hung external process can't leak a background thread
# forever. Generous enough that no normal use (opening an app,
# running a quick upload script) should ever hit it.
_TIMEOUT_SECONDS = 300


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
    """
    directory = greenshot_linux_cache_dir()
    fd, path_str = tempfile.mkstemp(suffix=".png", prefix="greenshot-linux-external-", dir=str(directory))
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
        return "Name is required."
    other_names = {c.name for c in get_external_commands() if c.name != existing_name}
    if name in other_names:
        return "A command with this name already exists."
    if not commandline.strip():
        return "Command is required."
    if shutil.which(commandline) is None and not Path(commandline).is_file():
        return "Command not found - check the path, or that it's on your PATH."
    try:
        for token in shlex.split(argument):
            token.format("")
    except ValueError as error:
        return f"Invalid arguments: {error}"
    return None


def _show_command_detail_dialog(parent: Gtk.Window, existing: ExternalCommand | None) -> ExternalCommand | None:
    """Add/edit a single command. Returns the new/edited
    ExternalCommand, or None if cancelled. Faithful-in-spirit port of
    SettingsFormDetail (SettingsFormDetail.cs) - minus the OutputFormat
    dropdown (see this module's own docstring) and the Windows
    "Executables (*.exe, *.bat, *.com)" file filter, which has no
    Linux equivalent (executables carry no reserved extension here) -
    a plain unfiltered file chooser is offered instead.
    """
    dialog = Gtk.Dialog(title="External Command", transient_for=parent, modal=True)
    ok_button = dialog.add_button("OK", Gtk.ResponseType.OK)
    dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
    content = dialog.get_content_area()
    content.set_border_width(12)
    content.set_spacing(6)

    grid = Gtk.Grid(row_spacing=6, column_spacing=6)
    content.pack_start(grid, False, False, 0)

    name_entry = Gtk.Entry()
    name_entry.set_text(existing.name if existing else "")
    grid.attach(Gtk.Label(label="Name:", xalign=0), 0, 0, 1, 1)
    grid.attach(name_entry, 1, 0, 2, 1)

    command_entry = Gtk.Entry()
    command_entry.set_text(existing.commandline if existing else "")
    grid.attach(Gtk.Label(label="Command:", xalign=0), 0, 1, 1, 1)
    grid.attach(command_entry, 1, 1, 1, 1)
    browse_button = Gtk.Button(label="Browse...")

    def on_browse(_button) -> None:
        chooser = Gtk.FileChooserDialog(title="Select Command", transient_for=dialog, action=Gtk.FileChooserAction.OPEN)
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
    argument_entry.set_tooltip_text("{0} is replaced with the screenshot's exported file path.")
    grid.attach(Gtk.Label(label="Arguments:", xalign=0), 0, 2, 1, 1)
    grid.attach(argument_entry, 1, 2, 2, 1)

    background_check = Gtk.CheckButton(label="Run in background")
    background_check.set_active(existing.run_in_background if existing else True)
    grid.attach(background_check, 1, 3, 2, 1)

    error_label = Gtk.Label(xalign=0)
    content.pack_start(error_label, False, False, 0)

    def revalidate(*_args) -> None:
        error = _validate(
            name_entry.get_text(), command_entry.get_text(), argument_entry.get_text(),
            existing.name if existing else None,
        )
        error_label.set_text(error or "")
        ok_button.set_sensitive(error is None)

    name_entry.connect("changed", revalidate)
    command_entry.connect("changed", revalidate)
    argument_entry.connect("changed", revalidate)
    revalidate()

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


def show_manage_external_commands_dialog(parent: Gtk.Window) -> None:
    """The list dialog - faithful-in-spirit port of SettingsForm
    (SettingsForm.cs): configured commands with Add/Edit/Delete.
    Reached from EditorWindow's Preferences dialog (this port has no
    separate Plugins tab with its own "Configure" button for this to
    live behind - see REQUIREMENTS.md's Preferences dialog audit).
    """
    dialog = Gtk.Dialog(title="External Commands", transient_for=parent, modal=True)
    dialog.add_buttons(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
    dialog.set_default_size(360, 240)
    content = dialog.get_content_area()
    content.set_border_width(12)
    content.set_spacing(6)

    store = Gtk.ListStore(str)
    for command in get_external_commands():
        store.append([command.name])
    tree = Gtk.TreeView(model=store)
    tree.append_column(Gtk.TreeViewColumn("Name", Gtk.CellRendererText(), text=0))
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.set_vexpand(True)
    scroller.add(tree)
    content.pack_start(scroller, True, True, 0)

    button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    add_button = Gtk.Button(label="Add...")
    edit_button = Gtk.Button(label="Edit...")
    delete_button = Gtk.Button(label="Delete")
    edit_button.set_sensitive(False)
    delete_button.set_sensitive(False)
    for button in (add_button, edit_button, delete_button):
        button_row.pack_start(button, False, False, 0)
    content.pack_start(button_row, False, False, 0)

    def refresh() -> None:
        store.clear()
        for command in get_external_commands():
            store.append([command.name])

    def selected_command() -> ExternalCommand | None:
        model, tree_iter = tree.get_selection().get_selected()
        if tree_iter is None:
            return None
        name = model[tree_iter][0]
        return next((c for c in get_external_commands() if c.name == name), None)

    def on_selection_changed(_selection) -> None:
        has_selection = selected_command() is not None
        edit_button.set_sensitive(has_selection)
        delete_button.set_sensitive(has_selection)

    tree.get_selection().connect("changed", on_selection_changed)

    def on_add(_button) -> None:
        result = _show_command_detail_dialog(dialog, None)
        if result is not None:
            set_external_commands(get_external_commands() + [result])
            refresh()

    def on_edit(_button) -> None:
        current = selected_command()
        if current is None:
            return
        result = _show_command_detail_dialog(dialog, current)
        if result is not None:
            commands = [result if c.name == current.name else c for c in get_external_commands()]
            set_external_commands(commands)
            refresh()

    def on_delete(_button) -> None:
        current = selected_command()
        if current is None:
            return
        set_external_commands([c for c in get_external_commands() if c.name != current.name])
        refresh()

    add_button.connect("clicked", on_add)
    edit_button.connect("clicked", on_edit)
    delete_button.connect("clicked", on_delete)

    dialog.show_all()
    dialog.run()
    dialog.destroy()
