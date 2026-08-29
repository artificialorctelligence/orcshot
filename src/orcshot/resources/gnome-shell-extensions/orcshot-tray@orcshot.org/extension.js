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
        this.menu.actionGroup = this._actionGroup;

        // TEMPORARY diagnostics (Task 7 live debugging, direflail
        // asked for click-behavior visibility) - remove once the
        // menu-doesn't-open bug is actually found. All go through
        // log() with a fixed, greppable prefix so `journalctl
        // GLIB_DOMAIN=GNOME Shell` or a plain grep for
        // "orcshot-tray-diag" finds every line.
        log(`orcshot-tray-diag: _init starting, get_n_items()=${this._menuModel.get_n_items()}`);
        this.connect('button-press-event', () => {
            log('orcshot-tray-diag: button-press-event fired');
            return Clutter.EVENT_PROPAGATE;
        });
        this.connect('touch-event', () => {
            log('orcshot-tray-diag: touch-event fired');
            return Clutter.EVENT_PROPAGATE;
        });
        this.menu.connect('open-state-changed', (menu, open) => {
            log(`orcshot-tray-diag: menu open-state-changed, open=${open}, numMenuItems=${this.menu.numMenuItems}`);
        });

        this._sectionSignalIds = [];
        this._rebuild();
        this._itemsChangedId = this._menuModel.connect('items-changed', (model, pos, removed, added) => {
            log(`orcshot-tray-diag: items-changed pos=${pos} removed=${removed} added=${added}, get_n_items()=${model.get_n_items()}`);
            this._rebuild();
        });
        this._actionEnabledChangedId = this._actionGroup.connect('action-enabled-changed', (group, name, enabled) => {
            log(`orcshot-tray-diag: action-enabled-changed name=${name} enabled=${enabled}`);
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

    _disconnectSectionSignals() {
        for (let [model, id] of this._sectionSignalIds)
            model.disconnect(id);
        this._sectionSignalIds = [];
    }

    _rebuild() {
        this._disconnectSectionSignals();
        this.menu.removeAll();
        log(`orcshot-tray-diag: _rebuild running, n=${this._menuModel.get_n_items()}`);
        this._addModelItems(this._menuModel);
        log(`orcshot-tray-diag: _rebuild finished, menu.numMenuItems=${this.menu.numMenuItems}`);
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
                log('orcshot-tray-diag: bus name appeared');
                if (this._button)
                    return;
                try {
                    this._button = new OrcshotTrayButton();
                    Main.panel.addToStatusArea('orcshot-tray', this._button);
                    log('orcshot-tray-diag: button constructed and added to status area');
                } catch (e) {
                    logError(e, 'orcshot-tray: failed to build tray button');
                }
            },
            () => {
                log('orcshot-tray-diag: bus name vanished');
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
