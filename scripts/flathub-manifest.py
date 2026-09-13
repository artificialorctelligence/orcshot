#!/usr/bin/env python3
"""Derive the Flathub manifest from the repo manifest.

Flathub builds from a tag+commit of the upstream repo; the repo's own
org.orcshot.Orcshot.yaml builds the working tree (type: dir) so local and CI
builds test what a PR changes. This swaps exactly that one source block and
nothing else (spec 2026-09-12 decision 5). Output goes to stdout.

Comments do not survive; the repo manifest remains the documented one.

    scripts/flathub-manifest.py v0.4.0 > /path/to/flathub/org.orcshot.Orcshot.yaml
"""
import argparse
import subprocess
import sys

try:
    import yaml
except ImportError:  # not a project dependency; say so instead of regex-editing YAML
    sys.exit("flathub-manifest.py needs PyYAML (python3-yaml / pip install pyyaml)")

UPSTREAM = "https://github.com/artificialorctelligence/orcshot.git"
MODULE = "orcshot"


class ManifestShapeError(ValueError):
    """The manifest is not the one shape this script knows how to rewrite."""


def derive(manifest_text: str, tag: str, commit: str) -> str:
    doc = yaml.safe_load(manifest_text)
    modules = [m for m in doc.get("modules", []) if isinstance(m, dict) and m.get("name") == MODULE]
    if len(modules) != 1:
        raise ManifestShapeError(f"expected exactly one module named {MODULE!r}, found {len(modules)}")
    dirs = [s for s in modules[0].get("sources", []) if isinstance(s, dict) and s.get("type") == "dir"]
    if len(dirs) != 1:
        raise ManifestShapeError(f"expected exactly one 'type: dir' source in {MODULE!r}, found {len(dirs)}")
    dirs[0].clear()
    dirs[0].update({"type": "git", "url": UPSTREAM, "tag": tag, "commit": commit})
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=1000)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tag")
    ap.add_argument("--manifest", default="org.orcshot.Orcshot.yaml")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args()
    try:
        commit = subprocess.check_output(["git", "-C", a.repo, "rev-list", "-n1", a.tag], text=True).strip()
    except subprocess.CalledProcessError:
        sys.exit(f"tag {a.tag!r} not found in {a.repo} - push/fetch the release tag first")
    with open(a.manifest, encoding="utf-8") as f:
        text = f.read()
    try:
        sys.stdout.write(derive(text, a.tag, commit))
    except ManifestShapeError as e:
        sys.exit(f"{a.manifest}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
