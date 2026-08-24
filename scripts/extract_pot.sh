#!/bin/sh
# i18n phase 1: dev-only string extraction, not part of the packaged
# build (see docs/superpowers/specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md's
# "Extraction tooling" section for why this deliberately doesn't touch
# debian/rules or debian/control).
set -e
cd "$(dirname "$0")/.."
mkdir -p po
xgettext --language=Python --keyword=_ --keyword=ngettext:1,2 \
    --force-po --output=po/orcshot.pot \
    $(find src/orcshot -name '*.py')
echo "Wrote po/orcshot.pot"
