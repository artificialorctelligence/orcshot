"""destinations_for_shell (task #113): the data the Wayland Shell-
native picker (extension.js's pickDestinationAsync) fetches over
D-Bus, so it shows the real, current destination list - including
ExternalCommand entries - instead of a hardcoded copy that drifts out
of sync with destination_picker.py's own _all_destinations().
"""

import logging

from orcshot.settings import ExternalCommand
from orcshot.ui.destination_picker import _should_reuse_editor, destinations_for_shell, ensure_output_directory


def test_includes_the_five_built_in_destinations(monkeypatch):
    monkeypatch.setattr("orcshot.ui.destination_picker.get_external_commands", lambda: [])
    monkeypatch.setattr("orcshot.ui.destination_picker.get_excluded_destinations", lambda: set())

    ids = [item_id for item_id, _label, _geometry_key in destinations_for_shell()]

    assert ids == ["clipboard", "save", "save_as", "edit", "print"]


class _FakeEditor:
    def __init__(self, is_modified: bool):
        self.is_modified = is_modified


class TestShouldReuseEditor:
    """BACKLOG #179's Reuse Editor setting - pure decision logic split
    out from _open_editor so it's unit-testable without a real GTK
    EditorWindow (see that function's own comment)."""

    def test_disabled_setting_never_reuses(self):
        assert _should_reuse_editor(False, _FakeEditor(is_modified=False)) is False

    def test_disabled_setting_never_reuses_even_with_no_editor(self):
        assert _should_reuse_editor(False, None) is False

    def test_enabled_but_no_editor_open_does_not_reuse(self):
        assert _should_reuse_editor(True, None) is False

    def test_enabled_with_modified_editor_does_not_reuse(self):
        assert _should_reuse_editor(True, _FakeEditor(is_modified=True)) is False

    def test_enabled_with_unmodified_editor_reuses(self):
        assert _should_reuse_editor(True, _FakeEditor(is_modified=False)) is True


def test_includes_a_configured_external_command(monkeypatch):
    monkeypatch.setattr(
        "orcshot.ui.destination_picker.get_external_commands",
        lambda: [ExternalCommand(name="My Tool", commandline="/usr/bin/my-tool")],
    )
    monkeypatch.setattr("orcshot.ui.destination_picker.get_excluded_destinations", lambda: set())

    entries = destinations_for_shell()

    assert ("external:My Tool", "My Tool", "external-command-symbolic") in entries


def test_excluded_destinations_are_left_out(monkeypatch):
    monkeypatch.setattr("orcshot.ui.destination_picker.get_external_commands", lambda: [])
    monkeypatch.setattr("orcshot.ui.destination_picker.get_excluded_destinations", lambda: {"print"})

    ids = [item_id for item_id, _label, _geometry_key in destinations_for_shell()]

    assert "print" not in ids


def test_geometry_key_matches_the_known_icon_for_a_built_in_destination(monkeypatch):
    monkeypatch.setattr("orcshot.ui.destination_picker.get_external_commands", lambda: [])
    monkeypatch.setattr("orcshot.ui.destination_picker.get_excluded_destinations", lambda: set())

    entries = dict((item_id, geometry_key) for item_id, _label, geometry_key in destinations_for_shell())

    assert entries["clipboard"] == "edit-copy-symbolic"


class TestEnsureOutputDirectory:
    """BACKLOG #210: quick Save must never write into the Flatpak
    sandbox's evaporating tmpfs. Both quick-save paths (tray/picker and
    the editor menu) go through this one function."""

    def test_returns_the_directory_when_reachable_without_asking(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orcshot.ui.destination_picker.get_output_directory", lambda: tmp_path)
        monkeypatch.setattr("orcshot.ui.destination_picker.output_directory_is_reachable", lambda d: True)
        asked = []
        monkeypatch.setattr("orcshot.ui.destination_picker._choose_location", lambda parent: asked.append(parent))

        assert ensure_output_directory(parent=None) == tmp_path
        assert asked == []

    def test_asks_once_and_returns_the_newly_chosen_directory(self, tmp_path, monkeypatch):
        chosen = tmp_path / "picked"
        current = {"dir": tmp_path / "tmpfs"}
        monkeypatch.setattr("orcshot.ui.destination_picker.get_output_directory", lambda: current["dir"])
        monkeypatch.setattr(
            "orcshot.ui.destination_picker.output_directory_is_reachable", lambda d: d == chosen,
        )

        def pick(parent):
            current["dir"] = chosen

        monkeypatch.setattr("orcshot.ui.destination_picker._choose_location", pick)

        assert ensure_output_directory(parent=None) == chosen

    def test_cancelled_picker_returns_none_and_warns(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setattr("orcshot.ui.destination_picker.get_output_directory", lambda: tmp_path / "tmpfs")
        monkeypatch.setattr("orcshot.ui.destination_picker.output_directory_is_reachable", lambda d: False)
        monkeypatch.setattr("orcshot.ui.destination_picker._choose_location", lambda parent: None)

        with caplog.at_level(logging.WARNING, logger="orcshot.ui.destination_picker"):
            assert ensure_output_directory(parent=None) is None
        assert "no reachable" in caplog.text


# --- ensure_output_directory (BACKLOG #210/#212/#216) ---------------
#
# The folder quick Save writes into. Its whole reason to exist is that
# three channels lie about writability in three different ways: under
# Flatpak $HOME is a tmpfs where the write succeeds and evaporates, under
# the snap any path no plug covers is denied by AppArmor, and on the .deb
# a read-only folder is just read-only. #216 is the sharpest of them - on
# an existing folder, mkdir(exist_ok=True) returns EEXIST before
# AppArmor's hook runs and os.access is not AppArmor-mediated, so both
# reported "writable" where a real write was refused. The probe is a real
# create-and-delete for that reason, and these tests hold that down.

import os  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from orcshot.settings import output_directory_is_reachable  # noqa: E402
from orcshot.ui.destination_picker import ensure_output_directory  # noqa: E402

cannot_drop_privileges = pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root ignores the permission bits these cases turn off",
)


class TestOutputDirectoryIsReachable:
    def test_an_ordinary_writable_directory_is_reachable(self, tmp_path):
        assert output_directory_is_reachable(tmp_path) is True

    def test_a_directory_that_does_not_exist_yet_is_created_and_reachable(self, tmp_path):
        target = tmp_path / "Pictures" / "Screenshots"

        assert output_directory_is_reachable(target) is True
        assert target.is_dir()

    @cannot_drop_privileges
    def test_an_existing_directory_that_cannot_be_written_is_not_reachable(self, tmp_path):
        """BACKLOG #216 in one assertion: mkdir(exist_ok=True) and
        os.access both call this folder fine. Only a real write does not.
        """
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        try:
            assert output_directory_is_reachable(locked) is False
        finally:
            locked.chmod(0o700)

    @cannot_drop_privileges
    def test_a_directory_whose_parent_cannot_be_written_is_not_reachable(self, tmp_path):
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        try:
            assert output_directory_is_reachable(locked / "Screenshots") is False
        finally:
            locked.chmod(0o700)

    def test_a_path_that_is_a_file_is_not_reachable(self, tmp_path):
        existing_file = tmp_path / "not-a-folder"
        existing_file.write_text("this is a file, not a directory")

        assert output_directory_is_reachable(existing_file) is False


class TestEnsureOutputDirectory:
    def test_a_reachable_folder_is_returned_without_prompting(self, tmp_path, monkeypatch):
        prompted = []
        monkeypatch.setattr("orcshot.ui.destination_picker.get_output_directory", lambda: tmp_path)
        monkeypatch.setattr(
            "orcshot.ui.destination_picker._choose_location", lambda parent: prompted.append(1)
        )

        assert ensure_output_directory() == tmp_path
        assert prompted == []

    def test_an_unreachable_folder_prompts_once_and_uses_what_was_chosen(self, tmp_path, monkeypatch):
        chosen = tmp_path / "chosen"
        chosen.mkdir()
        unreachable = tmp_path / "gone.txt"
        unreachable.write_text("a file, so never a reachable directory")
        answers = [unreachable, chosen]
        prompted = []
        monkeypatch.setattr("orcshot.ui.destination_picker.get_output_directory", lambda: answers.pop(0))
        monkeypatch.setattr(
            "orcshot.ui.destination_picker._choose_location", lambda parent: prompted.append(1)
        )

        assert ensure_output_directory() == chosen
        assert prompted == [1]

    def test_a_folder_still_unreachable_after_prompting_gives_up_rather_than_saving_into_nothing(
        self, tmp_path, monkeypatch
    ):
        """The point of returning None: Save must skip, not raise, and not
        write into a folder that will evaporate.
        """
        unreachable = tmp_path / "gone.txt"
        unreachable.write_text("a file, so never a reachable directory")
        monkeypatch.setattr("orcshot.ui.destination_picker.get_output_directory", lambda: unreachable)
        monkeypatch.setattr("orcshot.ui.destination_picker._choose_location", lambda parent: None)

        assert ensure_output_directory() is None

    def test_it_prompts_at_most_once_even_when_the_second_check_also_fails(self, tmp_path, monkeypatch):
        unreachable = tmp_path / "gone.txt"
        unreachable.write_text("a file")
        prompted = []
        monkeypatch.setattr("orcshot.ui.destination_picker.get_output_directory", lambda: unreachable)
        monkeypatch.setattr(
            "orcshot.ui.destination_picker._choose_location", lambda parent: prompted.append(1)
        )

        ensure_output_directory()

        assert prompted == [1]
