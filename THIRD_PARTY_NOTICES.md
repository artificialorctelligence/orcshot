# Third-party components

## window-calls GNOME Shell extension

- **Location in this repo:** `src/orcshot/resources/gnome-shell-extensions/window-calls@domandoman.xyz/`
- **Upstream:** https://github.com/ickyicky/window-calls
- **License:** GPL-2.0-or-later (SPDX header in `extension.js`; compatible with this
  project's own GPLv3 license via the "or later" clause)
- **Why it's here:** provides the window enumeration and window-activation D-Bus
  calls that `orcshot`'s "Capture Window" mode needs under Wayland, where no
  portable equivalent exists otherwise (see `REQUIREMENTS.md`'s Wayland window-picker
  section for the full rationale).
- **Modifications from upstream:** three bug fixes and one small addition, documented
  in full in a comment block at the top of `extension.js` itself (a
  `ReferenceError` fix affecting `Details`/`GetTitle`/`Activate`/etc., a `List()`
  geometry fix, an added `minimized` field in `List()`, and an added `raise()` call
  in `Activate()` - all live-verified against a real GNOME/Wayland session).
- **Not enabled automatically:** this project never silently enables GNOME
  extensions or writes to the user's real desktop settings as a side effect of
  installing or running the app. The `.deb` only places the extension's files on
  disk; enabling it happens exclusively through the user's own confirmation in the
  first-run setup dialog, the same way this project already handles hotkey and
  autostart configuration.
