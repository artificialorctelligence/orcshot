"""destinations_for_shell (task #113): the data the Wayland Shell-
native picker (extension.js's pickDestinationAsync) fetches over
D-Bus, so it shows the real, current destination list - including
ExternalCommand entries - instead of a hardcoded copy that drifts out
of sync with destination_picker.py's own _all_destinations().
"""

from orcshot.settings import ExternalCommand
from orcshot.ui.destination_picker import _should_reuse_editor, destinations_for_shell


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
