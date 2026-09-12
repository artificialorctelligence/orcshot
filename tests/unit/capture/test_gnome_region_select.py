"""Pure coverage for gnome_region_select.py's PNG-decoding logic - the
D-Bus call itself needs a real GNOME/Wayland session with the
orcshot-clipboard extension enabled and its GJS-side
StartRegionSelect capability, only verified live (see REQUIREMENTS.md's
"Planned: Shell-side rewrite of the Wayland overlays" section, task
#77). Doesn't need a real display: GdkPixbuf's own encode/decode round
trip works headless, same as test_gnome_clipboard.py.

_encode_png (already covered by test_gnome_clipboard.py) doubles as
this test's fixture builder, since the extension itself is what
encodes on the real path - there's no separate encoder in this module
to test.
"""

import numpy as np

from orcshot.capture.gnome_clipboard import _encode_png
from orcshot.capture.gnome_region_select import decode_png as _decode_png


class TestDecodePng:
    def test_round_trips_dimensions(self):
        image = np.random.default_rng(0).integers(0, 256, size=(4, 6, 4), dtype=np.uint8)
        decoded = _decode_png(_encode_png(image))
        assert decoded.shape == (4, 6, 4)

    def test_round_trips_pixel_values(self):
        image = np.zeros((2, 2, 4), dtype=np.uint8)
        image[0, 0] = (255, 0, 0, 255)
        image[1, 1] = (0, 255, 0, 128)
        decoded = _decode_png(_encode_png(image))
        assert tuple(decoded[0, 0]) == (255, 0, 0, 255)
        assert tuple(decoded[1, 1]) == (0, 255, 0, 128)

    def test_returns_uint8_rgba_array(self):
        image = np.zeros((1, 1, 4), dtype=np.uint8)
        decoded = _decode_png(_encode_png(image))
        assert decoded.dtype == np.uint8
        assert decoded.shape[2] == 4


from orcshot.capture import shell_bridge
from orcshot.capture.gnome_region_select import start_region_select
from tests.unit.capture.fake_bridge import install as install_fake_bridge


def _png_2x3() -> bytes:
    return _encode_png(np.zeros((3, 2, 4), dtype=np.uint8))


class TestBridgePlumbing:
    def test_requests_with_magnifier_flag_and_decodes_result(self, monkeypatch):
        bridge = install_fake_bridge(monkeypatch, capabilities=["region-select"])
        monkeypatch.setattr("orcshot.capture.gnome_region_select.get_show_magnifier_while_selecting", lambda: True)
        got = []
        start_region_select(on_selected=lambda img, rect, dest: got.append((img.shape, rect, dest)),
                            on_cancelled=lambda: got.append("cancel"))
        kind, params, on_result, _ = bridge.calls[0]
        assert (kind, params) == ("region-select", {"showMagnifier": True})
        on_result({"ok": True, "destination": "editor", "pngBytes": _png_2x3(), "x": 5, "y": 6, "width": 2, "height": 3})
        assert got[0][0] == (3, 2, 4) and got[0][1].left == 5 and got[0][2] == "editor"

    def test_error_is_cancel(self, monkeypatch):
        bridge = install_fake_bridge(monkeypatch, capabilities=["region-select"])
        monkeypatch.setattr("orcshot.capture.gnome_region_select.get_show_magnifier_while_selecting", lambda: False)
        got = []
        start_region_select(on_selected=lambda *a: got.append("selected"), on_cancelled=lambda: got.append("cancel"))
        bridge.calls[0][3](shell_bridge.ShellRequestError("cancelled"))
        assert got == ["cancel"]

    def test_no_capability_is_cancel_immediately(self, monkeypatch):
        install_fake_bridge(monkeypatch)
        monkeypatch.setattr("orcshot.capture.gnome_region_select.get_show_magnifier_while_selecting", lambda: False)
        got = []
        start_region_select(on_selected=lambda *a: got.append("selected"), on_cancelled=lambda: got.append("cancel"))
        assert got == ["cancel"]
