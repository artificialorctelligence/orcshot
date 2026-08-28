[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | **Deutsch** | [Українська](README.uk.md) | [हिन्दी](README.hi.md) | [日本語](README.ja.md) | [中文](README.zh.md)

# Orcshot

**Schnellinstallation** (Ubuntu 24.04/26.04, Mint und andere Ubuntu-basierte Distributionen):
```bash
sudo add-apt-repository ppa:artificialorctelligence/orcshot
sudo apt update && sudo apt install orcshot
```

Eine Linux-Portierung von [Greenshot](https://getgreenshot.org/), umgesetzt als originalgetreue
Verhaltensportierung in Python + GTK3 – nicht mit dem Greenshot-Projekt verbunden und nicht von ihm
unterstützt. Es steht außerdem in keiner Verbindung zum Projekt [Apache ORC](https://orc.apache.org/)
– die Übereinstimmung bei „Orc" ist zufällig. Den vollständigen Umfang, die Plattformprioritäten und
die Architekturentscheidungen finden Sie in [REQUIREMENTS.md](REQUIREMENTS.md).

## Installation

**Über das PPA** (Ubuntu 24.04 LTS, Ubuntu 26.04 LTS und Ubuntu-basierte Distributionen wie Linux
Mint):

```
sudo add-apt-repository ppa:artificialorctelligence/orcshot
sudo apt update
sudo apt install orcshot
```

**Aus dem Quellcode** (jede andere Debian-basierte Distribution, oder wenn Sie es lieber selbst
bauen möchten):

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

So oder so ist es ein ganz normales Debian-Paket – einmal installiert, verhält es sich wie jede
andere Anwendung (es erscheint im Anwendungsmenü, lässt sich mit `apt remove` sauber deinstallieren
usw.). Getestet auf: Linux Mint (Cinnamon), Ubuntu 24.04 LTS und Ubuntu 26.04 LTS.

Beim ersten Start bietet Orcshot an, Tastenkürzel für Aufnahmen und den Start bei der Anmeldung
einzurichten (die Tastenkürzel nur unter Cinnamon – für andere Desktop-Umgebungen siehe den Hinweis
in `debian/control`). Sie können das jederzeit über die Einstellungen im Tray-Symbol erneut aufrufen.

Für spätere Aktualisierungen: `sudo apt update && sudo apt upgrade` (bei PPA-Installation), oder die
neuesten Änderungen holen und neu bauen/installieren (aus dem Quellcode) – eine Neuinstallation
rührt Ihre Tastenbelegungen, die Autostart-Einstellung und alle anderen Einstellungen niemals an,
die liegen in Ihrer eigenen Benutzerkonfiguration, nicht im Paket. Hilfe > Nach Updates suchen meldet
Ihnen ebenfalls, wenn eine neuere Version verfügbar ist.

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
