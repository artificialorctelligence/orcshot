"""BACKLOG #210: Gtk.FileChooserDialog never goes through the desktop
portal, so under Flatpak it browses the sandbox's private tmpfs and
returns paths the app cannot really write. Every file dialog is
Gtk.FileChooserNative (portal when sandboxed, plain GTK dialog
otherwise). This pins that no in-process chooser sneaks back in.
"""

from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "orcshot"


def test_no_gtk_file_chooser_dialog_anywhere():
    offenders = [
        f"{p.relative_to(SRC)}:{n}"
        for p in SRC.rglob("*.py")
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if "Gtk.FileChooserDialog(" in line
    ]
    assert offenders == []
