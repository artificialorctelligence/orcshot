[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | **Deutsch** | [Українська](README.uk.md) | [हिन्दी](README.hi.md) | [日本語](README.ja.md) | [中文](README.zh.md)

# Orcshot

Eine Linux-Portierung von [Greenshot](https://getgreenshot.org/), umgesetzt als originalgetreue
Verhaltensportierung in Python + GTK3 – nicht mit dem Greenshot-Projekt verbunden und nicht von ihm
unterstützt. Den vollständigen Umfang, die Plattformprioritäten und die Architekturentscheidungen
finden Sie in [REQUIREMENTS.md](REQUIREMENTS.md).

## Installation

Für Orcshot gibt es noch keine veröffentlichte Version, daher bauen und installieren Sie das `.deb`
vorerst selbst. Es ist ein ganz normales Debian-Paket – einmal installiert, verhält es sich wie jede
andere Anwendung (es erscheint im Anwendungsmenü, lässt sich mit `apt remove` sauber deinstallieren
usw.).

Getestet auf: Linux Mint (Cinnamon), Ubuntu 24.04 LTS und Ubuntu 26.04 LTS.

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

Beim ersten Start bietet Orcshot an, Tastenkürzel für Aufnahmen und den Start bei der Anmeldung
einzurichten (die Tastenkürzel nur unter Cinnamon – für andere Desktop-Umgebungen siehe den Hinweis
in `debian/control`). Sie können das jederzeit über die Einstellungen im Tray-Symbol erneut aufrufen.

Für spätere Aktualisierungen: die neuesten Änderungen holen, neu bauen und mit demselben
`apt install`-Befehl von oben erneut installieren (eine Neuinstallation rührt Ihre Tastenbelegungen,
die Autostart-Einstellung und alle anderen Einstellungen niemals an – die liegen in Ihrer eigenen
Benutzerkonfiguration, nicht im Paket). Sobald es eine echte Veröffentlichung gibt, meldet Ihnen
Hilfe > Nach Updates suchen, wenn eine neuere verfügbar ist.

## Entwicklungsumgebung einrichten

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Erfordert die Systempakete zum Bauen von PyGObject: `libcairo2-dev`, `libgirepository-2.0-dev`,
`libgtk-3-dev`.

## Tests ausführen

```
.venv/bin/pytest
```
