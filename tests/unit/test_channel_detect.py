from orcshot.channel_detect import detect_channel


def test_detect_channel_snap():
    assert detect_channel({"SNAP": "/snap/orcshot/x1", "SNAP_NAME": "orcshot"}) == "snap"


def test_detect_channel_flatpak_via_env_var():
    assert detect_channel({"FLATPAK_ID": "org.orcshot.Orcshot"}) == "flatpak"


def test_detect_channel_deb_when_neither_present():
    assert detect_channel({}, path_exists=lambda p: False) == "deb"


def test_detect_channel_snap_takes_priority_over_flatpak_if_both_set():
    # Not a real scenario (a process can't be both), but pins the
    # function's own tie-breaking behavior rather than leaving it
    # undefined.
    env = {"SNAP": "/snap/orcshot/x1", "SNAP_NAME": "orcshot", "FLATPAK_ID": "org.orcshot.Orcshot"}
    assert detect_channel(env) == "snap"
