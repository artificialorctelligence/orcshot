[English](README.md) | **Español** | [Français](README.fr.md) | [Deutsch](README.de.md) | [Українська](README.uk.md) | [हिन्दी](README.hi.md) | [日本語](README.ja.md) | [中文](README.zh.md)

# Orcshot

Una adaptación a Linux de [Greenshot](https://getgreenshot.org/), desarrollada como una réplica fiel
de su comportamiento en Python + GTK3, sin afiliación con el proyecto Greenshot ni respaldo por su
parte. Consulte [REQUIREMENTS.md](REQUIREMENTS.md) para conocer el alcance completo, las prioridades
de plataforma y las decisiones de arquitectura.

## Instalación

Orcshot todavía no tiene una versión publicada, así que por ahora tendrá que compilar e instalar el
`.deb` usted mismo. Es un paquete Debian normal: una vez instalado, se comporta como cualquier otra
aplicación (aparece en el menú de aplicaciones, se desinstala limpiamente con `apt remove`, etc.).

Verificado en: Linux Mint (Cinnamon), Ubuntu 24.04 LTS y Ubuntu 26.04 LTS.

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

La primera vez que inicie Orcshot, le ofrecerá configurar los atajos de teclado de captura y el
inicio automático al iniciar sesión (los atajos solo en Cinnamon: consulte la nota en
`debian/control` para otros escritorios). Puede volver a esta configuración en cualquier momento
desde las Preferencias del icono de la bandeja.

Para actualizar más adelante: descargue los últimos cambios, vuelva a compilar y reinstale con el
mismo comando `apt install` de arriba (reinstalar nunca toca sus atajos de teclado, la opción de
inicio automático ni ninguna otra preferencia: estas residen en su propia configuración de usuario,
no en el paquete). Cuando exista una versión publicada de verdad, Ayuda > Buscar actualizaciones le
avisará cuando haya una más reciente disponible.

## Configuración del entorno de desarrollo

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Requiere paquetes del sistema para compilar PyGObject: `libcairo2-dev`, `libgirepository-2.0-dev`,
`libgtk-3-dev`.

## Ejecutar las pruebas

```
.venv/bin/pytest
```
