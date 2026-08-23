"""destinations_for_shell (task #113): the data the Wayland Shell-
native picker (extension.js's pickDestinationAsync) fetches over
D-Bus, so it shows the real, current destination list - including
ExternalCommand entries - instead of a hardcoded copy that drifts out
of sync with destination_picker.py's own _all_destinations().
"""

from orcshot.settings import ExternalCommand
from orcshot.ui.destination_picker import destinations_for_shell


def test_includes_the_five_built_in_destinations(monkeypatch):
    monkeypatch.setattr("orcshot.ui.destination_picker.get_external_commands", lambda: [])
    monkeypatch.setattr("orcshot.ui.destination_picker.get_excluded_destinations", lambda: set())

    ids = [item_id for item_id, _label, _geometry_key in destinations_for_shell()]

    assert ids == ["clipboard", "save", "save_as", "edit", "print"]


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
