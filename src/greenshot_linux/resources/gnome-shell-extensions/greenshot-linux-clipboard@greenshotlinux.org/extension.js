/* extension.js
 *
 * Wholly original code written for the Greenshot Linux project - not
 * derived from or copied out of any other GNOME Shell extension or
 * GNOME Shell itself. It calls St.Clipboard and Shell.Screenshot -
 * public, documented GNOME Shell extension APIs, the same ones GNOME
 * Shell's own built-in screenshot UI uses - and GrabHelper, imported
 * from Shell's own resource path the same way any extension imports
 * Main - rather than porting anyone else's implementation. Licensed
 * under this project's own license (GPL-3.0-or-later, see the repo's
 * top-level LICENSE) rather than a bundled/patched third-party
 * license, since there is no upstream project this is based on.
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
 * Why the clipboard half exists (see REQUIREMENTS.md's "Clipboard
 * under Wayland" section for the full write-up): a wl_data_offer is
 * only valid while the claiming client has real Wayland keyboard
 * focus, which an ordinary background app's transient popup menu
 * never gets. GNOME Shell's own screenshot UI sidesteps this entirely
 * by running *inside* the Shell/Mutter compositor process, where
 * St.Clipboard has privileged access not subject to that per-client
 * constraint - confirmed by reading GNOME Shell's own screenshot.js
 * and the (GPL-3.0) Gradia Capture extension, both of which use
 * exactly this API for exactly this reason.
 *
 * Why the capture-overlay half exists (see REQUIREMENTS.md's
 * "Planned: Shell-side rewrite of the Wayland overlays" section for
 * the full write-up, task #77): this project's Wayland region-select/
 * window-picker/eyedropper overlays (task #68) are real, separate
 * Gtk.WindowType.TOPLEVEL client windows - confirmed live that Mutter
 * treats a real window mapping/unmapping as a normal lifecycle event
 * other Shell UI (the dock, at minimum) visibly reacts to. Read GNOME
 * Shell's own screenshot.js and confirmed its selection UI (and
 * Gradia Capture's, which hooks into the same native UI) never
 * creates a separate window at all - it's Clutter/St actors added
 * directly to Shell's own UI group. This overlay is built the same
 * way: no window, so nothing for other Shell UI to react to.
 */

import Cairo from 'cairo';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import { GrabHelper } from 'resource:///org/gnome/shell/ui/grabHelper.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

// Neither is promisified by default - GNOME Shell's own screenshot.js
// does these same two _promisify calls itself before awaiting either
// method, confirmed by reading that file (composite_to_stream is a
// static method, hence promisifying the class itself rather than
// .prototype, matching that file's own line 24 exactly).
Gio._promisify(Shell.Screenshot.prototype, 'screenshot_stage_to_content');
Gio._promisify(Shell.Screenshot, 'composite_to_stream');

// Two separate single-interface documents, not one <node> with both
// <interface> elements - confirmed against GJS's own source
// (modules/core/overrides/Gio.js) that Gio.DBusExportedObject.
// wrapJSObject() parses XML via Gio.DBusInterfaceInfo.new_for_xml(),
// which only picks up one interface per call; a combined multi-
// interface document silently dropped the second interface (caught
// live: gdbus introspect showed only GreenshotClipboard after
// deploying a combined-XML version - not assumed, observed).
const CLIPBOARD_IFACE = `
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

// StartRegionSelect now chains the whole selection-through-destination-
// choice interaction into one continuous Shell-side flow (drag-select,
// then immediately a native Shell popup menu for the destination) -
// see this file's own docstring (and REQUIREMENTS.md's Shell-side
// rewrite section) for why: a client-side Gtk.Menu popup here needs a
// real, recent input-event serial to be legitimately created at all
// under Wayland (a deliberate protocol-level anti-spoofing rule, not a
// GTK quirk), and nothing in the new Shell-side selection flow ever
// gives the Python client one - confirmed live: menu.get_visible()
// reported True on every attempt, yet only the very first ever
// actually took real compositor focus (has_toplevel_focus went False
// right after, matching a real popup grab; later attempts kept
// keyboard focus the whole time, meaning the popup was silently never
// really mapped). destination is one of "clipboard"/"save"/"save_as"/
// "edit"/"print", or "" if the user dismissed the picker without
// choosing (Escape/click-outside) - Python only ever executes the
// chosen action, no picker UI of its own for this flow at all anymore.
const CAPTURE_IFACE = `
<node>
   <interface name="org.gnome.Shell.Extensions.GreenshotCapture">
      <method name="StartRegionSelect">
         <arg type="b" direction="out" name="ok" />
         <arg type="s" direction="out" name="destination" />
         <arg type="ay" direction="out" name="pngBytes" />
         <arg type="i" direction="out" name="x" />
         <arg type="i" direction="out" name="y" />
         <arg type="i" direction="out" name="width" />
         <arg type="i" direction="out" name="height" />
      </method>
   </interface>
</node>`;

// Matches ui/region_select.py's own constants (_SELECTION_BORDER,
// _DIM_ALPHA) - see that module for the Windows-source citation these
// were originally traced from.
const _SELECTION_BORDER = [0.1, 0.6, 1.0];
const _DIM_ALPHA = 0.5;

// Matches ui/destination_picker.py's own item order/labels - see that
// module's docstring for the Windows-destination-priority citation
// these were traced from. destination_picker.py's own Gtk.Menu is no
// longer used for the Wayland/Shell-native flow at all (see
// pickDestinationAsync below for why) - Python only ever *dispatches*
// on whichever of these ids comes back, it doesn't build any menu UI
// of its own for this path anymore.
const DESTINATIONS = [
  ['clipboard', 'Copy to Clipboard'],
  ['save', 'Save'],
  ['save_as', 'Save As...'],
  ['edit', 'Edit'],
  ['print', 'Print'],
];

// Shows a native Shell popup menu (PopupMenu.PopupMenu - the same
// class Shell's own top-bar menus use) at stage coordinates (x, y),
// resolving with whichever destination id was chosen, or null if
// dismissed without choosing (Escape/click-outside - both handled
// automatically by PopupMenuManager, no custom code needed for that
// part, matching GrabHelper's own equivalent free behavior for the
// selection overlay above). Deliberately not a Gtk.Menu (see
// CAPTURE_IFACE's own comment for why that doesn't work reliably here
// at all past the first call) - PopupMenu needs a real sourceActor to
// anchor to rather than arbitrary coordinates (confirmed against
// GNOME Shell's own popupMenu.js), hence the tiny invisible St.Widget
// used purely as that anchor.
function pickDestinationAsync(x, y) {
  return new Promise(resolve => {
    const anchor = new St.Widget({ x, y, width: 1, height: 1, opacity: 0, reactive: false });
    Main.uiGroup.add_child(anchor);

    const menu = new PopupMenu.PopupMenu(anchor, 0, St.Side.TOP);
    Main.uiGroup.add_child(menu.actor);

    const manager = new PopupMenu.PopupMenuManager(anchor);
    manager.addMenu(menu);

    let chosen = null;
    for (const [id, label] of DESTINATIONS)
      menu.addAction(label, () => { chosen = id; });

    // Fires exactly once per open/close cycle regardless of *how* the
    // menu closed (item chosen - addAction's own default behavior
    // closes the menu on activation - Escape, or click-outside), so
    // this is the one place resolution and cleanup need to happen,
    // matching the same "resolve on however the interaction ends"
    // principle GrabHelper's own onUngrab callback uses above.
    menu.connect('open-state-changed', (_menu, isOpen) => {
      if (isOpen)
        return;
      menu.destroy();
      anchor.destroy();
      resolve(chosen);
    });

    menu.open(true);
  });
}

class RegionSelectOverlay extends St.Widget {
  static {
    GObject.registerClass(this);
  }

  constructor() {
    super({ visible: false, reactive: true, x: 0, y: 0 });
    Main.uiGroup.add_child(this);
    this.add_constraint(new Clutter.BindConstraint({
      source: global.stage,
      coordinate: Clutter.BindCoordinate.ALL,
    }));

    this._backdrop = new Clutter.Actor();
    this.add_child(this._backdrop);

    // Clutter.Canvas, used by GNOME Shell's own SelectArea reference
    // (js/ui/screenshot.js) in older Shell versions, does not exist
    // at all in this Shell's bundled Clutter fork - confirmed live by
    // introspecting Clutter-18.typelib directly (Object.keys(Clutter)
    // has no Canvas, only Content/TextureContent - a "Canvas is not a
    // constructor" TypeError was the first, wrong-guess symptom of
    // this). St.DrawingArea (get_context()/get_surface_size()/
    // queue_repaint(), a parameterless 'repaint' signal) is this
    // Shell version's real equivalent - confirmed the same way, via
    // GObject.signal_query() against the live St typelib, not assumed
    // from an older recollection.
    this._drawing = new St.DrawingArea();
    this._drawing.connect('repaint', this._onRepaint.bind(this));
    this.add_child(this._drawing);

    this._grabHelper = new GrabHelper(this);

    // Mirrors GNOME Shell's own SelectArea (js/ui/screenshot.js):
    // start point tracked separately from the latest point, geometry
    // derived from the two rather than accumulated deltas.
    this._startX = -1;
    this._startY = -1;
    this._lastX = 0;
    this._lastY = 0;
    this._result = null;

    this._panGesture = new Clutter.PanGesture();
    this._panGesture.set_begin_threshold(0);
    this._panGesture.connect('recognize', this._onPanBegin.bind(this));
    this._panGesture.connect('pan-update', this._onPanUpdate.bind(this));
    this._panGesture.connect('end', this._onPanEnd.bind(this));
    // Clutter.Gesture (PanGesture's base class) also has a 'cancel'
    // signal, confirmed live via GObject.signal_list_ids() - fires if
    // something else preempts the gesture mid-drag. Without handling
    // it, this._result stays null forever and the grab is never
    // released (only _onPanEnd calls ungrab()) - defense in depth
    // alongside the system-modal-opened fix above, matching how real
    // ScreenshotUI's grab always calls onUngrab/close() regardless of
    // *how* the grab ends, not only through its own success path.
    this._panGesture.connect('cancel', this._onPanEnd.bind(this));
    this.add_action(this._panGesture);

    this.set_cursor_type(Clutter.CursorType.CROSSHAIR);
  }

  async selectAsync() {
    const [content, scale] = await new Shell.Screenshot().screenshot_stage_to_content();
    this._backdrop.set_content(content);
    this._texture = content.get_texture();
    this._scale = scale;

    const [width, height] = [global.stage.width, global.stage.height];
    this._backdrop.set_size(width, height);
    this._drawing.set_size(width, height);
    this._drawing.queue_repaint();

    // Matches GNOME Shell's own ScreenshotUI.open() (js/ui/screenshot.js) -
    // without this, the dock and top bar can still steal a drag that ends
    // over them even though this overlay is raised above uiGroup's other
    // children, since they're independently-tracked chrome, not ordinary
    // uiGroup siblings. Confirmed live as the root cause of a real bug:
    // dragging a selection onto the dock silently dropped the whole
    // gesture (no 'end', no result, grab left dangling) and broke every
    // capture attempt afterward, since nothing had released the grab.
    // Real ScreenshotUI emits this before its own grab call for exactly
    // this reason ("Get rid of any popup menus... this needs to happen
    // before the grab below as closing menus will pop their grabs").
    Main.layoutManager.emit('system-modal-opened');

    Main.uiGroup.set_child_above_sibling(this, null);
    this.show();

    await this._grabHelper.grabAsync({ actor: this });

    // Hide the dim-select visuals as soon as the drag itself is done,
    // *before* the destination picker (chained below) even starts -
    // confirmed live as a real, separate bug otherwise: users saw the
    // whole screen still dimmed/blanked while waiting on the picker,
    // since destroy() alone was scheduled via idle_add_once and could
    // lag behind the picker appearing. Destroying happens once at the
    // very end (see below) instead, after the picker has resolved -
    // this only needs to stop being visible, not be gone yet.
    this.hide();

    if (this._result === null) {
      this.destroy();
      return null;
    }

    // Crop + PNG-encode directly from the same frozen backdrop already
    // captured above - same principle region_select.py's own docstring
    // states ("captures the whole virtual screen once up front...then
    // crops the final region from that same frozen copy rather than
    // re-grabbing"), now Shell-side. No cursor compositing here - the
    // Python side samples and places the auto-captured cursor itself
    // (core/cursor_capture.py), unchanged by this rewrite.
    const stream = Gio.MemoryOutputStream.new_resizable();
    const { x, y, width: w, height: h } = this._result;
    await Shell.Screenshot.composite_to_stream(
      this._texture, x, y, w, h, this._scale,
      null, 0, 0, 1,
      stream);
    stream.close(null);
    const pngBytes = stream.steal_as_bytes().toArray();

    // Chained directly here, in the same continuous Shell-side
    // interaction, rather than returning to Python in between - see
    // pickDestinationAsync's own docstring for why a client-side
    // Gtk.Menu can't reliably do this part at all past the very first
    // capture. Anchored at the release point (_lastX/_lastY), still
    // known here since this actor isn't destroyed until just below.
    const destination = await pickDestinationAsync(this._lastX, this._lastY);
    this.destroy();

    if (destination === null)
      return null;

    return { ...this._result, pngBytes, destination };
  }

  _getGeometry() {
    return {
      x: Math.min(this._startX, this._lastX),
      y: Math.min(this._startY, this._lastY),
      width: Math.abs(this._startX - this._lastX),
      height: Math.abs(this._startY - this._lastY),
    };
  }

  _onPanBegin() {
    if (this._result)
      return;
    const coords = this._panGesture.get_centroid_abs();
    this._startX = Math.floor(coords.x);
    this._startY = Math.floor(coords.y);
    this._lastX = this._startX;
    this._lastY = this._startY;
    this._drawing.queue_repaint();
  }

  _onPanUpdate() {
    if (this._result)
      return;
    const coords = this._panGesture.get_centroid_abs();
    this._lastX = Math.floor(coords.x);
    this._lastY = Math.floor(coords.y);
    this._drawing.queue_repaint();
  }

  _onPanEnd() {
    if (this._result)
      return;
    const geometry = this._getGeometry();
    this._result = geometry.width > 0 && geometry.height > 0 ? geometry : null;
    this._grabHelper.ungrab();
  }

  _onRepaint(area) {
    const cr = area.get_context();
    const [width, height] = area.get_surface_size();
    cr.setOperator(Cairo.Operator.CLEAR);
    cr.paint();
    cr.setOperator(Cairo.Operator.OVER);

    cr.setSourceRGBA(0, 0, 0, _DIM_ALPHA);
    if (this._startX >= 0) {
      const { x: sx, y: sy, width: sw, height: sh } = this._getGeometry();
      cr.setFillRule(Cairo.FillRule.EVEN_ODD);
      cr.rectangle(0, 0, width, height);
      cr.rectangle(sx, sy, sw, sh);
      cr.fill();

      cr.setSourceRGB(..._SELECTION_BORDER);
      cr.setLineWidth(1);
      cr.rectangle(sx + 0.5, sy + 0.5, sw - 1, sh - 1);
      cr.stroke();
    } else {
      cr.rectangle(0, 0, width, height);
      cr.fill();
    }
    cr.$dispose();
  }
}

export default class Extension {
  // Two separate exported objects at two separate paths - tried a
  // single combined multi-<interface> document first (wrong, GJS only
  // parses one interface per wrapJSObject call - see CAPTURE_IFACE's
  // comment), then tried two single-interface exports at the *same*
  // path (also wrong: confirmed live that a second .export() call to
  // an already-exported path is silently a no-op - `gdbus call`
  // against GreenshotCapture at the shared path came back "No such
  // interface", with enable() itself reporting no error either way).
  // Two distinct paths sidesteps whatever that limitation is entirely.
  enable() {
    this._dbus = Gio.DBusExportedObject.wrapJSObject(CLIPBOARD_IFACE, this);
    this._dbus.export(Gio.DBus.session, '/org/gnome/Shell/Extensions/GreenshotClipboard');
    this._captureDbus = Gio.DBusExportedObject.wrapJSObject(CAPTURE_IFACE, this);
    this._captureDbus.export(Gio.DBus.session, '/org/gnome/Shell/Extensions/GreenshotCapture');
  }

  disable() {
    this._dbus.flush();
    this._dbus.unexport();
    delete this._dbus;
    this._captureDbus.flush();
    this._captureDbus.unexport();
    delete this._captureDbus;
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

  // async method name (matching the D-Bus method name exactly, no
  // "Async" suffix needed) - GJS's Gio.DBusExportedObject dispatch
  // auto-detects a returned Promise and defers the reply until it
  // resolves, confirmed by reading GJS's own overrides/Gio.js
  // (_handleMethodCall's retval?.then?.(...) branch), rather than
  // assumed from documentation, which doesn't cover this.
  async StartRegionSelect() {
    const overlay = new RegionSelectOverlay();
    const result = await overlay.selectAsync();
    if (result === null)
      return [false, '', [], 0, 0, 0, 0];
    return [true, result.destination, result.pngBytes, result.x, result.y, result.width, result.height];
  }
}
