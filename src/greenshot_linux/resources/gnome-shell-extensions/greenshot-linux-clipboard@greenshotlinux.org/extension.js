/* extension.js
 *
 * Wholly original code written for the Greenshot Linux project - not
 * derived from or copied out of any other GNOME Shell extension or
 * GNOME Shell itself. It calls St.Clipboard - a public, documented
 * GNOME Shell extension API, the same one every extension (including
 * GNOME Shell's own built-in screenshot UI) uses - rather than porting
 * anyone else's implementation. Licensed under this project's own
 * license (GPL-3.0-or-later, see the repo's top-level LICENSE) rather
 * than a bundled/patched third-party license, since there is no
 * upstream project this is based on.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Why this exists (see REQUIREMENTS.md's "Clipboard under Wayland"
 * section for the full write-up): a wl_data_offer is only valid while
 * the claiming client has real Wayland keyboard focus, which an
 * ordinary background app's transient popup menu never gets. GNOME
 * Shell's own screenshot UI and GNOME's own extensions sidestep this
 * entirely by running *inside* the Shell/Mutter compositor process,
 * where St.Clipboard has privileged access not subject to that
 * per-client constraint - confirmed by reading GNOME Shell's own
 * screenshot.js and the (GPL-3.0) Gradia Capture extension, both of
 * which use exactly this API for exactly this reason. This extension
 * exposes that same privileged path over D-Bus so Greenshot Linux, an
 * ordinary Wayland client, can use it too - the reliable alternative
 * to (and preferred over, when available) the invisible-window/focus-
 * wait technique wayland_clipboard.py falls back to otherwise.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

const IFACE = `
<node>
   <interface name="org.gnome.Shell.Extensions.GreenshotClipboard">
      <method name="SetImage">
         <arg type="ay" direction="in" name="pngBytes" />
      </method>
      <method name="Ping">
         <arg type="b" direction="out" name="ok" />
      </method>
   </interface>
</node>`;

export default class Extension {
  enable() {
    this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
    this._dbus.export(Gio.DBus.session, '/org/gnome/Shell/Extensions/GreenshotClipboard');
  }

  disable() {
    this._dbus.flush();
    this._dbus.unexport();
    delete this._dbus;
  }

  SetImage(pngBytes) {
    const bytes = new GLib.Bytes(pngBytes);
    St.Clipboard.get_default().set_content(St.ClipboardType.CLIPBOARD, 'image/png', bytes);
  }

  // Availability probe only - deliberately does not touch the
  // clipboard. Greenshot Linux's own is_available() check needs a
  // real method call to distinguish "not installed/enabled" from "a
  // stale version whose SetImage signature changed", the same
  // reasoning window-calls' own is_available() uses - but probing
  // with SetImage itself would silently overwrite the user's real
  // clipboard just from checking availability, which happens before
  // the user has chosen to copy anything at all.
  Ping() {
    return true;
  }
}
