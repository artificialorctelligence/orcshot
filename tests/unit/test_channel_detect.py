import shutil

from orcshot.channel_detect import detect_channel, install_bundled_extension_if_needed


def test_detect_channel_snap():
    assert detect_channel({"SNAP": "/snap/orcshot/x1", "SNAP_NAME": "orcshot"}) == "snap"


def test_detect_channel_flatpak_via_env_var():
    assert detect_channel({"FLATPAK_ID": "org.orcshot.Orcshot"}) == "flatpak"


def test_detect_channel_deb_when_neither_present(monkeypatch, tmp_path):
    monkeypatch.setattr("os.path.exists", lambda p: False)
    assert detect_channel({}) == "deb"


def test_detect_channel_snap_takes_priority_over_flatpak_if_both_set():
    # Not a real scenario (a process can't be both), but pins the
    # function's own tie-breaking behavior rather than leaving it
    # undefined.
    env = {"SNAP": "/snap/orcshot/x1", "SNAP_NAME": "orcshot", "FLATPAK_ID": "org.orcshot.Orcshot"}
    assert detect_channel(env) == "snap"


def test_install_copies_extension_files(tmp_path):
    bundled = tmp_path / "bundled" / "orcshot-tray@orcshot.org"
    bundled.mkdir(parents=True)
    (bundled / "extension.js").write_text("// real js")
    (bundled / "metadata.json").write_text("{}")
    dest_parent = tmp_path / "real-home" / "extensions"

    result = install_bundled_extension_if_needed("orcshot-tray@orcshot.org", bundled, dest_parent)

    assert result is True
    dest = dest_parent / "orcshot-tray@orcshot.org"
    assert (dest / "extension.js").read_text() == "// real js"
    assert (dest / "metadata.json").read_text() == "{}"


def test_install_is_idempotent_already_installed(tmp_path):
    bundled = tmp_path / "bundled" / "orcshot-tray@orcshot.org"
    bundled.mkdir(parents=True)
    (bundled / "extension.js").write_text("// v2")
    (bundled / "metadata.json").write_text("{}")
    dest_parent = tmp_path / "real-home" / "extensions"
    dest = dest_parent / "orcshot-tray@orcshot.org"
    dest.mkdir(parents=True)
    (dest / "extension.js").write_text("// already here, v1")

    result = install_bundled_extension_if_needed("orcshot-tray@orcshot.org", bundled, dest_parent)

    assert result is True
    # Already-present files are left alone, not overwritten - matches
    # this project's existing "never clobber something already
    # configured" precedent (e.g. hotkey_setup's conflict-aware writes).
    assert (dest / "extension.js").read_text() == "// already here, v1"


def test_install_returns_false_on_permission_error(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled" / "orcshot-tray@orcshot.org"
    bundled.mkdir(parents=True)
    (bundled / "extension.js").write_text("// real js")
    (bundled / "metadata.json").write_text("{}")
    dest_parent = tmp_path / "real-home" / "extensions"

    def _raise_permission_error(*a, **kw):
        raise PermissionError("personal-files not connected")

    monkeypatch.setattr(shutil, "copytree", _raise_permission_error)

    result = install_bundled_extension_if_needed("orcshot-tray@orcshot.org", bundled, dest_parent)

    assert result is False
