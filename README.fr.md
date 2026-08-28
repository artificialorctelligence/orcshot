[English](README.md) | [Español](README.es.md) | **Français** | [Deutsch](README.de.md) | [Українська](README.uk.md) | [हिन्दी](README.hi.md) | [日本語](README.ja.md) | [中文](README.zh.md)

# Orcshot

Un portage Linux de [Greenshot](https://getgreenshot.org/), conçu comme un portage comportemental
fidèle en Python + GTK3 - sans affiliation avec le projet Greenshot ni approbation de sa part. Il n'a
non plus aucun lien avec le projet [Apache ORC](https://orc.apache.org/) : la coïncidence sur « Orc »
est fortuite. Voir [REQUIREMENTS.md](REQUIREMENTS.md) pour la portée complète, les priorités de
plateformes et les décisions d'architecture.

## Installation

**Depuis le PPA** (Ubuntu 24.04 LTS, Ubuntu 26.04 LTS, et les distributions basées sur Ubuntu comme
Linux Mint) :

```
sudo add-apt-repository ppa:artificialorctelligence/orcshot
sudo apt update
sudo apt install orcshot
```

**Depuis les sources** (toute autre distribution basée sur Debian, ou si vous préférez le compiler
vous-même) :

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

Dans les deux cas, c'est un paquet Debian ordinaire - une fois installé, il se comporte comme
n'importe quelle autre application (il apparaît dans votre menu d'applications, se désinstalle
proprement avec `apt remove`, etc.). Vérifié sur : Linux Mint (Cinnamon), Ubuntu 24.04 LTS et Ubuntu
26.04 LTS.

Au premier lancement d'Orcshot, celui-ci vous propose de configurer les raccourcis clavier de capture
et le lancement à l'ouverture de session (Cinnamon uniquement pour les raccourcis - voir la note dans
`debian/control` pour les autres environnements de bureau). Vous pouvez y revenir à tout moment
depuis les Préférences de l'icône de la zone de notification.

Pour mettre à jour plus tard : `sudo apt update && sudo apt upgrade` (installation via le PPA), ou
récupérez les dernières modifications et recompilez/réinstallez (depuis les sources) - une
réinstallation ne touche jamais à vos raccourcis clavier, à votre réglage de lancement au démarrage
ni à aucune autre préférence, ceux-ci résident dans votre propre configuration utilisateur, pas dans
le paquet. Aide > Rechercher des mises à jour vous indiquera aussi quand une version plus récente est
disponible.

## Environnement de développement

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Nécessite les paquets système permettant de compiler PyGObject : `libcairo2-dev`,
`libgirepository-2.0-dev`, `libgtk-3-dev`.

## Lancer les tests

```
.venv/bin/pytest
```
