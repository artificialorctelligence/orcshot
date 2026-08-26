#!/bin/sh
# Task #183 follow-up: dev-only string extraction for the Wayland
# Shell-native tray menu's own gettext domain ("orcshot-tray",
# metadata.json) - a separate GJS runtime inside gnome-shell itself,
# never covered by extract_pot.sh's Python-only xgettext sweep. Same
# "not part of the packaged build" scope as that script - regenerating
# the .pot is a manual dev step; only .po -> .mo compilation happens
# at build time (debian/rules).
set -e
cd "$(dirname "$0")/.."
mkdir -p po
xgettext --language=JavaScript --keyword=_ --from-code=UTF-8 --force-po --output=po/orcshot-tray.pot \
    "src/orcshot/resources/gnome-shell-extensions/orcshot-clipboard@orcshot.org/extension.js"
# xgettext leaves charset=CHARSET unfilled for JS input even with
# --from-code set (unlike the Python extraction above) - every file
# here really is UTF-8 (the extension source itself, same as
# everything else in this repo), so this just states that plainly
# instead of leaving the generic placeholder in place.
sed -i 's/charset=CHARSET/charset=UTF-8/' po/orcshot-tray.pot
echo "Wrote po/orcshot-tray.pot"
