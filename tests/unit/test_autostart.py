"""remove_legacy_autostart_entry (task #180): cleans up the stale,
pre-task-#141 XDG autostart .desktop entry a previous version of
this app wrote directly (see autostart.py's own module docstring for
why that mechanism was replaced by a systemd --user service). Left
behind on any install that had autostart enabled before that
migration, it races orcshot.service at every boot - see BACKLOG.md's
resolved #180 entry for the full live-reproduced symptom.
"""

from pathlib import Path

from orcshot.autostart import remove_legacy_autostart_entry


class TestRemoveLegacyAutostartEntry:
    def test_removes_an_existing_stale_entry(self, tmp_path: Path):
        autostart_dir = tmp_path / "autostart"
        autostart_dir.mkdir()
        stale_entry = autostart_dir / "orcshot.desktop"
        stale_entry.write_text("[Desktop Entry]\nExec=/usr/bin/orcshot\n")

        remove_legacy_autostart_entry(config_home=tmp_path)

        assert not stale_entry.exists()

    def test_is_a_no_op_when_no_stale_entry_exists(self, tmp_path: Path):
        # Must not raise just because the directory (or file) was
        # never created - the common case on any install that never
        # had the old .desktop-writing mechanism at all.
        remove_legacy_autostart_entry(config_home=tmp_path)

    def test_leaves_other_files_in_the_autostart_directory_alone(self, tmp_path: Path):
        autostart_dir = tmp_path / "autostart"
        autostart_dir.mkdir()
        unrelated_entry = autostart_dir / "some-other-app.desktop"
        unrelated_entry.write_text("[Desktop Entry]\nExec=/usr/bin/some-other-app\n")

        remove_legacy_autostart_entry(config_home=tmp_path)

        assert unrelated_entry.exists()
