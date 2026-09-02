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

## GNOME Shell's `org.gnome.shell` GSettings schema (org.gnome.shell.gschema.xml)

- **Location in this repo:** `org.gnome.shell.gschema.xml` (repo root, next to the
  Flatpak manifest that installs it)
- **Upstream:** https://gitlab.gnome.org/GNOME/gnome-shell (`data/` directory);
  extracted here from Ubuntu 24.04's real
  `gnome-shell-common_46.0-0ubuntu6~24.04.14_all.deb` (sha256
  `a61d931db26599f20c6dd0d4e7e6acb316871d6e1c1f2f66e07f0807c4f98539`, downloaded and
  verified 2026-08-31), unmodified.
- **License:** GPL-2.0-or-later (`gnome-shell-common`'s own `debian/copyright`
  attributes the package as a whole to GPL-2+; compatible with this project's own
  GPLv3 license via the "or later" clause, same reasoning as the window-calls entry
  above)
- **Why it's here:** `org.orcshot.Orcshot.yaml`'s `gnome-shell-schema` module
  installs and compiles this schema into the Flatpak build - `gnome_shell_present()`
  (`src/orcshot/gnome_extension_setup.py`) needs `org.gnome.shell`'s own compiled
  schema to resolve at all, and `org.gnome.Platform//50` does not bundle it
  (confirmed live; BACKLOG #192 found the same gap on Snap's `core24` base).
  Vendored in-repo rather than fetched by URL at build time (final-review finding,
  2026-08-31): the previous pinned `archive.ubuntu.com/.../pool/...` URL only
  stays reachable while that exact package revision is still the current one in
  `pool/` - a routine Ubuntu security update would 404 this build on a commit that
  changed nothing. A single ~16KB schema file that only changes when GNOME Shell's
  own schema does is cheap to vendor outright.
- **Not modified from the extracted copy.**

## MS-NRBF binary writer (core/nrbf.py)

- **Location in this repo:** `src/orcshot/core/nrbf.py`
- **Upstream:** https://github.com/agix/NetBinaryFormatterParser
  (`JSON2dotnetBinaryFormatter.py`)
- **License:** MIT (Copyright (c) 2016 NetBinaryFormatterParser)
- **Why it's here:** task #124 (exporting Orcshot shapes to real Windows
  Greenshot's own `.greenshot`/`.gst` file format) needs to write .NET's
  `BinaryFormatter`/MS-NRBF wire format from Python - this is the record-writing
  logic that format needs, adapted rather than written from scratch.
- **Modifications from upstream:** ported from Python 2's dict/JSON-driven design
  to a small typed `Writer` class (Python 3), and two real bugs fixed: `Single`/
  `Double` were packed with `'<I'`/`'<Q'` (reinterpreting the raw bits as an
  unsigned integer) instead of `'<f'`/`'<d'` (actual IEEE 754 encoding). The
  resulting record layout was independently verified byte-for-byte against a
  real `Greenshot.Editor.dll` object serialized with the actual `BinaryFormatter`
  on a real Windows 11 VM - see `REQUIREMENTS.md`'s task #124 section for the
  full trace and citations.

## Capture-complete sound (resources/camera-shutter.oga)

- **Location in this repo:** `src/orcshot/resources/camera-shutter.oga`
- **Upstream:** the `sound-theme-freedesktop` package (`stereo/camera-shutter.oga`,
  version `0.8-2ubuntu1` on Ubuntu 24.04/26.04 - `dpkg -S` confirms this exact file)
- **License:** CC-BY-SA-3.0
- **Copyright:** freesound user `horsthorstensen` (per `sound-theme-freedesktop`'s own
  `debian/copyright`, which also credits this same file as the source for
  `stereo/screen-capture.oga` - the two are the identical audio, `screen-capture.oga`
  is a plain symlink to `camera-shutter.oga` on a real install, confirmed live)
- **Why it's here:** `capture/capture_feedback.py`'s own module docstring has the
  full story - this used to be resolved at runtime from the desktop's own installed
  sound theme via GSound's `"camera-shutter"` event ID, which broke on the Flatpak
  channel (no GSound typelib available there). Bundling this exact file (byte-for-byte
  the same audio GSound's theme lookup already resolved to on a standard install) and
  playing it via GStreamer instead works identically on all three channels - confirmed
  live on three separate real machines (Mint, Ubuntu 24.04.4 LTS, Ubuntu 26.04/GNOME 50).
- **Not modified from the extracted copy.**
