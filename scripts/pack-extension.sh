#!/usr/bin/env bash
# Packs the GNOME Shell extension into the zip layout `gnome-extensions pack`
# produces, without needing GNOME Shell on this machine (the snap build
# container and the Mint host both lack it). Output:
#   <out>/orcshot@orcshot.org.shell-extension.zip   (default out: dist/)
# Used by CI (installed on the runner as a user would), by the EGO upload
# leaf in .orclab/publish/channels.yaml, and by the first EGO submission.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UUID="orcshot@orcshot.org"
SRC="$ROOT/src/orcshot/resources/gnome-shell-extensions/$UUID"
OUT="$(mkdir -p "${1:-$ROOT/dist}" && cd "${1:-$ROOT/dist}" && pwd)"   # absolute: the zip is written from inside the temp stage dir
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -r "$SRC/." "$STAGE/"
# Compile translations if the extension ever ships .po sources (it has
# none today: labels arrive already translated over D-Bus).
if [ -d "$STAGE/po" ]; then
  for po in "$STAGE"/po/*.po; do
    lang="$(basename "$po" .po)"
    mkdir -p "$STAGE/locale/$lang/LC_MESSAGES"
    msgfmt -o "$STAGE/locale/$lang/LC_MESSAGES/$UUID.mo" "$po"
  done
  rm -rf "$STAGE/po"
fi
python3 - "$STAGE/metadata.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
assert m["uuid"] == "orcshot@orcshot.org" and m["version-name"], "metadata.json incomplete"
PY
mkdir -p "$OUT"
rm -f "$OUT/$UUID.shell-extension.zip"
( cd "$STAGE" && zip -qr "$OUT/$UUID.shell-extension.zip" . -x '*.po' )
echo "$OUT/$UUID.shell-extension.zip"
