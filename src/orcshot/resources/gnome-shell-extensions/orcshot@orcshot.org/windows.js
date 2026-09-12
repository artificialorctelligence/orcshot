/* extension.js
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 2 of the License, or
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
 * SPDX-License-Identifier: GPL-2.0-or-later
 *
 * --- Modified by the Orcshot project (2026-08-04) ---
 * Original source: https://github.com/ickyicky/window-calls
 * Changes from upstream, redistributed here under the same license:
 *   1. _get_window_by_wid(): fixed a ReferenceError - the not-found
 *      check referenced `w` (only in scope inside the .find() callback
 *      that produced `win`) instead of `win`, which made Details,
 *      GetTitle, Activate, and every other method using this helper
 *      throw unconditionally.
 *   2. List(): 'width'/'height'/'x'/'y' were requested via
 *      get_width()/get_height()/get_x()/get_y(), which aren't real
 *      Meta.Window methods, so they always came back null/undefined.
 *      Replaced with get_frame_rect(), the same approach Details()
 *      already used correctly.
 *   3. List(): added 'minimized' to the returned fields, needed by
 *      Orcshot's window-picker to exclude iconified windows
 *      from its hover list without an extra per-window Details() call.
 *   4. Activate(): added an explicit win.raise() call.
 *      activate_with_focus()/activate() alone grant input focus but
 *      Mutter does not treat that as implying a stacking-order raise -
 *      confirmed live, the target window kept its keyboard focus but
 *      stayed visually behind another window until raise() was added.
 * ---
 */

// --- Modified by the Orcshot project (2026-09-11) ---
//   5. No D-Bus interface of its own any more: this is a module of the
//      merged orcshot@orcshot.org extension, and the app asks for
//      List/Activate through extension.js's request loop (spec
//      docs/superpowers/specs/2026-09-11-snap-compliant-extension-delivery-design.md).
//      The method bodies below are unchanged from change 4.


class WindowCalls {
  _get_window_by_wid(winid) {
    let win = global.get_window_actors().find(w => w.meta_window.get_id() == winid);

    if (!win) {
      throw new Error('winid not found');
    }

    return win;
  }

  Details(winid) {
    const w = this._get_window_by_wid(winid);

    const workspaceManager = global.workspace_manager;
    const currentmonitor = global.display.get_current_monitor();
    // const monitor = global.display.get_monitor_geometry(currentmonitor);

    const props = {
      get: ['wm_class', 'wm_class_instance', 'pid', 'id', 'maximized', 'display', 'frame_type', 'window_type', 'layer', 'monitor', 'role', 'title'],
      can: ['close', 'maximize', 'minimize'],
      has: ['focus'],
      booleans: ['fullscreen', 'minimized', 'maximized_horizontally', 'maximized_vertically'],
      custom: new Map([
        ['moveable', 'allows_move'],
        ['resizeable', 'allows_resize'],
        ['area', 'get_work_area_current_monitor'],
        ['area_all', 'get_work_area_all_monitors'],
        ['canclose', 'can_close'],
        ['canmaximize', 'can_maximize'],
        ['canminimize', 'can_minimize'],
        ['canshade', 'can_shade'],
      ]),
      frame: ['x', 'y', 'width', 'height']
    };

    const win = {
      in_current_workspace: w.meta_window.located_on_workspace?.(workspaceManager.get_active_workspace?.()),
      area_cust: w.meta_window.get_work_area_for_monitor?.(currentmonitor)
    };

    props.get.forEach(name => win[name] = w.meta_window[`get_${name}`]?.());
    props.booleans.forEach(name => win[name] = w.meta_window[name]);
    props.can.forEach(name => win[`can${name}`] = w.meta_window[`can_${name}`]?.());
    props.has.forEach(name => win[name] = w.meta_window[`has_${name}`]?.());
    props.custom.forEach((fname, name) => { win[name] = w.meta_window[fname]?.() });
    let frame = w.meta_window.get_frame_rect();
    props.frame.forEach(name => win[name] = frame[name]);
    
    return JSON.stringify(win);
  }

  List() {
    const win = global.get_window_actors();
    const workspaceManager = global.workspace_manager;

    const props = {
      get: ['wm_class', 'wm_class_instance', 'title', 'pid', 'id', 'frame_type', 'window_type'],
      has: ['focus'],
      booleans: ['minimized'],
      // custom: new Map([])
    };

    const winJsonArr = win.map(w => {
      const ws = w.meta_window.get_workspace();
      // The default is -1 in case the get_workspace() call fails
      let ws_index = -1;
      if (ws) {
        ws_index = ws.index();
      }

      const win = {
        in_current_workspace: w.meta_window.located_on_workspace?.(workspaceManager.get_active_workspace?.()),
        workspace: ws_index
      };
      props.get.forEach(name => win[name] = w.meta_window[`get_${name}`]?.());
      props.has.forEach(name => win[name] = w.meta_window[`has_${name}`]?.());
      props.booleans.forEach(name => win[name] = w.meta_window[name]);
      // props.custom.forEach((fname, name) => { win[name] = w.meta_window[fname]?.() });
      // 'width'/'height'/'x'/'y' aren't real per-axis get_* methods on
      // Meta.Window (that's why they came back null) - real geometry
      // comes from get_frame_rect(), same as Details() already does.
      const frame = w.meta_window.get_frame_rect();
      win.x = frame.x;
      win.y = frame.y;
      win.width = frame.width;
      win.height = frame.height;
      return win;
    });

    return JSON.stringify(winJsonArr);
  }

  GetFrameBounds(winid) {
    let w = this._get_window_by_wid(winid);
    const result = {
      frame_bounds: w.meta_window.get_frame_bounds(),
    }
    return JSON.stringify(result);
  }

  GetFrameRect(winid) {
    let w = this._get_window_by_wid(winid);
    let frame = w.meta_window.get_frame_rect()
    const result = {
      "x": frame.x,
      "y": frame.y,
      "width": frame.width,
      "height": frame.height
    }
    return JSON.stringify(result);
  }

  GetTitle(winid) {
    let w = this._get_window_by_wid(winid);
    return w.meta_window.get_title();
  }

  MoveToWorkspace(winid, workspaceNum) {
    let win = this._get_window_by_wid(winid).meta_window;
    win.change_workspace_by_index(workspaceNum, false);
  }

  MoveResize(winid, x, y, width, height) {
    let win = this._get_window_by_wid(winid);

    if (win.meta_window.maximized_horizontally || win.meta_window.maximized_vertically) {
      win.meta_window.unmaximize(3);
    }

    win.meta_window.move_resize_frame(1, x, y, width, height);
  }

  Resize(winid, width, height) {
    let win = this._get_window_by_wid(winid);
    if (win.meta_window.maximized_horizontally || win.meta_window.maximized_vertically) {
      win.meta_window.unmaximize(3);
    }
    win.meta_window.move_resize_frame(1, win.get_x(), win.get_y(), width, height);
  }

  Move(winid, x, y) {
    let win = this._get_window_by_wid(winid);
    if (win.meta_window.maximized_horizontally || win.meta_window.maximized_vertically) {
      win.meta_window.unmaximize(3);
    }
    win.meta_window.move_frame(1, x, y);
  }

  MakeFullscreen(winid) {
    let win = this._get_window_by_wid(winid).meta_window;
    win.make_fullscreen();
  }

  Maximize(winid) {
    let win = this._get_window_by_wid(winid).meta_window;
    win.maximize(3);
  }

  Minimize(winid) {
    let win = this._get_window_by_wid(winid).meta_window;
    win.minimize();
  }

  Unmaximize(winid) {
    let win = this._get_window_by_wid(winid).meta_window;
    win.unmaximize(3);
  }

  Unminimize(winid) {
    let win = this._get_window_by_wid(winid).meta_window;
    win.unminimize();
  }

  Activate(winid) {
    const win = this._get_window_by_wid(winid).meta_window;
    // activate_with_focus()/activate() alone grant input focus but not
    // necessarily a stacking-order raise (Mutter deliberately treats
    // "gets focus" and "pops to the top of the stack" as separate
    // concepts) - explicit raise() is needed to actually bring the
    // window in front of whatever currently occludes it.
    win.raise();
    const workspace = win.get_workspace();
    if (workspace) {
      workspace.activate_with_focus(win, 0);
    } else {
      win.activate(0);
    }
  }

  Close(winid) {
    let win = this._get_window_by_wid(winid).meta_window;
    win.delete(global.get_current_time())
    // win.kill();
  }

  MakeAbove(winid) {
    let win = this._get_window_by_wid(winid).meta_window;
    win.make_above()
  }

  UnmakeAbove(winid) {
    let win = this._get_window_by_wid(winid).meta_window;
    win.unmake_above()
  }
}

const _calls = new WindowCalls();

export const handlers = {
  async 'list-windows'() {
    return { windows: _calls.List() };   // List() already returns the JSON string
  },
  async 'activate-window'({ id }) {
    _calls.Activate(id);                  // throws 'winid not found' -> extension.js reports ok:false
    return { ok: true };
  },
};
