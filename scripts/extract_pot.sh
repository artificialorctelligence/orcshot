#!/bin/sh
# i18n phase 1: dev-only string extraction, not part of the packaged
# build (see docs/superpowers/specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md's
# "Extraction tooling" section for why this deliberately doesn't touch
# debian/rules or debian/control).
set -e
cd "$(dirname "$0")/.."
# BACKLOG #204: optional output path. Defaults to the committed po/orcshot.pot,
# so running this by hand is unchanged - it exists so the test suite can extract
# to a temp file and compare, instead of overwriting the real file on every run
# and leaving `git status` dirty mid-release.
out="${1:-po/orcshot.pot}"
mkdir -p "$(dirname "$out")"
find src/orcshot -name '*.py' -print0 | sort -z | xargs -0 xgettext --language=Python \
    --keyword=_ --keyword=ngettext:1,2 --force-po --output="$out"
echo "Wrote $out"
