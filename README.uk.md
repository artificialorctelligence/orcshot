[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | **Українська** | [हिन्दी](README.hi.md) | [日本語](README.ja.md) | [中文](README.zh.md)

# Orcshot

Порт [Greenshot](https://getgreenshot.org/) для Linux — точне відтворення його поведінки
на Python + GTK3; проєкт не пов’язаний із Greenshot і не схвалений ним. Повний обсяг,
пріоритети платформ та архітектурні рішення описано в [REQUIREMENTS.md](REQUIREMENTS.md).

## Встановлення

Orcshot ще не має опублікованого випуску, тож наразі пакунок `.deb` доведеться зібрати та
встановити самотужки. Це звичайний пакунок Debian — після встановлення він поводиться як
будь-яка інша програма (з’являється в меню програм, чисто видаляється командою `apt remove`
тощо).

Перевірено на: Linux Mint (Cinnamon), Ubuntu 24.04 LTS та Ubuntu 26.04 LTS.

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

Під час першого запуску Orcshot запропонує налаштувати гарячі клавіші для захоплення та
автоматичний запуск під час входу в систему (гарячі клавіші — лише для Cinnamon; про інші
стільниці див. примітку у `debian/control`). Повернутися до цього можна будь-коли через
Параметри в меню піктограми в лотку.

Щоб оновитися пізніше: отримайте останні зміни, зберіть пакунок заново та перевстановіть
тією самою командою `apt install` вище (перевстановлення ніколи не змінює ваші гарячі
клавіші, налаштування автозапуску чи будь-які інші параметри — вони зберігаються у вашій
власній конфігурації користувача, а не в пакунку). Коли з’явиться справжній випуск, пункт
Довідка > Перевірити наявність оновлень повідомлятиме про появу новішої версії.

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
