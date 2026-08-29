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

        this._menuModel = Gio.DBusMenuModel.get(Gio.DBus.session, BUS_NAME, MENU_PATH);
        this._actionGroup = Gio.DBusActionGroup.get(Gio.DBus.session, BUS_NAME, ACTIONS_PATH);
        this.menu.actionGroup = this._actionGroup;

        this._rebuild();
        this._itemsChangedId = this._menuModel.connect('items-changed', () => this._rebuild());
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
                    // First item's icon is also the panel button's
                    // own icon (Orcshot's own hand-drawn "region"
                    // icon, task #146 - never a system theme name).
                    if (i === 0 && !this._panelIconSet) {
                        this.add_child(new St.Icon({ gicon, style_class: 'system-status-icon', icon_size: 16 }));
                        this._panelIconSet = true;
                    }
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

    _destroy_impl() {
        if (this._itemsChangedId)
            this._menuModel.disconnect(this._itemsChangedId);
        super._destroy_impl?.();
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
