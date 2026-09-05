const Applet = imports.ui.applet;
const Gio = imports.gi.Gio;
const PopupMenu = imports.ui.popupMenu;
const St = imports.gi.St;

// Must match app.py's fixed application_id and gnome_tray_export.py's
// TRAY_MENU_PATH exactly - same values orcshot-tray@orcshot.org's
// GNOME Shell extension uses, see that file's own comment.
const BUS_NAME = 'org.orcshot.Orcshot';
const MENU_PATH = '/org/orcshot/Orcshot/TrayMenu';
const ACTIONS_PATH = '/org/orcshot/Orcshot';

class OrcshotTrayApplet extends Applet.IconApplet {
    constructor(metadata, orientation, panel_height, instance_id) {
        super(orientation, panel_height, instance_id);

        // Same real app logo the GNOME extension uses
        // (Gio.ThemedIcon.new("orcshot"), usr/share/icons/hicolor/
        // 128x128/apps/orcshot.png via debian/orcshot.install) - not a
        // generic action icon, so no theme ships a replacement for a
        // name it's never heard of.
        this.set_applet_icon_name('orcshot');
        this.set_applet_tooltip('Orcshot');

        this._menuModel = Gio.DBusMenuModel.get(Gio.DBus.session, BUS_NAME, MENU_PATH);
        this._actionGroup = Gio.DBusActionGroup.get(Gio.DBus.session, BUS_NAME, ACTIONS_PATH);

        this._sectionSignalIds = [];
        this._rebuild();
        this._itemsChangedId = this._menuModel.connect('items-changed', () => this._rebuild());
        this._actionEnabledChangedId = this._actionGroup.connect(
            'action-enabled-changed', () => this._rebuild());
    }

    // Called automatically by Applet's own _onButtonPressEvent on a
    // primary (left) click - see this file's own header comment for
    // why no manual button.get_button() check is needed here.
    on_applet_clicked(event) {
        this._actionGroup.activate_action('tray-region', null);
    }

    _disconnectSectionSignals() {
        for (let [model, id] of this._sectionSignalIds)
            model.disconnect(id);
        this._sectionSignalIds = [];
    }

    // Populates this._applet_context_menu (built by the Applet base
    // class itself) directly, rather than a separate menu of our own -
    // this is what makes our items show up on right-click alongside
    // Cinnamon's own built-in Remove/Configure/About entries, which
    // the base class also adds to this same menu instance.
    _rebuild() {
        this._disconnectSectionSignals();
        this._applet_context_menu.removeAll();
        this._addModelItems(this._menuModel);
    }

    // Same recursive section-walk as orcshot-tray@orcshot.org's GNOME
    // Shell extension (_addModelItems there) - same Gio.MenuModel
    // shape, same reasoning for why every section link needs its own
    // 'items-changed' listener.
    _addModelItems(model) {
        let n = model.get_n_items();
        for (let i = 0; i < n; i++) {
            let section = model.get_item_link(i, Gio.MENU_LINK_SECTION);
            if (section) {
                if (this._applet_context_menu._getMenuItems().length > 0)
                    this._applet_context_menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
                let id = section.connect('items-changed', () => this._rebuild());
                this._sectionSignalIds.push([section, id]);
                this._addModelItems(section);
                continue;
            }

            let label = model.get_item_attribute_value(i, 'label', null)?.deep_unpack() ?? '';
            let action = model.get_item_attribute_value(i, 'action', null)?.deep_unpack();
            let iconValue = model.get_item_attribute_value(i, 'icon', null);

            // PopupIconMenuItem's own iconName parameter is a string
            // (a themed icon *name*) - confirmed live it throws "Wrong
            // type GObject_Object; string expected" when handed a real
            // Gio.Icon object, which is what our menu items actually
            // carry (raw serialized PNG bytes from the D-Bus menu
            // model, same as the GNOME extension's own _addModelItems).
            // Plain PopupMenuItem already builds its own St.Icon
            // internally (this._icon) - set_gicon() on that, after
            // construction, is the real way to hand it an arbitrary
            // Gio.Icon rather than a named one.
            let item = new PopupMenu.PopupMenuItem(label);
            if (iconValue)
                item._icon.set_gicon(Gio.Icon.deserialize(iconValue));
            let bareAction = null;
            if (action) {
                bareAction = action.includes('.') ? action.split('.').slice(1).join('.') : action;
                item.connect('activate', () => this._actionGroup.activate_action(bareAction, null));
                item.setSensitive(this._actionGroup.get_action_enabled(bareAction));
            }
            this._applet_context_menu.addMenuItem(item);
        }
    }
}

function main(metadata, orientation, panel_height, instance_id) {
    return new OrcshotTrayApplet(metadata, orientation, panel_height, instance_id);
}
