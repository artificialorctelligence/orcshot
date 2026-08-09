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
// StartWindowPicker follows the exact same shape/reasoning as
// StartRegionSelect above (see that method's own comment) - same
// reply tuple, same reused pickDestinationAsync for the destination
// choice, same reasons a client-side Gtk.Menu can't do that part.
//
// CaptureRect has no gesture/overlay of its own, unlike the two
// methods above (task #73), used by ui/capture_modes.py's full-screen/
// active-window/last-region-repeat capture in place of the XDG portal
// round trip those three still used even after task #77's rewrite
// (they never needed an interactive overlay, so #77 didn't touch
// them) - but it *does* chain into pickDestinationAsync just like
// StartRegionSelect/StartWindowPicker do, anchored at the current
// pointer position (no drag-release/click point to anchor at instead,
// since there's no gesture here). Two real, separate artifacts of the
// old ui/destination_picker.py Gtk.Menu path motivated folding the
// picker in here too, not just the pixel grab, both confirmed live:
// xdg-desktop-portal-gnome's own audible camera-shutter feedback on
// the portal's Screenshot() method (Shell.Screenshot, used here
// exactly as the overlays above already use it, has none), and even
// after switching only the pixel grab, the Gtk.Menu itself - a real
// client-side window - still caused a brief dock/taskbar flash under
// this Wayland session, the same class of artifact task #76/#77
// already eliminated for region-select/window-picker this same way.
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
      <method name="StartWindowPicker">
         <arg type="b" direction="out" name="ok" />
         <arg type="s" direction="out" name="destination" />
         <arg type="ay" direction="out" name="pngBytes" />
         <arg type="i" direction="out" name="x" />
         <arg type="i" direction="out" name="y" />
         <arg type="i" direction="out" name="width" />
         <arg type="i" direction="out" name="height" />
      </method>
      <method name="StartEyedropper">
         <arg type="b" direction="out" name="ok" />
         <arg type="y" direction="out" name="r" />
         <arg type="y" direction="out" name="g" />
         <arg type="y" direction="out" name="b" />
         <arg type="y" direction="out" name="a" />
      </method>
      <method name="CaptureRect">
         <arg type="i" direction="in" name="x" />
         <arg type="i" direction="in" name="y" />
         <arg type="i" direction="in" name="width" />
         <arg type="i" direction="in" name="height" />
         <arg type="b" direction="out" name="ok" />
         <arg type="s" direction="out" name="destination" />
         <arg type="ay" direction="out" name="pngBytes" />
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

// Real window geometry/content, not the bundled window-calls
// extension's own D-Bus interface - worth checking during
// implementation, per REQUIREMENTS.md's own open question, now that
// this caller is Shell-side too: `global.get_window_actors()`/
// `Meta.Window` gives this directly, no separate extension or D-Bus
// round trip needed at all for enumeration or activation.
class WindowPickerOverlay extends St.Widget {
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

    this._drawing = new St.DrawingArea();
    this._drawing.connect('repaint', this._onRepaint.bind(this));
    this.add_child(this._drawing);

    this._grabHelper = new GrabHelper(this);
    this._windows = [];
    this._hovered = null;
    this._result = null;

    // Plain Clutter.Actor signals, not a Gesture object - hover
    // tracking isn't a drag/pan, just "where is the pointer and was
    // there a click", confirmed real signals via GObject.signal_list_ids()
    // against the live Clutter typelib before relying on them (same
    // discipline as everything else built tonight - Clutter.Canvas's
    // absence was found exactly this way, not assumed from an older
    // recollection).
    this.connect('motion-event', this._onMotion.bind(this));
    this.connect('button-press-event', this._onButtonPress.bind(this));
  }

  _enumerateWindows() {
    // Mirrors ui/window_picker.py's own filtering intent (skip
    // minimized, skip windows that shouldn't be pickable) using
    // Shell's own native window model directly. global.get_window_
    // actors() is documented (and confirmed via GNOME Shell's own
    // screenshot.js UIWindowSelector.capture(), which enumerates the
    // exact same way) to return actors in bottom-to-top stacking
    // order, matching the "last match wins" hover contract this
    // project's X11/WaylandWindowPicker implementations already rely
    // on (see ui/window_picker.py's own docstring for the stacking-
    // order bug that contract was written to prevent).
    const workspaceManager = global.workspace_manager;
    const activeWorkspace = workspaceManager.get_active_workspace();
    const windows = [];
    for (const actor of global.get_window_actors()) {
      const metaWindow = actor.meta_window;
      if (!metaWindow || metaWindow.is_override_redirect())
        continue;
      if (!metaWindow.located_on_workspace(activeWorkspace))
        continue;
      if (metaWindow.minimized)
        continue;
      windows.push({ metaWindow, rect: metaWindow.get_frame_rect() });
    }
    return windows;
  }

  async selectAsync() {
    const [content, scale] = await new Shell.Screenshot().screenshot_stage_to_content();
    this._backdrop.set_content(content);

    const [width, height] = [global.stage.width, global.stage.height];
    this._backdrop.set_size(width, height);
    this._drawing.set_size(width, height);
    this._drawing.queue_repaint();

    this._windows = this._enumerateWindows();

    Main.layoutManager.emit('system-modal-opened');
    Main.uiGroup.set_child_above_sibling(this, null);
    this.show();

    await this._grabHelper.grabAsync({ actor: this });
    this.hide();

    if (this._result === null) {
      this.destroy();
      return null;
    }

    // Raise/focus the picked window, then take a *fresh* stage
    // screenshot before cropping to its frame rect - matches the
    // reasoning ui/window_picker_wayland.py's own docstring documents
    // (the initial backdrop may show a since-occluded window's stale
    // content, if another window was on top of it at capture time),
    // but entirely synchronous and Shell-side, with none of the
    // reentrancy hazards that forced that Python implementation to
    // defer the equivalent step to menu-item-click time instead (see
    // destination_picker.py's refresh_image docstring for that story)
    // - no portal, no cross-process D-Bus round trip, no nested
    // GLib.MainLoop risk exists in this path at all.
    //
    // The restack itself is NOT instantaneous, though - confirmed live
    // as a real bug: capturing immediately after activate() still
    // returned a mix of the target window's own (stale) pixels and
    // whatever had been on top of it, meaning the fresh screenshot was
    // taken before the raise actually took visual effect. Same root
    // cause ui/window_picker_wayland.py's own docstring already
    // documented for its X11/portal equivalent ("the raise genuinely
    // happens, just too fast to perceive... 0.15s") - that empirically-
    // verified delay is reused here rather than re-derived, since
    // there's no Shell-side signal to wait on instead (no 'restacked'-
    // style event fires synchronously with the actual compositor
    // repaint that matters here).
    const metaWindow = this._result;
    metaWindow.activate(global.get_current_time());
    await new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, 150, () => {
      resolve();
      return GLib.SOURCE_REMOVE;
    }));
    const [freshContent, freshScale] = await new Shell.Screenshot().screenshot_stage_to_content();
    const freshTexture = freshContent.get_texture();

    const rect = metaWindow.get_frame_rect();
    const stream = Gio.MemoryOutputStream.new_resizable();
    await Shell.Screenshot.composite_to_stream(
      freshTexture, rect.x, rect.y, rect.width, rect.height, freshScale,
      null, 0, 0, 1,
      stream);
    stream.close(null);
    const pngBytes = stream.steal_as_bytes().toArray();

    const destination = await pickDestinationAsync(rect.x, rect.y);
    this.destroy();

    if (destination === null)
      return null;

    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, pngBytes, destination };
  }

  _windowAt(x, y) {
    let match = null;
    for (const w of this._windows) {
      const r = w.rect;
      if (x >= r.x && x < r.x + r.width && y >= r.y && y < r.y + r.height)
        match = w;
    }
    return match;
  }

  _onMotion(_actor, event) {
    if (this._result !== null)
      return Clutter.EVENT_PROPAGATE;
    const [x, y] = event.get_coords();
    const hovered = this._windowAt(x, y);
    if (hovered !== this._hovered) {
      this._hovered = hovered;
      this._drawing.queue_repaint();
    }
    return Clutter.EVENT_PROPAGATE;
  }

  _onButtonPress(_actor, _event) {
    if (this._result !== null)
      return Clutter.EVENT_PROPAGATE;
    // Clicking where no window is cancels - matches ui/window_picker.py
    // and ui/window_picker_wayland.py's own documented contract.
    this._result = this._hovered !== null ? this._hovered.metaWindow : null;
    this._grabHelper.ungrab();
    return Clutter.EVENT_STOP;
  }

  _onRepaint(area) {
    const cr = area.get_context();
    const [width, height] = area.get_surface_size();
    cr.setOperator(Cairo.Operator.CLEAR);
    cr.paint();
    cr.setOperator(Cairo.Operator.OVER);

    cr.setSourceRGBA(0, 0, 0, _DIM_ALPHA);
    if (this._hovered !== null) {
      const r = this._hovered.rect;
      cr.setFillRule(Cairo.FillRule.EVEN_ODD);
      cr.rectangle(0, 0, width, height);
      cr.rectangle(r.x, r.y, r.width, r.height);
      cr.fill();

      cr.setSourceRGB(..._SELECTION_BORDER);
      cr.setLineWidth(2);
      cr.rectangle(r.x + 1, r.y + 1, r.width - 2, r.height - 2);
      cr.stroke();
    } else {
      cr.rectangle(0, 0, width, height);
      cr.fill();
    }
    cr.$dispose();
  }
}

// Matches ui/eyedropper.py's own constants exactly (_PATCH_SIZE,
// _LOUPE_DIAMETER, _LOUPE_OFFSET) and ui/magnifier.py's rendering
// constants (_RING_WIDTH, _CROSSHAIR_GAP, _CROSSHAIR_THICKNESS) - see
// those modules' docstrings for the Windows CaptureForm.cs/DrawZoom
// citations these were traced from.
const _PATCH_SIZE = 25;
const _LOUPE_DIAMETER = 80;
const _LOUPE_OFFSET_X = 18;
const _LOUPE_OFFSET_Y = 18;
const _RING_WIDTH = 2;
const _CROSSHAIR_GAP = 6;
const _CROSSHAIR_THICKNESS = 2;

// Pick-a-color-from-anywhere-on-screen tool, Shell-side counterpart to
// ui/eyedropper.py/eyedropper_wayland.py. No destination picker here
// at all - unlike region-select/window-picker, the only result is a
// single sampled colour, handed straight back to the caller (the
// colour dialog).
//
// Cairo.ImageSurface.createForData() does not exist in this GJS
// binding at all (confirmed live: undefined, unlike pycairo's own
// API), and createFromPNG() only accepts a filename, not a stream or
// bytes (confirmed live: "Couldn't convert to filename" against a
// Gio.MemoryInputStream) - ruling out both of the more direct ways
// region_select.py's own numpy_to_cairo_surface gets a Cairo surface
// from raw pixel bytes in Python. The real path here: Shell.
// Screenshot.composite_to_stream() already hands back a decoded
// GdkPixbuf.Pixbuf directly (not just the PNG bytes written to its
// stream argument - confirmed live reading GNOME Shell's own
// screenshot.js), and GdkPixbuf.Pixbuf.get_pixels() returns a real,
// correctly-indexable Uint8Array (confirmed live) - so the magnified
// preview is drawn one source pixel at a time, each as its own filled
// Cairo rectangle scaled up to the destination size (manual nearest-
// neighbour scaling), rather than via a Cairo surface pattern the way
// the Python version does it.
class EyedropperOverlay extends St.Widget {
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

    this._drawing = new St.DrawingArea();
    this._drawing.connect('repaint', this._onRepaint.bind(this));
    this.add_child(this._drawing);

    this._grabHelper = new GrabHelper(this);
    this._dragging = false;
    this._cursorX = 0;
    this._cursorY = 0;
    this._patchPixbuf = null;
    this._patchOrigin = null;
    this._currentColor = null;
    this._result = null;

    // Same signals as RegionSelectOverlay's PanGesture, for the same
    // reasons (recognize/pan-update/end/cancel) - here every pan-
    // update matters (a continuous sample-as-you-drag gesture), not
    // just the start/end points, matching ui/eyedropper.py's own
    // press-drag-release contract exactly (a single click with no
    // drag at all still counts as a valid pick, sampled at press).
    this._panGesture = new Clutter.PanGesture();
    this._panGesture.set_begin_threshold(0);
    this._panGesture.connect('recognize', this._onPanBegin.bind(this));
    this._panGesture.connect('pan-update', this._onPanUpdate.bind(this));
    this._panGesture.connect('end', this._onPanEnd.bind(this));
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

    Main.layoutManager.emit('system-modal-opened');
    Main.uiGroup.set_child_above_sibling(this, null);
    this.show();

    await this._grabHelper.grabAsync({ actor: this });
    this.destroy();

    return this._result;
  }

  async _sample(x, y) {
    this._cursorX = x;
    this._cursorY = y;

    const half = Math.floor(_PATCH_SIZE / 2);
    const stageWidth = global.stage.width;
    const stageHeight = global.stage.height;
    const left = Math.max(0, Math.min(Math.round(x) - half, stageWidth - _PATCH_SIZE));
    const top = Math.max(0, Math.min(Math.round(y) - half, stageHeight - _PATCH_SIZE));

    const stream = Gio.MemoryOutputStream.new_resizable();
    const pixbuf = await Shell.Screenshot.composite_to_stream(
      this._texture, left, top, _PATCH_SIZE, _PATCH_SIZE, this._scale,
      null, 0, 0, 1,
      stream);
    stream.close(null);

    this._patchPixbuf = pixbuf;
    this._patchOrigin = { x: left, y: top };
    this._currentColor = this._pixelAt(pixbuf, Math.round(x) - left, Math.round(y) - top);
    this._drawing.queue_repaint();
  }

  _pixelAt(pixbuf, px, py) {
    const pixels = pixbuf.get_pixels();
    const rowstride = pixbuf.get_rowstride();
    const channels = pixbuf.get_n_channels();
    const i = py * rowstride + px * channels;
    const a = channels === 4 ? pixels[i + 3] : 255;
    return [pixels[i], pixels[i + 1], pixels[i + 2], a];
  }

  _onPanBegin() {
    if (this._result !== null)
      return;
    this._dragging = true;
    const coords = this._panGesture.get_centroid_abs();
    this._sample(coords.x, coords.y).catch(e => logError(e));
  }

  _onPanUpdate() {
    if (this._result !== null || !this._dragging)
      return;
    const coords = this._panGesture.get_centroid_abs();
    this._sample(coords.x, coords.y).catch(e => logError(e));
  }

  _onPanEnd() {
    if (this._result !== null)
      return;
    this._dragging = false;
    // this._currentColor is null if _sample() never resolved even
    // once (e.g. an extremely fast click-release before the first
    // composite_to_stream() call finished) - treated as a cancel, same
    // as ui/eyedropper_wayland.py's own _on_button_release contract.
    this._result = this._currentColor;
    this._grabHelper.ungrab();
  }

  _onRepaint(area) {
    const cr = area.get_context();
    const [width, height] = area.get_surface_size();
    cr.setOperator(Cairo.Operator.CLEAR);
    cr.paint();
    cr.setOperator(Cairo.Operator.OVER);
    if (this._patchPixbuf !== null) {
      try {
        this._drawLoupe(cr);
      } catch (e) {
        logError(e, 'Error drawing eyedropper loupe');
      }
    }
    cr.$dispose();
  }

  _drawLoupe(cr) {
    const pixbuf = this._patchPixbuf;
    const pixels = pixbuf.get_pixels();
    const rowstride = pixbuf.get_rowstride();
    const channels = pixbuf.get_n_channels();
    const patchWidth = pixbuf.get_width();
    const patchHeight = pixbuf.get_height();

    const destX = this._cursorX + _LOUPE_OFFSET_X;
    const destY = this._cursorY + _LOUPE_OFFSET_Y;
    const radius = _LOUPE_DIAMETER / 2;
    const centerX = destX + radius;
    const centerY = destY + radius;
    const scaleX = _LOUPE_DIAMETER / patchWidth;
    const scaleY = _LOUPE_DIAMETER / patchHeight;

    cr.save();
    cr.arc(centerX, centerY, radius, 0, 2 * Math.PI);
    cr.clip();
    for (let py = 0; py < patchHeight; py++) {
      for (let px = 0; px < patchWidth; px++) {
        const i = py * rowstride + px * channels;
        const a = channels === 4 ? pixels[i + 3] / 255 : 1;
        cr.setSourceRGBA(pixels[i] / 255, pixels[i + 1] / 255, pixels[i + 2] / 255, a);
        cr.rectangle(destX + px * scaleX, destY + py * scaleY, scaleX + 0.5, scaleY + 0.5);
        cr.fill();
      }
    }
    cr.restore();

    cr.save();
    cr.setLineWidth(_RING_WIDTH);
    cr.setSourceRGB(1, 1, 1);
    cr.arc(centerX, centerY, radius - _RING_WIDTH / 2, 0, 2 * Math.PI);
    cr.stroke();
    cr.restore();

    // Crosshair at the cursor's own pixel within the zoomed preview -
    // matches ui/magnifier.py's draw_magnifier exactly (a small gap at
    // the middle, outlined in white for contrast).
    const cursorInPatchX = this._cursorX - this._patchOrigin.x;
    const cursorInPatchY = this._cursorY - this._patchOrigin.y;
    const crossX = destX + (cursorInPatchX + 0.5) * scaleX;
    const crossY = destY + (cursorInPatchY + 0.5) * scaleY;
    const arm = radius * 0.7;
    const gap = _CROSSHAIR_GAP;
    cr.save();
    cr.arc(centerX, centerY, radius - _RING_WIDTH, 0, 2 * Math.PI);
    cr.clip();
    for (const [lineWidth, r, g, b] of [[_CROSSHAIR_THICKNESS + 2, 1, 1, 1], [_CROSSHAIR_THICKNESS, 0, 0, 0]]) {
      cr.setLineWidth(lineWidth);
      cr.setSourceRGB(r, g, b);
      cr.moveTo(crossX, crossY - arm);
      cr.lineTo(crossX, crossY - gap);
      cr.moveTo(crossX, crossY + gap);
      cr.lineTo(crossX, crossY + arm);
      cr.moveTo(crossX - arm, crossY);
      cr.lineTo(crossX - gap, crossY);
      cr.moveTo(crossX + gap, crossY);
      cr.lineTo(crossX + arm, crossY);
      cr.stroke();
    }
    cr.restore();

    if (this._currentColor !== null) {
      const [r, g, b] = this._currentColor;
      const hex = n => n.toString(16).padStart(2, '0').toUpperCase();
      const text = `#${hex(r)}${hex(g)}${hex(b)}`;
      const labelX = destX;
      const labelY = destY + _LOUPE_DIAMETER + 4;
      cr.save();
      cr.selectFontFace('sans-serif', Cairo.FontSlant.NORMAL, Cairo.FontWeight.NORMAL);
      cr.setFontSize(13);
      const extents = cr.textExtents(text);
      const pad = 4;
      cr.setSourceRGBA(0, 0, 0, 0.75);
      cr.rectangle(labelX - pad, labelY - extents.height - pad, extents.width + 2 * pad, extents.height + 2 * pad);
      cr.fill();
      cr.setSourceRGB(1, 1, 1);
      cr.moveTo(labelX, labelY);
      cr.showText(text);
      cr.restore();
    }
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

  async StartWindowPicker() {
    const overlay = new WindowPickerOverlay();
    const result = await overlay.selectAsync();
    if (result === null)
      return [false, '', [], 0, 0, 0, 0];
    return [true, result.destination, result.pngBytes, result.x, result.y, result.width, result.height];
  }

  async StartEyedropper() {
    const overlay = new EyedropperOverlay();
    const result = await overlay.selectAsync();
    if (result === null)
      return [false, 0, 0, 0, 0];
    const [r, g, b, a] = result;
    return [true, r, g, b, a];
  }

  // No overlay actor/grab/gesture of its own, unlike the interactive
  // methods above - just a single frozen stage screenshot cropped to
  // the given rect (same primitive RegionSelectOverlay/
  // WindowPickerOverlay already use for their own final crop), then
  // straight into the same pickDestinationAsync those two use, see
  // CAPTURE_IFACE's own comment for why. Genuinely async from the
  // D-Bus caller's own point of view now that a destination choice is
  // part of the round trip (see gnome_capture_rect.py's docstring).
  async CaptureRect(x, y, width, height) {
    try {
      const [content, scale] = await new Shell.Screenshot().screenshot_stage_to_content();
      const texture = content.get_texture();
      const stream = Gio.MemoryOutputStream.new_resizable();
      await Shell.Screenshot.composite_to_stream(
        texture, x, y, width, height, scale,
        null, 0, 0, 1,
        stream);
      stream.close(null);
      const pngBytes = stream.steal_as_bytes().toArray();

      const [pointerX, pointerY] = global.get_pointer();
      const destination = await pickDestinationAsync(pointerX, pointerY);
      if (destination === null)
        return [false, '', []];
      return [true, destination, pngBytes];
    } catch (e) {
      logError(e, 'Error in CaptureRect');
      return [false, '', []];
    }
  }
}
