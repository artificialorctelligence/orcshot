# Flatpak Save through the file-chooser portal — design

**Date:** 2026-09-12 · **Backlog:** #210 (blocks the Flathub half of #198) · **Related:** #212
(snap Save, separate fix), #213 (external commands under Flatpak, out of scope here).

## Why

On 2026-09-12, accepting #208 on the Mint host with the CI-built Flatpak, direflail chose
*Capture Full Screen → Save* from the tray and no file appeared anywhere, with nothing in the log.
The manifest grants no `--filesystem=` at all (correct since #205 removed the extensions grant),
and every write in the app goes straight to a path.

Why it was *silent*, proven live in the installed Flatpak (`flatpak run --command=sh
org.orcshot.Orcshot`): the sandbox's `$HOME` is the sandbox's own tmpfs (`findmnt -T ~` →
`tmpfs[/newroot]`). `mkdir -p ~/Screenshots` and the write succeed, no error is raised, and the
file is gone when the process exits — it never existed on the host. No amount of error handling
on that path can catch it; Save has to write somewhere the host can see.

Beyond quick Save: all nine file dialogs in the app are `Gtk.FileChooserDialog` (Save Screenshot
As, Save Screenshot with format combo, Save Objects, Load Objects, Insert Image, Insert SVG,
Open, Select Command, Screenshot Save Location). That class never uses the portal — under Flatpak
it browses the tmpfs and returns paths the sandbox cannot reach. Every one is broken the same way.

## What was verified before this was written

- **Portal grants persist.** xdg-desktop-portal `desktop-portal/file-chooser.c` (main, fetched
  2026-09-12) registers every returned URI via `xdp_register_document`, which in
  `xdp-documents.c` always sets `DOCUMENT_ADD_FLAGS_PERSISTENT | REUSE_EXISTING`, adds
  `write` for save/writable, and `DOCUMENT_ADD_FLAGS_DIRECTORY` when the `directory` option was
  set. A folder picked once through the portal stays readable and writable at a stable
  `/run/user/<uid>/doc/<id>/<name>` path across restarts.
- **The runtime's GTK speaks it.** org.gnome.Platform//50 ships GTK 3.24.52; its `libgtk-3.so.0`
  contains the portal client strings `org.freedesktop.portal.FileChooser`, `OpenFile`,
  `SaveFile`, `directory`, `choices`. `Gtk.FileChooserNative` uses the portal when
  `/.flatpak-info` exists and the ordinary GTK dialog otherwise.
- **Sandbox tmpfs is detectable without path lists.** Inside the sandbox, `os.stat(p).st_dev`:
  `/` = 60, `~` = 60, `~/Screenshots` = 60; `~/.var/app/org.orcshot.Orcshot` = 43;
  `/run/user/1000/doc` = 54. Anything sharing `/`'s device is the evaporating tmpfs; every real
  host mount differs.
- **Flathub practice for the static grant.** Current flathub manifests: Flameshot
  `--filesystem=xdg-pictures`, Kooha `--filesystem=xdg-videos`, ksnip `--filesystem=host`.
  Flathub's requirements page says portals are mandatory where one covers the use case, with
  case-by-case exceptions; a screenshot tool's Pictures folder is the established exception in
  practice. `xdg-pictures:create` is not expected to draw a reviewer objection; `home`/`host`
  would.
- **Host portals present:** xdg-desktop-portal 1.20.0, -gtk 1.15.1, -xapp 1.1.3 on the Mint
  host.

## Design

### 1. Manifest

`org.orcshot.Orcshot.yaml` gains one line in `finish-args`:

```yaml
  # BACKLOG #210: the default output directory is ~/Pictures/Screenshots.
  # The same static grant Flameshot (xdg-pictures) and Kooha (xdg-videos)
  # ship on Flathub; :create so the folder can be made on first Save.
  # Any other folder the user picks goes through the FileChooser portal
  # (persistent document grant) - see section 3.
  - --filesystem=xdg-pictures:create
```

Nothing else in the manifest changes. The Flathub linter must still pass with the existing
exceptions file.

### 2. Every file dialog becomes `Gtk.FileChooserNative`

All nine `Gtk.FileChooserDialog` sites swap to `Gtk.FileChooserNative`. One code path for
.deb, snap and Flatpak: the native chooser is the portal dialog when sandboxed and the plain GTK
dialog otherwise. Per-site mechanics:

- Construction: `Gtk.FileChooserNative(title=…, transient_for=…, action=…,
  accept_label=…, cancel_label=…)`. `add_buttons(...)` calls go away; the existing labels
  (`_("Select")`, stock Save/Cancel) become `accept_label`/`cancel_label`.
- `dialog.run()` returns `Gtk.ResponseType.ACCEPT` on success, not `OK`.
- `add_filter`, `set_current_name`, `set_do_overwrite_confirmation`, `get_filename` are
  unchanged.
- **Save Screenshot's "Save as type" combo** (`editor_window.py` ~3402, the only
  `set_extra_widget` site): replaced by `dialog.add_choice("format", _("Save as type:"),
  ids, labels)` and `dialog.get_choice("format")` after ACCEPT. `add_choice` exists on
  `Gtk.FileChooser` since 3.22 for exactly this purpose; the portal renders it as a combo and
  the plain GTK dialog does too. The `on_format_changed` handler that renamed the suggested
  filename live is dropped.
- **A portal-given path is never renamed.** Found live (Scenario D, first run): the portal
  registers a *file document* for exactly the confirmed name; any sibling name the app writes in
  that document is backed by a `.xdp-<name>-XXXXXX` temp on the host and finalized only by a
  rename onto the document's own name (`document-portal-fuse.c`). Save Screenshot's post-dialog
  `with_suffix(format)` and Save Objects' `with_suffix(".json")` therefore stranded files.
  `settings.is_portal_document_path(path)` (under `$XDG_RUNTIME_DIR/doc`) gates both: under
  the portal the confirmed name is the file, its extension is the format (`save_image_to_file`
  already encodes by extension), and when that differs from the "Save as type" choice an info
  dialog says which format was written and that the extension decides. Outside the portal the
  rename behaviour is unchanged.
- `set_current_folder(get_output_directory())` is skipped when that folder is on the sandbox
  tmpfs (section 3's helper); pointing the portal at a path the host cannot see is at best
  ignored.
- `dialog.destroy()` in `finally` stays.

### 3. Quick Save under a sandbox

New helper in `settings.py`:

```python
def output_directory_is_reachable(directory: Path) -> bool:
    """True unless we are inside the Flatpak sandbox and `directory` is on the
    sandbox's own tmpfs, where writes succeed and evaporate (BACKLOG #210)."""
    if detect_channel() != "flatpak":
        return True
    directory.mkdir(parents=True, exist_ok=True)
    return os.stat(directory).st_dev != os.stat("/").st_dev
```

The `st_dev` test runs only under Flatpak: on a plain install `/home` may or may not be its own
filesystem, so the comparison means nothing there.

There are two quick-save paths — `destination_picker._quick_save` (tray / picker) and
`EditorWindow._do_quick_save` (editor menu) — and both start with `get_output_directory()`.
One new function in `destination_picker.py`, `ensure_output_directory(parent) -> Path | None`,
replaces that call in both: it returns the directory when reachable; otherwise it runs the
existing `_choose_save_location` picker (module-level in `editor_window.py`, now portal-backed
by section 2) and re-checks. The portal returns a persistent `/run/user/…/doc/…` path;
`set_output_directory` stores it as today; the save proceeds into it, and every later quick Save
is silent. If the picker is cancelled or the chosen folder is still unreachable, it returns
`None`, the caller writes nothing, and a warning is logged — no more silent success.

Out of the box under Flatpak (no configured directory, host has `~/Pictures`): `~/Pictures` is
visible through the section-1 grant, `default_output_directory()` returns
`~/Pictures/Screenshots`, it is reachable, no dialog ever appears. A host without `~/Pictures`
falls to `~/Screenshots` on the tmpfs → the picker runs once.

### 4. Preferences "location" label

Unchanged: it shows `get_output_directory()`. For a portal-picked folder that is
`/run/user/1000/doc/a1b2c3/Screenshots`. Accepted for now; `ponytail:` comment naming the
upgrade (show the folder's display name, or resolve through the Documents portal's `GetHostPaths`).

## Testing

- `output_directory_is_reachable`: True outside Flatpak for any path (detect_channel
  monkeypatched to "deb"); under "flatpak", False when `os.stat` reports the same `st_dev` as
  `/`, True otherwise. Realistic paths, `os.stat` monkeypatched — never touches a real sandbox.
- `_quick_save` under "flatpak" with an unreachable directory calls the picker; picker cancelled
  → `save_image_to_file` not called, warning logged; picker accepted → saved into the returned
  path and `set_output_directory` called with it.
- Existing tests that drive any of the nine dialogs get the `ACCEPT`/`get_choice` changes.
  No new per-site tests: the swap is mechanical and the live scenarios below cover the portal.
- Flathub linter run on the manifest (existing CI step) must pass.

## Live verification (VERIFICATION.md scenarios)

All on the CI-built Flatpak bundle, never on the dev checkout:

1. **Mint host, today's repro.** `output_directory` configured to `~/Screenshots`. Tray →
   Capture Full Screen → Save. Expected: the "Screenshot Save Location" portal dialog appears
   once; after choosing `~/Screenshots`, the file is in `~/Screenshots` on the host. Second
   Save: no dialog, file lands.
2. **Fresh Flatpak, no config, host has `~/Pictures`.** Save is silent; file in
   `~/Pictures/Screenshots`; no dialog at any point.
3. **Save Screenshot dialog.** "Save as type" appears in the portal dialog; choosing JPEG yields
   a `.jpg` on the host with quality applied.
4. **Open and Insert Image through the portal.** A host file outside Pictures loads.
5. **Ubuntu 26.04 / GNOME 50 VM**, scenario 1 again — the portal frontend there is
   xdg-desktop-portal-gnome, not -xapp.
6. **Restart persistence.** After scenario 1, quit and relaunch the Flatpak; Save is still
   silent and still lands (the document grant survived).

## Scope boundaries

- **Snap Save** is #212: no `home` plug, AppArmor denial rather than tmpfs — different mechanism,
  one-line fix, its own verification. Not folded in.
- **External commands / Open in External Editor under Flatpak** is #213: the sandbox cannot exec
  host programs at all; unrelated to file dialogs.
- **apt/PPA**: no sandbox; `Gtk.FileChooserNative` is the ordinary GTK dialog there and
  `output_directory_is_reachable` is trivially True. Behaviour must be unchanged.

## Verification items (facts to confirm while building, not decisions)

1. GTK 3.24.52's portal backend sends `directory: true` for `SELECT_FOLDER` (the string is in
   the binary; confirm scenario 1 actually shows a folder picker, not a file picker).
2. `get_choice` returns the chosen id after ACCEPT through the portal on both -gtk/-xapp (Mint)
   and -gnome (VM) backends.
3. `set_current_folder` on a `/run/user/…/doc/…` path is honoured by the portal (opens there) —
   if not, harmless; note it. **Result:** not honoured — the portal dialog opens in Home.
