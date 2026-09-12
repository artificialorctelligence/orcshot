const Applet = imports.ui.applet;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const PopupMenu = imports.ui.popupMenu;

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
        // Real, live-confirmed bug this tracks around: PopupMenu's own
        // removeAll() calls .destroy() on *every* current child
        // (popupMenu.js's own removeAll()), not just the ones we
        // added. Cinnamon's own Remove/Configure/About entries live in
        // this exact same this._applet_context_menu (added once, by
        // finalizeContextMenu(), called synchronously by
        // appletManager.js's createApplet() right after main()
        // returns - before our own menu model's first real, async
        // D-Bus population ever lands). A naive removeAll() in
        // _rebuild() would destroy those built-ins the moment real
        // data first arrives, permanently, since finalizeContextMenu()
        // only ever runs once more on an orientation change, and even
        // then only via a now-stale, already-destroyed item reference.
        // Tracking and destroying only our own items keeps Cinnamon's
        // own entries alone entirely.
        this._ownMenuItems = [];
        this._rebuild();
        this._itemsChangedId = this._menuModel.connect('items-changed', () => this._rebuild());
        this._actionEnabledChangedId = this._actionGroup.connect(
            'action-enabled-changed', () => this._rebuild());
        // BACKLOG #196's fix, ported from the GNOME Shell tray on
        // 2026-09-11 (found the first time this applet sat on a real
        // Cinnamon panel): Gio.DBusActionGroup's initial sync with the
        // app is asynchronous with no "ready" signal, and
        // get_action_enabled() answers false for every action until it
        // completes - so the setSensitive() calls in _addModelItems
        // latch every item greyed at build time and nothing re-reads
        // them. Re-reading when the menu actually opens is the fix.
        this._applet_context_menu.connect('open-state-changed', (menu, open) => {
            if (open)
                this._refreshSensitivity();
        });

        // An applet's own lifecycle is owned by Cinnamon's panel, not by
        // us - unlike the GNOME Shell extension's status-area button
        // (extension.js's enable()/disable()), this applet can't be
        // constructed/destroyed on demand when Orcshot itself starts or
        // quits. Watching the same bus name and toggling this applet's
        // own actor is the real equivalent: direflail's standing
        // requirement (see app.py) is "when the user selects quit, i
        // want all parts of the program to quit and vanish" - without
        // this, the icon just sits in the panel looking functional after
        // Orcshot has already exited. Starts hidden (below) so there's
        // no visible icon at all until the appeared callback actually
        // confirms org.orcshot.Orcshot is up.
        this.actor.hide();
        this._busWatchId = Gio.bus_watch_name(
            Gio.BusType.SESSION, BUS_NAME, Gio.BusNameWatcherFlags.NONE,
            () => {
                // Re-run in case the menu model's identity changed across
                // a restart (a fresh Gio.DBusMenuModel/Gio.DBusActionGroup
                // proxy pair, same objects held since the constructor).
                this._rebuild();
                this.actor.show();
            },
            () => {
                this.actor.hide();
            },
        );
    }

    // Called automatically by Applet's own _onButtonPressEvent on a
    // primary (left) click - see this file's own header comment for
    // why no manual button.get_button() check is needed here.
    on_applet_clicked(event) {
        this._actionGroup.activate_action('tray-region', null);
    }

    // Called by Cinnamon's own _onAppletRemovedFromPanel when the
    // applet is removed or the panel reloads it - matches the GNOME
    // Shell extension's own 'destroy' handler for the identical pair
    // of D-Bus proxy signals (Gio.DBusMenuModel/Gio.DBusActionGroup
    // connections hold a strong closure reference to `this`; omitting
    // this leaks both the signal connection and the applet instance).
    on_applet_removed_from_panel(deleteConfig) {
        if (this._activateTimerId) {
            GLib.source_remove(this._activateTimerId);
            this._activateTimerId = 0;
        }
        this._menuModel.disconnect(this._itemsChangedId);
        this._actionGroup.disconnect(this._actionEnabledChangedId);
        this._disconnectSectionSignals();
        Gio.bus_unwatch_name(this._busWatchId);
    }

    _disconnectSectionSignals() {
        for (let [model, id] of this._sectionSignalIds)
            model.disconnect(id);
        this._sectionSignalIds = [];
    }

    // Close the menu instantly, then fire the action a beat later: the
    // menu is Cinnamon's, with its own fade-out, so the app's one-main-
    // loop-turn deferral (app.py's _defer, task #134) cannot see it -
    // captures started from this menu were getting the menu itself
    // baked in (found live on the Mint host, 2026-09-11). 150 ms is
    // longer than the fade; the timer id is tracked and cleared in
    // on_applet_removed_from_panel per Spices' lifecycle rules.
    _activateAfterClose(bareAction) {
        this._applet_context_menu.close(false);
        if (this._activateTimerId)
            GLib.source_remove(this._activateTimerId);
        this._activateTimerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 150, () => {
            this._activateTimerId = 0;
            this._actionGroup.activate_action(bareAction, null);
            return GLib.SOURCE_REMOVE;
        });
    }

    _refreshSensitivity() {
        for (let item of this._ownMenuItems) {
            if (item._orcshotAction)
                item.setSensitive(this._actionGroup.get_action_enabled(item._orcshotAction));
        }
    }

    // Destroys only the items *we* added (this._ownMenuItems), never
    // this._applet_context_menu.removeAll() - see the real bug this
    // tracks around, explained in the constructor's own comment.
    _rebuild() {
        this._disconnectSectionSignals();
        for (let item of this._ownMenuItems)
            item.destroy();
        this._ownMenuItems = [];
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
                if (this._applet_context_menu._getMenuItems().length > 0) {
                    let separator = new PopupMenu.PopupSeparatorMenuItem();
                    this._applet_context_menu.addMenuItem(separator);
                    this._ownMenuItems.push(separator);
                }
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
            if (iconValue) {
                try {
                    item._icon.set_gicon(Gio.Icon.deserialize(iconValue));
                } catch (e) {
                    // global.logError, not GNOME Shell's bare logError(e, prefix) -
                    // Cinnamon's own JS environment doesn't define that global at
                    // all; global.logError(message, error) is the real, confirmed
                    // signature (message first - see e.g. xrandr@cinnamon.org's
                    // own applet.js on this host).
                    global.logError('orcshot-tray applet: bad icon data', e);
                }
            }
            if (action) {
                let bareAction = action.includes('.') ? action.split('.').slice(1).join('.') : action;
                item._orcshotAction = bareAction;
                item.connect('activate', () => this._activateAfterClose(bareAction));
                item.setSensitive(this._actionGroup.get_action_enabled(bareAction));
            }
            this._applet_context_menu.addMenuItem(item);
            this._ownMenuItems.push(item);
        }
    }
}

function main(metadata, orientation, panel_height, instance_id) {
    return new OrcshotTrayApplet(metadata, orientation, panel_height, instance_id);
}
