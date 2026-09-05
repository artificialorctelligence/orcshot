import St from 'gi://St';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import Clutter from 'gi://Clutter';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

// Must match app.py's fixed application_id and
// gnome_tray_export.py's TRAY_MENU_PATH exactly.
const BUS_NAME = 'org.orcshot.Orcshot';
const MENU_PATH = '/org/orcshot/Orcshot/TrayMenu';
const ACTIONS_PATH = '/org/orcshot/Orcshot';

const OrcshotTrayButton = GObject.registerClass(
class OrcshotTrayButton extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'Orcshot');

        // Orcshot's own real app logo, not a menu-item icon reused as
        // a stand-in (direflail live-caught this on Task 7's first
        // real-VM look, expected a real logo, not the region-capture
        // glyph) - "orcshot" is a fixed, unique PNG this project
        // installs at usr/share/icons/hicolor/128x128/apps/orcshot.png
        // (debian/orcshot.install), the same icon-theme name app.py's
        // own notifications already use (Gio.ThemedIcon.new("orcshot"),
        // app.py's _notify). Not a task #146
        // violation: that rule is about generic action icons (no
        // canonical per-app design to diverge on) needing to look
        // identical everywhere - this is the app's own one-of-a-kind
        // logo, which resolves to the exact same file regardless of
        // the user's icon theme since no theme ships a replacement
        // for a name it's never heard of.
        this.add_child(new St.Icon({
            gicon: Gio.ThemedIcon.new('orcshot'),
            style_class: 'system-status-icon',
            icon_size: 16,
        }));

        this._menuModel = Gio.DBusMenuModel.get(Gio.DBus.session, BUS_NAME, MENU_PATH);
        this._actionGroup = Gio.DBusActionGroup.get(Gio.DBus.session, BUS_NAME, ACTIONS_PATH);


        this._sectionSignalIds = [];
        this._rebuild();
        this._itemsChangedId = this._menuModel.connect('items-changed', (model, pos, removed, added) => {
            this._rebuild();
        });
        this._actionEnabledChangedId = this._actionGroup.connect('action-enabled-changed', (group, name, enabled) => {
            // A full rebuild, not a targeted item lookup: this fires
            // rarely (once per capture, for "repeat_region" only, see
            // app.py's _remember_region) so the cost of re-walking the
            // whole menu is not a real concern, and it's the same
            // "just re-render everything" approach 'items-changed'
            // above already takes rather than maintaining a parallel
            // name-to-item map.
            this._rebuild();
        });
        // Standard Clutter.Actor 'destroy' signal, matching this
        // project's own orcshot-clipboard@orcshot.org convention for
        // cleanup-on-destroy - not a `_destroy_impl` vfunc override,
        // which isn't a real GJS-exposed hook on this class hierarchy
        // and would silently leak this signal connection.
        this.connect('destroy', () => {
            this._menuModel.disconnect(this._itemsChangedId);
            this._actionGroup.disconnect(this._actionEnabledChangedId);
            this._disconnectSectionSignals();
        });
    }

    vfunc_event(event) {
        // BACKLOG #189: left-click captures directly (matching the
        // real Windows tray default, and X11's own former
        // Gtk.StatusIcon "activate" signal before it was deleted).
        // Overrides at the event-dispatch level, before
        // PanelMenu.Button's internal ClickGesture processes the event.
        // BUTTON_RELEASE (not PRESS) matches standard UI convention
        // and real extension patterns. Right-click and all other
        // interactions fall through to super.vfunc_event(), which
        // preserves PanelMenu.Button's default behavior (menu toggle, etc).
        if (event.type() === Clutter.EventType.BUTTON_RELEASE &&
            event.get_button() === Clutter.BUTTON_PRIMARY) {
            this._actionGroup.activate_action('tray-region', null);
            return Clutter.EVENT_STOP;
        }
        return super.vfunc_event(event);
    }

    _disconnectSectionSignals() {
        for (let [model, id] of this._sectionSignalIds)
            model.disconnect(id);
        this._sectionSignalIds = [];
    }

    _rebuild() {
        this._disconnectSectionSignals();
        this.menu.removeAll();
        this._addModelItems(this._menuModel);
    }

    // Walks a Gio.MenuModel's items, recursing into any 'section' link
    // (see gnome_tray_export.py's build_tray_menu - the top-level model
    // is now section-only, 4 sections wrapping the 8 real items) and
    // inserting a separator between groups, matching X11's own
    // _build_tray_menu (three Gtk.SeparatorMenuItems between the same
    // four groups).
    //
    // Each section link resolves to its own Gio.DBusMenuModel proxy,
    // not a plain already-populated Gio.MenuModel - genuinely uncertain
    // (no live GNOME Shell session available to confirm either way,
    // see final-review-fix-brief.md Item 1's own note on this) whether
    // it's synchronously populated once the top-level model's own
    // 'items-changed' has already fired, since the whole structure is
    // exported as one atomic Gio.Menu object in one Start() call
    // server-side (gnome_tray_export.py's export_tray_menu) - or
    // whether each link genuinely needs its own async
    // subscribe-then-populate round trip the way the org.gtk.Menus
    // wire protocol's Start()/Changed mechanism is documented to work
    // per (group, id) pair. Took the brief's own suggested safe
    // fallback rather than guessing: every section model gets its own
    // 'items-changed' listener too (tracked in _sectionSignalIds,
    // disconnected and rebuilt fresh at the top of every _rebuild()
    // call, since get_item_link() is not guaranteed to hand back the
    // same proxy object on a later call). Slightly more code, no
    // behavioral downside either way this resolves live.
    _addModelItems(model) {
        let n = model.get_n_items();
        for (let i = 0; i < n; i++) {
            let section = model.get_item_link(i, Gio.MENU_LINK_SECTION);
            if (section) {
                if (this.menu.numMenuItems > 0)
                    this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
                let id = section.connect('items-changed', () => this._rebuild());
                this._sectionSignalIds.push([section, id]);
                this._addModelItems(section);
                continue;
            }

            let label = model.get_item_attribute_value(i, 'label', null)?.deep_unpack() ?? '';
            let action = model.get_item_attribute_value(i, 'action', null)?.deep_unpack();
            let iconValue = model.get_item_attribute_value(i, 'icon', null);

            let item = new PopupMenu.PopupMenuItem(label);
            if (iconValue) {
                try {
                    let gicon = Gio.Icon.deserialize(iconValue);
                    let iconWidget = new St.Icon({ gicon, style_class: 'popup-menu-icon', icon_size: 16 });
                    // Left-aligned by construction: icon inserted
                    // BEFORE the label in child order, matching
                    // native GNOME PopupImageMenuItem's own layout -
                    // NOT ubuntu-appindicators@ubuntu.com's hard-coded
                    // xAlign: Clutter.ActorAlign.END, the bug this
                    // whole redesign exists to route around.
                    item.insert_child_below(iconWidget, item.label);
                } catch (e) {
                    logError(e, 'orcshot-tray: bad icon data');
                }
            }
            let bareAction = null;
            if (action) {
                // Bare name, no "app." prefix - see this file's own
                // Interfaces note above for why.
                bareAction = action.includes('.') ? action.split('.').slice(1).join('.') : action;
                item.connect('activate', () => this._actionGroup.activate_action(bareAction, null));
                item.setSensitive(this._actionGroup.get_action_enabled(bareAction));
            }
            this.menu.addMenuItem(item);
        }
    }

});

export default class OrcshotTrayExtension extends Extension {
    enable() {
        this._button = null;
        this._watchId = Gio.bus_watch_name(
            Gio.BusType.SESSION, BUS_NAME, Gio.BusNameWatcherFlags.NONE,
            () => {
                if (this._button)
                    return;
                try {
                    this._button = new OrcshotTrayButton();
                    // Role name deliberately distinct from the old,
                    // now-removed orcshot-clipboard@orcshot.org tray
                    // button, which used to register itself under the
                    // plain 'orcshot-tray' role - if a stale, cached
                    // copy of that old extension's JS module is still
                    // resident in a GNOME Shell process during an
                    // upgrade (see [[feedback_extension_reload_caching]]),
                    // reusing the same role name here would throw
                    // "there is already a status indicator for role
                    // 'orcshot-tray'" (caught below, so it fails safely,
                    // but this button would then silently never appear).
                    Main.panel.addToStatusArea('orcshot-tray-button', this._button);
                } catch (e) {
                    logError(e, 'orcshot-tray: failed to build tray button');
                }
            },
            () => {
                if (this._button) {
                    this._button.destroy();
                    this._button = null;
                }
            },
        );
    }

    disable() {
        if (this._watchId) {
            Gio.bus_unwatch_name(this._watchId);
            this._watchId = null;
        }
        if (this._button) {
            this._button.destroy();
            this._button = null;
        }
    }
}
