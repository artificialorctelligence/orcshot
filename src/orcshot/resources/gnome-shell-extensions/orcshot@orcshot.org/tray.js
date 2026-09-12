import St from 'gi://St';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import Clutter from 'gi://Clutter';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

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

        // Diagnostics for the still-open "tray menu inert until a full
        // reboot" failure (BACKLOG #189's own entry, REQUIREMENTS.md):
        // kept commented out rather than deleted, since nobody knows
        // whether that failure will recur, and reproducing it should be
        // an uncomment-and-reinstall rather than a git dig. Uncomment
        // whichever lines are relevant, reinstall the extension, log
        // out/in, then: journalctl GLIB_DOMAIN='GNOME Shell' -f | grep
        // orcshot-tray-diag
        //
        // The old 'button-press-event'/'touch-event' probes are
        // deliberately NOT among them: this branch live-confirmed
        // neither signal ever reaches this actor at all (PanelMenu.
        // Button's own ClickGesture claims both first - see the long
        // comment on the captured-event handler below), so keeping them
        // would preserve a probe already proven to log nothing. The
        // commented line inside that handler is where real click
        // visibility lives now.
        // log(`orcshot-tray-diag: _init starting, get_n_items()=${this._menuModel.get_n_items()}`);

        // BACKLOG #189: left-click captures directly (matching the real
        // Windows tray default, and X11's own former Gtk.StatusIcon
        // "activate" signal before it was deleted) - right-click still
        // opens the menu via PanelMenu.Button's own default handling.
        //
        // Live-verified (real Ubuntu 26.04 GNOME Shell 50.1 VM,
        // Mutter/Clutter 18) that neither a 'button-press-event' signal
        // connect() nor a vfunc_event() override ever receives
        // BUTTON_PRESS/BUTTON_RELEASE on this actor at all: PanelMenu.
        // Button's own base class attaches a Clutter.ClickGesture (via
        // add_action() - this._clickGesture, toggling this.menu on ANY
        // button, with no button-filtering API on this Clutter version)
        // which claims press/release before either of those ever fire -
        // confirmed via GJS introspection
        // (Clutter.ClickGesture.prototype has no set_button) and by
        // instrumenting vfunc_event live (only saw ENTER/MOTION, never
        // BUTTON_PRESS/BUTTON_RELEASE, for a real xdotool click).
        //
        // The real interception point that DOES see the raw button
        // events, confirmed live the same way: Clutter.Actor's
        // 'captured-event' signal on global.stage, which fires during
        // the capture phase - before Clutter hands the event to any
        // actor's attached gesture actions.
        //
        // event.get_source() is NOT usable here - confirmed live it is
        // always null at this point. Real reason (upstream Clutter
        // docs/source): the source actor is normally resolved by a
        // "pick" (hit-test) that Clutter performs lazily, only when
        // building the actor-targeted event to dispatch AFTER the
        // capture phase - captured-event fires before that pick has
        // happened at all. Doing the pick ourselves, from the event's
        // own coordinates, is the real fix.
        //
        // BUTTON_PRESS, not BUTTON_RELEASE: live-verified that once a
        // press is seen here, GNOME Shell's own ClickGesture action
        // establishes an implicit grab for the rest of that click
        // sequence - the matching release event never reaches this
        // stage-level listener at all (only the press does). Acting on
        // press is a real, valid UI choice on its own merits, not a
        // workaround forced by this constraint.
        this._stageCapturedEventId = global.stage.connect('captured-event', (actor, event) => {
            if (event.type() !== Clutter.EventType.BUTTON_PRESS)
                return Clutter.EVENT_PROPAGATE;
            if (event.get_button() !== Clutter.BUTTON_PRIMARY)
                return Clutter.EVENT_PROPAGATE;
            // Pick the real target ourselves from the event's own
            // coordinates - get_source() is always null this early
            // (see the comment above this handler).
            let [x, y] = event.get_coords();
            let picked = global.stage.get_actor_at_pos(Clutter.PickMode.REACTIVE, x, y);
            if (!picked || !this.contains(picked))
                return Clutter.EVENT_PROPAGATE;
            // log('orcshot-tray-diag: primary press picked on the tray button');
            this._actionGroup.activate_action('tray-region', null);
            return Clutter.EVENT_STOP;
        });

        this._sectionSignalIds = [];
        // [item, bareAction] pairs for every real (non-separator) menu
        // item - see _refreshSensitivity()'s own comment for why this
        // exists alongside the 'action-enabled-changed' handler below.
        this._actionItems = [];
        this._rebuild();
        this._itemsChangedId = this._menuModel.connect('items-changed', (model, pos, removed, added) => {
            // log(`orcshot-tray-diag: items-changed pos=${pos} removed=${removed} added=${added}, get_n_items()=${model.get_n_items()}`);
            this._rebuild();
        });
        this._actionEnabledChangedId = this._actionGroup.connect('action-enabled-changed', (group, name, enabled) => {
            // log(`orcshot-tray-diag: action-enabled-changed name=${name} enabled=${enabled}`);
            // A full rebuild, not a targeted item lookup: this fires
            // rarely (once per capture, for "repeat_region" only, see
            // app.py's _remember_region) so the cost of re-walking the
            // whole menu is not a real concern, and it's the same
            // "just re-render everything" approach 'items-changed'
            // above already takes rather than maintaining a parallel
            // name-to-item map.
            this._rebuild();
        });
        // BACKLOG #196 follow-up, live-reproduced: Gio.DBusActionGroup's
        // own initial sync with the server is asynchronous with no
        // public "ready" signal - confirmed live that neither
        // 'action-added' nor 'action-enabled-changed' fires for the
        // initial batch, and get_action_enabled() silently returns
        // false for every action until some non-deterministic amount
        // of time passes (measured live: sometimes under 200ms,
        // sometimes still not ready past 300ms). _rebuild() above reads
        // get_action_enabled() synchronously at construction time, so
        // it reliably latches every item as permanently disabled - real,
        // live-confirmed on the Ubuntu 26.04 VM (menu opened, per
        // BACKLOG #196's own systemd-ordering fix, but every item stayed
        // greyed out across repeated opens, since nothing ever triggered
        // a fresh read afterward). Re-reading sensitivity at the moment
        // the menu actually opens - long after construction, by which
        // point the async sync has always completed in practice - is
        // the real fix, not a longer arbitrary delay guess.
        this.menu.connect('open-state-changed', (menu, open) => {
            // log(`orcshot-tray-diag: menu open-state-changed, open=${open}, numMenuItems=${this.menu.numMenuItems}`);
            if (open)
                this._refreshSensitivity();
        });
        // Standard Clutter.Actor 'destroy' signal, matching this
        // project's own orcshot-clipboard@orcshot.org convention for
        // cleanup-on-destroy - not a `_destroy_impl` vfunc override,
        // which isn't a real GJS-exposed hook on this class hierarchy
        // and would silently leak this signal connection.
        this.connect('destroy', () => {
            this._menuModel.disconnect(this._itemsChangedId);
            this._actionGroup.disconnect(this._actionEnabledChangedId);
            // global.stage outlives this button - must disconnect
            // explicitly or every future button instance (the bus name
            // can appear/vanish/reappear across a Shell session) leaks
            // one more permanently-live 'captured-event' handler.
            global.stage.disconnect(this._stageCapturedEventId);
            this._disconnectSectionSignals();
        });
    }

    _disconnectSectionSignals() {
        for (let [model, id] of this._sectionSignalIds)
            model.disconnect(id);
        this._sectionSignalIds = [];
    }

    _rebuild() {
        // log(`orcshot-tray-diag: _rebuild running, n=${this._menuModel.get_n_items()}`);
        this._disconnectSectionSignals();
        this.menu.removeAll();
        this._actionItems = [];
        this._addModelItems(this._menuModel);
        // log(`orcshot-tray-diag: _rebuild finished, menu.numMenuItems=${this.menu.numMenuItems}`);
    }

    // See the 'open-state-changed' comment in _init() for why this
    // exists: a fresh read of get_action_enabled() for every item,
    // independent of whatever _rebuild() last captured.
    _refreshSensitivity() {
        for (let [item, bareAction] of this._actionItems)
            item.setSensitive(this._actionGroup.get_action_enabled(bareAction));
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
            if (action) {
                // Bare name, no "app." prefix - see this file's own
                // Interfaces note above for why.
                let bareAction = action.includes('.') ? action.split('.').slice(1).join('.') : action;
                item.connect('activate', () => this._actionGroup.activate_action(bareAction, null));
                item.setSensitive(this._actionGroup.get_action_enabled(bareAction));
                this._actionItems.push([item, bareAction]);
            }
            this.menu.addMenuItem(item);
        }
    }

});

/** The panel button, built while org.orcshot.Orcshot is owned. extension.js
 *  drives create/destroy from its own single name watcher (there is exactly
 *  one watcher for the whole merged extension) and logs the load marker CI
 *  greps for. The status-area role stays 'orcshot-tray-button', distinct
 *  from the pre-2026-08-28 'orcshot-tray' role a stale cached copy of the
 *  old clipboard extension might still hold in an upgraded session (see
 *  [[feedback_extension_reload_caching]]) - reusing it would throw "there
 *  is already a status indicator for role ...". */
export function createTrayButton() {
    const button = new OrcshotTrayButton();
    Main.panel.addToStatusArea('orcshot-tray-button', button);
    return button;
}
