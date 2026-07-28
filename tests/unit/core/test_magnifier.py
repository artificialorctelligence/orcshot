"""Pure sizing/positioning math behind the region-select magnifier
loupe (ui/region_select.py). Ported from the Windows source's
CaptureForm.cs (DrawZoom/VerifyZoomAnimation) - see that module's
docstring for the exact line references this was traced from.
"""

from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.magnifier import magnifier_diameter, magnifier_offset, magnifier_source_rect


class TestMagnifierDiameter:
    def test_is_a_fifth_of_the_smaller_screen_dimension(self):
        assert magnifier_diameter(1000, 800) == 160

    def test_uses_the_smaller_of_width_and_height(self):
        assert magnifier_diameter(1920, 1080) == 216

    def test_rounds_down_to_a_multiple_of_4(self):
        # 999 // 5 == 199, which isn't a multiple of 4 (199 % 4 == 3)
        assert magnifier_diameter(999, 999) == 196
        assert magnifier_diameter(999, 999) % 4 == 0


class TestMagnifierSourceRect:
    def test_is_centered_on_the_cursor(self):
        rect = magnifier_source_rect((100, 100), size=25)
        # matches the source's integer-division centering exactly:
        # cursor - size//2, sized size x size
        assert rect == Rect(88, 88, 113, 113)

    def test_default_size_is_25(self):
        rect = magnifier_source_rect((50, 50))
        assert rect.width == 25
        assert rect.height == 25


SCREEN = Rect(0, 0, 1000, 800)


class TestMagnifierOffset:
    def test_prefers_bottom_right_of_cursor_when_it_fits(self):
        offset = magnifier_offset((500, 400), SCREEN, avoid_rect=None, diameter=160, gap=20)
        assert offset == (20, 20)

    def test_falls_back_to_bottom_left_when_bottom_right_goes_off_screen(self):
        # cursor near the right edge - bottom-right quadrant would
        # spill past the screen's right edge
        offset = magnifier_offset((950, 400), SCREEN, avoid_rect=None, diameter=160, gap=20)
        assert offset == (-20 - 160, 20)

    def test_falls_back_to_top_right_when_bottom_is_off_screen(self):
        # cursor near the bottom edge - both bottom quadrants spill
        # past the screen's bottom edge, but the cursor is still far
        # enough from the right edge for top-right to fit
        offset = magnifier_offset((500, 780), SCREEN, avoid_rect=None, diameter=160, gap=20)
        assert offset == (20, -20 - 160)

    def test_falls_back_to_top_left_when_bottom_and_right_are_off_screen(self):
        offset = magnifier_offset((980, 780), SCREEN, avoid_rect=None, diameter=160, gap=20)
        assert offset == (-20 - 160, -20 - 160)

    def test_skips_a_quadrant_that_overlaps_the_avoid_rect(self):
        cursor = (500, 400)
        bottom_right = Rect(cursor[0] + 20, cursor[1] + 20, cursor[0] + 20 + 160, cursor[1] + 20 + 160)
        offset = magnifier_offset(cursor, SCREEN, avoid_rect=bottom_right, diameter=160, gap=20)
        assert offset != (20, 20)
        assert offset == (-20 - 160, 20)

    def test_allows_overlapping_the_avoid_rect_if_no_quadrant_is_both_on_screen_and_clear(self):
        # avoid_rect covering the whole screen - no quadrant can avoid
        # it, so the function must still return *something* on-screen
        # rather than nothing.
        offset = magnifier_offset((500, 400), SCREEN, avoid_rect=SCREEN, diameter=160, gap=20)
        assert offset == (20, 20)
