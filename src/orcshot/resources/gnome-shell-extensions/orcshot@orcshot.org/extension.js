// extension.js - Orcshot's GNOME Shell extension: one name watcher, one
// Hello, one request loop. Everything privileged lives in capture.js,
// windows.js and tray.js; this file only routes.
//
// Direction: this extension CALLS the Orcshot app; the app never calls the
// Shell. The app asks by changing the state of its `shell-request` action
// (org.gtk.Actions.Changed is the one signal a strict snap may emit), and
// this file answers with GetRequest/Deliver on org.orcshot.Orcshot.Shell.
// Proven under both the strict snap and the Flatpak sandbox on 2026-09-11.
// Spec: docs/superpowers/specs/2026-09-11-snap-compliant-extension-delivery-design.md
//
// SPDX-License-Identifier: GPL-3.0-or-later
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Capture from './capture.js';
import * as Windows from './windows.js';
import { createTrayButton } from './tray.js';

const BUS_NAME = 'org.orcshot.Orcshot';
const ACTIONS_PATH = '/org/orcshot/Orcshot';
const SHELL_PATH = '/org/orcshot/Orcshot/Shell';
const SHELL_IFACE = 'org.orcshot.Orcshot.Shell';
const REQUEST_ACTION = 'shell-request';

const HANDLERS = { ...Capture.handlers, ...Windows.handlers };
// What Hello announces. 'tray' is reported, never requested.
const CAPABILITIES = ['tray', ...Object.keys(HANDLERS)];

// A result object -> the plain {key: GLib.Variant} object GJS packs into
// the a{sv} Deliver carries. Numbers are 'i' (every numeric result here
// is a pixel coordinate or a 0-255 channel), bytes are 'ay' - the
// shell_bridge on the app side normalises those back.
function toVariantDict(obj) {
    const out = {};
    for (const [k, v] of Object.entries(obj)) {
        if (typeof v === 'boolean')
            out[k] = new GLib.Variant('b', v);
        else if (typeof v === 'number')
            out[k] = new GLib.Variant('i', v | 0);
        else if (typeof v === 'string')
            out[k] = new GLib.Variant('s', v);
        else if (v instanceof Uint8Array)
            out[k] = new GLib.Variant('ay', v);
        else if (v instanceof GLib.Bytes)
            out[k] = new GLib.Variant('ay', v.toArray());
        else
            throw new Error(`unsupported result value for ${k}: ${typeof v}`);
    }
    return out;
}

export default class OrcshotExtension extends Extension {
    enable() {
        // One permanent, intentional load marker: CI greps the Shell log
        // for this exact string as proof GNOME Shell loaded the extension.
        log('orcshot: extension enabled');
        this._button = null;
        this._group = null;
        this._stateChangedId = 0;
        this._watchId = Gio.bus_watch_name(
            Gio.BusType.SESSION, BUS_NAME, Gio.BusNameWatcherFlags.NONE,
            () => this._onAppAppeared(),
            () => this._onAppVanished(),
        );
    }

    disable() {
        if (this._watchId) {
            Gio.bus_unwatch_name(this._watchId);
            this._watchId = 0;
        }
        this._onAppVanished();
    }

    _onAppAppeared() {
        if (!this._button) {
            try {
                this._button = createTrayButton();
            } catch (e) {
                logError(e, 'orcshot: failed to build tray button');
            }
        }
        this._group = Gio.DBusActionGroup.get(Gio.DBus.session, BUS_NAME, ACTIONS_PATH);
        this._stateChangedId = this._group.connect('action-state-changed', (_group, name, state) => {
            if (name === REQUEST_ACTION)
                this._handleRequest(state.get_uint32()).catch(e => logError(e, 'orcshot: request failed'));
        });
        // The first list_actions() only kicks off DescribeAll; the group
        // goes live asynchronously, after which state changes arrive.
        this._group.list_actions();
        this._call('Hello', new GLib.Variant('(sas)', [this.metadata['version-name'], CAPABILITIES]))
            .catch(e => logError(e, 'orcshot: Hello failed'));
    }

    _onAppVanished() {
        if (this._group && this._stateChangedId)
            this._group.disconnect(this._stateChangedId);
        this._group = null;
        this._stateChangedId = 0;
        if (this._button) {
            this._button.destroy();
            this._button = null;
        }
    }

    _call(method, args) {
        return new Promise((resolve, reject) => {
            Gio.DBus.session.call(BUS_NAME, SHELL_PATH, SHELL_IFACE, method, args, null,
                Gio.DBusCallFlags.NONE, 10000, null, (conn, res) => {
                    try {
                        resolve(conn.call_finish(res));
                    } catch (e) {
                        reject(e);
                    }
                });
        });
    }

    async _handleRequest(id) {
        if (!id)
            return;   // the action's initial state is 0
        // recursiveUnpack, not deepUnpack: the a{sv} values are variants
        // themselves and only recursiveUnpack opens those too.
        const [req] = (await this._call('GetRequest', new GLib.Variant('(u)', [id]))).recursiveUnpack();
        const { kind, ...params } = req;
        const handler = HANDLERS[kind];
        let result;
        try {
            result = handler ? await handler(params) : { ok: false, error: `unknown kind ${kind}` };
        } catch (e) {
            logError(e, `orcshot: handler ${kind} threw`);
            result = { ok: false, error: String(e) };
        }
        await this._call('Deliver', new GLib.Variant('(ua{sv})', [id, toVariantDict(result)]));
    }
}
