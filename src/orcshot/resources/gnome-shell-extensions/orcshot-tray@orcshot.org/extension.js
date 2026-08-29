import St from 'gi://St';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
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

        this._rebuild();
        this._itemsChangedId = this._menuModel.connect('items-changed', () => this._rebuild());
        // Standard Clutter.Actor 'destroy' signal, matching this
        // project's own orcshot-clipboard@orcshot.org convention for
        // cleanup-on-destroy - not a `_destroy_impl` vfunc override,
        // which isn't a real GJS-exposed hook on this class hierarchy
        // and would silently leak this signal connection.
        this.connect('destroy', () => this._menuModel.disconnect(this._itemsChangedId));
    }

    _rebuild() {
        this.menu.removeAll();
        let n = this._menuModel.get_n_items();
        for (let i = 0; i < n; i++) {
            let label = this._menuModel.get_item_attribute_value(i, 'label', null)?.deep_unpack() ?? '';
            let action = this._menuModel.get_item_attribute_value(i, 'action', null)?.deep_unpack();
            let iconValue = this._menuModel.get_item_attribute_value(i, 'icon', null);

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
            if (action) {
                // Bare name, no "app." prefix - see this file's own
                // Interfaces note above for why.
                let bareAction = action.includes('.') ? action.split('.').slice(1).join('.') : action;
                item.connect('activate', () => this._actionGroup.activate_action(bareAction, null));
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
                    Main.panel.addToStatusArea('orcshot-tray', this._button);
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
