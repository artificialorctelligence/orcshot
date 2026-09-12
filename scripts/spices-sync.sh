#!/usr/bin/env bash
# Syncs the Cinnamon applet into a local checkout of the cinnamon-spices-applets fork in
# the layout Spices requires (UUID/files/UUID/...), sets metadata.json's version to the
# app version, and runs Mint's own validator. Usage: scripts/spices-sync.sh <fork-checkout>
# Spec: docs/superpowers/specs/2026-09-11-snap-compliant-extension-delivery-design.md §5.
set -euo pipefail
FORK="${1:?path to the cinnamon-spices-applets fork checkout}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UUID="orcshot-tray@orcshot.org"   # the applet keeps its own UUID; orcshot@orcshot.org is the GNOME extension
SRC="$ROOT/src/orcshot/resources/cinnamon-applets/$UUID"
DEST="$FORK/$UUID/files/$UUID"
VERSION="$(dpkg-parsechangelog -l"$ROOT/debian/changelog" --show-field Version | sed 's/-[^-]*$//')"
test -x "$FORK/validate-spice" || { echo "not a cinnamon-spices-applets checkout: $FORK" >&2; exit 1; }
mkdir -p "$DEST"
rsync -a --delete "$SRC/" "$DEST/"
python3 - "$DEST/metadata.json" "$VERSION" <<'PY'
import json, sys
path, version = sys.argv[1], sys.argv[2]
meta = json.load(open(path))
meta["version"] = version
with open(path, "w") as f:
    json.dump(meta, f, indent=2)
    f.write("\n")
PY
for f in info.json screenshot.png README.md; do
  test -e "$FORK/$UUID/$f" || echo "missing $UUID/$f - required for the first submission" >&2
done
( cd "$FORK" && ./validate-spice "$UUID" )
echo "synced $UUID at version $VERSION into $FORK"
