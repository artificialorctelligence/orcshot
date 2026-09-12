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
