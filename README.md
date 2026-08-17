# Orcshot

A Linux port of [Greenshot](https://getgreenshot.org/), built as a faithful Python + GTK3
behavioral port - not affiliated with or endorsed by the Greenshot project. See
[REQUIREMENTS.md](REQUIREMENTS.md) for full scope, platform priorities, and architecture decisions.

## Installing

Orcshot doesn't have a published release yet, so for now you build and install the `.deb` yourself.
It's a normal Debian package - once installed, it behaves like any other app (shows up in your
application menu, uninstalls cleanly with `apt remove`, etc.).

Verified on: Linux Mint (Cinnamon), Ubuntu 24.04 LTS, and Ubuntu 26.04 LTS.

```
sudo apt install dpkg-dev debhelper dh-python pybuild-plugin-pyproject python3-all \
    python3-hatchling python3-pytest python3-hypothesis python3-scipy python3-gi \
    python3-gi-cairo python3-cairo python3-numpy python3-shapely python3-xlib \
    gir1.2-gtk-3.0 gir1.2-rsvg-2.0 gir1.2-gdkpixbuf-2.0 gir1.2-pango-1.0 gir1.2-glib-2.0

git clone https://github.com/artificialorctelligence/orcshot.git
cd orcshot
dpkg-buildpackage -us -uc -b
sudo apt install ../orcshot_*_all.deb
```

The first time you launch Orcshot, it offers to set up capture keyboard shortcuts and start-on-login
(Cinnamon only for the shortcuts - see the note in `debian/control` for other desktops). You can revisit
this any time from the tray icon's Preferences.

To update later: pull the latest changes, rebuild, and reinstall with the same `apt install` command
above (reinstalling never touches your keybindings, autostart setting, or any other preferences - those
live in your own user config, not the package). Once a real release exists, Help > Check for Updates
will tell you when a newer one is available.

## Development setup

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Requires system packages for building PyGObject: `libcairo2-dev`, `libgirepository-2.0-dev`,
`libgtk-3-dev`.

## Running tests

```
.venv/bin/pytest
```
