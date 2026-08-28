**English** | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Українська](README.uk.md) | [हिन्दी](README.hi.md) | [日本語](README.ja.md) | [中文](README.zh.md)

# Orcshot

**Quick install** (Ubuntu 24.04/26.04, Mint, and other Ubuntu-based distros):
```bash
sudo add-apt-repository ppa:artificialorctelligence/orcshot
sudo apt update && sudo apt install orcshot
```

A Linux port of [Greenshot](https://getgreenshot.org/), built as a faithful Python + GTK3
behavioral port - not affiliated with or endorsed by the Greenshot project. It's also unrelated
to the [Apache ORC](https://orc.apache.org/) project - the shared "Orc" is coincidental. See
[REQUIREMENTS.md](REQUIREMENTS.md) for full scope, platform priorities, and architecture decisions.

## Installing

**From the PPA** (Ubuntu 24.04 LTS, Ubuntu 26.04 LTS, and Ubuntu-based distros like Linux Mint):

```
sudo add-apt-repository ppa:artificialorctelligence/orcshot
sudo apt update
sudo apt install orcshot
```

**From source** (any other Debian-based distro, or if you'd rather build it yourself):

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

Either way it's a normal Debian package - once installed, it behaves like any other app (shows up in
your application menu, uninstalls cleanly with `apt remove`, etc.). Verified on: Linux Mint (Cinnamon),
Ubuntu 24.04 LTS, and Ubuntu 26.04 LTS.

The first time you launch Orcshot, it offers to set up capture keyboard shortcuts and start-on-login
(Cinnamon only for the shortcuts - see the note in `debian/control` for other desktops). You can revisit
this any time from the tray icon's Preferences.

To update later: `sudo apt update && sudo apt upgrade` (PPA install), or pull the latest changes and
rebuild/reinstall (from source) - reinstalling never touches your keybindings, autostart setting, or any
other preferences, those live in your own user config, not the package. Help > Check for Updates also
tells you when a newer version is available.

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
