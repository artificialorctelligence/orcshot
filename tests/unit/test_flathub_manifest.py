# tests/unit/test_flathub_manifest.py
"""scripts/flathub-manifest.py: the Flathub manifest is derived from the repo one by
swapping exactly one source block (spec 2026-09-12 decision 5)."""
import importlib.util
import pathlib

import pytest
import yaml

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "flathub-manifest.py"
spec = importlib.util.spec_from_file_location("flathub_manifest", SCRIPT)
fm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fm)

MANIFEST = """\
app-id: org.orcshot.Orcshot
runtime: org.gnome.Platform
runtime-version: '50'
finish-args:
  - --share=ipc
modules:
  - name: xapps
    buildsystem: meson
    sources:
      - type: git
        url: https://github.com/linuxmint/xapp.git
        tag: "3.2.2"
        commit: 913b2a2b441ec24daf3aa92e2863cc40e1c43650
  - name: orcshot
    buildsystem: simple
    build-commands:
      - pip3 install --prefix=/app .
    sources:
      - type: dir
        path: .
"""

TAG = "v0.4.0"
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def test_only_the_orcshot_source_changes():
    out = yaml.safe_load(fm.derive(MANIFEST, TAG, COMMIT))
    src = yaml.safe_load(MANIFEST)
    assert out["modules"][0] == src["modules"][0]          # xapps untouched
    orc_out, orc_src = out["modules"][1], src["modules"][1]
    assert orc_out["sources"] == [{
        "type": "git",
        "url": "https://github.com/artificialorctelligence/orcshot.git",
        "tag": TAG,
        "commit": COMMIT,
    }]
    orc_out.pop("sources"); orc_src.pop("sources")
    assert orc_out == orc_src                                # every other key of the module intact
    for key in ("app-id", "runtime", "runtime-version", "finish-args"):
        assert out[key] == src[key]


def test_refuses_a_manifest_without_exactly_one_dir_source():
    two_dirs = MANIFEST + "      - type: dir\n        path: ./again\n"
    with pytest.raises(fm.ManifestShapeError):
        fm.derive(two_dirs, TAG, COMMIT)
    no_orcshot = MANIFEST.replace("name: orcshot", "name: other")
    with pytest.raises(fm.ManifestShapeError):
        fm.derive(no_orcshot, TAG, COMMIT)
