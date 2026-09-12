"""How Orcshot's GNOME Shell extension (or Cinnamon applet) gets installed
on each channel - spec 2026-09-11 §4 and §7. The app never writes into the
user's home on any channel: a sandboxed app is not allowed to put code
where the desktop shell loads it from (Snap Store: refused as a
confinement escape; Flathub: a home grant to review). So:

- .deb: the package installed it system-wide. Nothing to do.
- Flatpak on GNOME: ask GNOME to install it from extensions.gnome.org
  (InstallRemoteExtension; GNOME shows its own confirmation dialog).
  Exactly how Extension Manager on Flathub does it.
- Snap on GNOME: no snapd interface reaches GNOME's installer, so the
  dialog sends the user to extensions.gnome.org with explicit steps.
- Flatpak on Cinnamon: the tray applet lives on Cinnamon Spices; the
  dialog sends the user to System Settings -> Applets -> Download.
- Snap on Cinnamon: nothing (decided 2026-09-11: Mint blocks snapd).

Every dialog closes itself when the extension/applet says Hello. "Later"
leaves Orcshot fully usable on the portal path; the dialog comes back
through the editor's existing Setup... entry, which re-runs first-run
setup and therefore this.
"""

from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

from orcshot.capture.shell_bridge import get_bridge
from orcshot.i18n import _

EXTENSION_UUID = "orcshot@orcshot.org"
# Both URLs are replaced with the real listing pages once the first
# submissions are accepted (plan Task 9); the site roots work meanwhile.
EGO_URL = "https://extensions.gnome.org/"
SPICES_URL = "https://cinnamon-spices.linuxmint.com/applets/"


def plan_install(channel: str, desktop: str | None) -> str | None:
    if channel == "flatpak" and desktop == "gnome":
        return "flatpak-gnome"
    if channel == "flatpak" and desktop == "cinnamon":
        return "flatpak-cinnamon"
    if channel == "snap" and desktop == "gnome":
        return "snap-gnome"
    return None


def request_gnome_install(uuid: str, bus=None) -> str:
    """GNOME installs (and enables) the extension from EGO, behind its
    own 'Install extension?' dialog. Returns GNOME's result string
    ('successful' / 'cancelled'). The one org.gnome.Shell call left in
    the app: allowed because Flatpak grants --talk-name=org.gnome.Shell,
    and because it *asks* GNOME to act rather than acting itself."""
    bus = bus or Gio.bus_get_sync(Gio.BusType.SESSION, None)
    reply = bus.call_sync(
        "org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Extensions", "InstallRemoteExtension",
        GLib.Variant("(s)", (uuid,)), GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 120000, None,
    )
    return reply.unpack()[0]


# (title, body, action-button label, url-or-None). Spec §7, verbatim.
_TEXT = {
    "snap-gnome": (
        _("One more step for the tray icon and Wayland capture"),
        _(
            "Orcshot's tray icon, region selection and window picker on Wayland run inside GNOME Shell as an "
            "extension. Snap packages aren't allowed to install extensions, so this one comes from GNOME's own "
            "extension site.\n\n"
            "1. Click Open extensions.gnome.org below.\n"
            "2. On the Orcshot page, switch the toggle to ON.\n"
            "3. That's it — this window closes by itself when the extension is running.\n\n"
            "If the page says your browser needs the GNOME Shell integration add-on: install the add-on it "
            "links to, then on Ubuntu run  sudo apt install gnome-browser-connector  (or install Extension "
            "Manager from the Software app and search for Orcshot there). This is a one-time setup for any "
            "extension, not just Orcshot's.\n\n"
            "Without the extension Orcshot still works — captures use GNOME's screenshot service and there's "
            "no tray icon."
        ),
        _("Open extensions.gnome.org"),
        EGO_URL,
    ),
    "flatpak-gnome": (
        _("One more step for the tray icon and Wayland capture"),
        _(
            "Orcshot's tray icon, region selection and window picker on Wayland run inside GNOME Shell as an "
            "extension. Click Install extension and GNOME will ask you to confirm.\n\n"
            "Without it Orcshot still works — captures use GNOME's screenshot service and there's no tray icon."
        ),
        _("Install extension"),
        None,
    ),
    "flatpak-cinnamon": (
        _("One more step for the tray icon"),
        _(
            "Orcshot's tray icon on Cinnamon is an applet from Mint's applet library.\n\n"
            "1. Open System Settings → Applets.\n"
            "2. Choose the Download tab and search for Orcshot.\n"
            "3. Click the install arrow, then add it to your panel from the Manage tab.\n\n"
            "This window closes by itself when the applet is running. Without it Orcshot still works; there's "
            "just no tray icon."
        ),
        _("Open the Orcshot applet page"),
        SPICES_URL,
    ),
}


def show_install_dialog(plan: str, parent: Gtk.Window = None) -> None:
    title, body, action_label, url = _TEXT[plan]
    dialog = Gtk.Dialog(title=_("Orcshot Setup"), transient_for=parent)
    dialog.add_buttons(_("Later"), Gtk.ResponseType.CANCEL, action_label, Gtk.ResponseType.OK)
    box = dialog.get_content_area()
    heading = Gtk.Label(label=f"<b>{GLib.markup_escape_text(title)}</b>", use_markup=True, xalign=0)
    text = Gtk.Label(label=body, wrap=True, xalign=0, max_width_chars=70)
    for widget in (heading, text):
        widget.set_margin_start(12)
        widget.set_margin_end(12)
        widget.set_margin_top(8)
        box.add(widget)
    box.show_all()

    bridge = get_bridge()

    def on_capabilities(capabilities):
        # Hello arrived: the extension/applet is running. Done.
        if capabilities:
            dialog.response(Gtk.ResponseType.DELETE_EVENT)

    bridge.on_capabilities_changed(on_capabilities)

    def on_response(d, response):
        if response == Gtk.ResponseType.OK:
            if url is not None:
                # Through the desktop portal under both sandboxes.
                Gio.AppInfo.launch_default_for_uri(url, None)
                return  # stays open until Hello
            try:
                request_gnome_install(EXTENSION_UUID)
            except GLib.Error as error:
                text.set_text(body + "\n\n" + _("GNOME could not install it: %s") % error.message)
            return  # Hello closes it
        bridge.off_capabilities_changed(on_capabilities)
        d.destroy()

    dialog.connect("response", on_response)
    dialog.show()
