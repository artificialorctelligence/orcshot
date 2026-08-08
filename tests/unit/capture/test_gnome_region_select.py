"""Pure coverage for gnome_region_select.py's PNG-decoding logic - the
D-Bus call itself needs a real GNOME/Wayland session with the
greenshot-linux-clipboard extension enabled and its GJS-side
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

from greenshot_linux.capture.gnome_clipboard import _encode_png
from greenshot_linux.capture.gnome_region_select import _decode_png


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
