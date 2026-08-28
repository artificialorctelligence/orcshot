[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | **Українська** | [हिन्दी](README.hi.md) | [日本語](README.ja.md) | [中文](README.zh.md)

# Orcshot

**Швидке встановлення** (Ubuntu 24.04/26.04, Mint та інші дистрибутиви на основі Ubuntu):
```bash
sudo add-apt-repository ppa:artificialorctelligence/orcshot
sudo apt update && sudo apt install orcshot
```

Порт [Greenshot](https://getgreenshot.org/) для Linux — точне відтворення його поведінки
на Python + GTK3; проєкт не пов’язаний із Greenshot і не схвалений ним. Проєкт також не пов’язаний
з [Apache ORC](https://orc.apache.org/) — збіг у слові «Orc» випадковий. Повний обсяг,
пріоритети платформ та архітектурні рішення описано в [REQUIREMENTS.md](REQUIREMENTS.md).

## Встановлення

**З PPA** (Ubuntu 24.04 LTS, Ubuntu 26.04 LTS та дистрибутиви на основі Ubuntu, як-от Linux Mint):

```
sudo add-apt-repository ppa:artificialorctelligence/orcshot
sudo apt update
sudo apt install orcshot
```

**Із джерельного коду** (будь-який інший дистрибутив на основі Debian, або якщо ви хочете зібрати
його самостійно):

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

У будь-якому разі це звичайний пакунок Debian — після встановлення він поводиться як будь-яка інша
програма (з’являється в меню програм, чисто видаляється командою `apt remove` тощо). Перевірено на:
Linux Mint (Cinnamon), Ubuntu 24.04 LTS та Ubuntu 26.04 LTS.

Під час першого запуску Orcshot запропонує налаштувати гарячі клавіші для захоплення та
автоматичний запуск під час входу в систему (гарячі клавіші — лише для Cinnamon; про інші
стільниці див. примітку у `debian/control`). Повернутися до цього можна будь-коли через
Параметри в меню піктограми в лотку.

Щоб оновитися пізніше: `sudo apt update && sudo apt upgrade` (встановлення через PPA) або отримайте
останні зміни та перезберіть/перевстановіть (із джерельного коду) — перевстановлення ніколи не
змінює ваші гарячі клавіші, налаштування автозапуску чи будь-які інші параметри, вони зберігаються
у вашій власній конфігурації користувача, а не в пакунку. Довідка > Перевірити наявність оновлень
також повідомить, коли з’явиться новіша версія.

## Налаштування середовища розробки

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Потребує системних пакунків для збирання PyGObject: `libcairo2-dev`, `libgirepository-2.0-dev`,
`libgtk-3-dev`.

## Запуск тестів

```
.venv/bin/pytest
```
