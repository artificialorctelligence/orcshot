"""Crop: canvas-level transforms, not drawn annotations.

Behavioral port of CropContainer's four modes. Ported as pure functions
(core/crop.py) rather than a Layer-participating shape, consistent with
how box_blur/pixelize/highlight_filter are pure functions: CropContainer
itself is IsUndoable => false and HasContextMenu => false, and
functionally it's a one-time "transform the whole canvas on confirm"
operation (Surface.ConfirmCrop), not something composited into the
image like an annotation.

The real behavioral distinction, easy to miss from the name alone: only
Default/AutoCrop crop *to* the selection (standard "keep this rect,
discard the rest"). Vertical/Horizontal crop the selection *out* —
remove the selected band and splice the remaining pieces back together,
closing the gap (e.g. cutting a sidebar strip out of a screenshot).
This is confirmed directly by the source's own enum doc comments, not
inferred from the Draw/HandleMouseMove code.

HandleMouseMove forces Vertical mode's rect to Top=0/Height=image.Height
(and Horizontal's to Left=0/Width=image.Width) — only one axis of the
rect is ever meaningful for those two modes. crop_out_vertical_strip and
crop_out_horizontal_strip take a full Rect for interface consistency
with the rest of this codebase, but only read the relevant axis, mirroring
that the other axis is never meaningful in the source either.

The semi-transparent "this will be removed" preview overlay Draw paints
is an editing-UI rendering concern, not part of the final transform —
not ported, consistent with every other rendering-only detail skipped
elsewhere in this codebase (font measurement, Bezier smoothing, exact
GDI+ path geometry).
"""

import numpy as np

from orcshot.core.crop import autocrop_rect, crop_out_horizontal_strip, crop_out_vertical_strip, crop_to_rect
from orcshot.core.geometry import Rect


def column_marked_image(width, height=1):
    """Each column x has pixel value (x, x, x, 255) — makes splice order
    directly verifiable by reading the marker back out."""
    image = np.zeros((height, width, 4), dtype=np.uint8)
    for x in range(width):
        image[:, x] = (x, x, x, 255)
    return image


def row_marked_image(height, width=1):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    for y in range(height):
        image[y, :] = (y, y, y, 255)
    return image


class TestCropToRect:
    def test_keeps_only_the_selected_rect(self):
        image = column_marked_image(10)
        result = crop_to_rect(image, Rect(3, 0, 7, 1))
        assert list(result[0, :, 0]) == [3, 4, 5, 6]

    def test_output_shape_matches_the_rect(self):
        image = np.zeros((20, 30, 4), dtype=np.uint8)
        result = crop_to_rect(image, Rect(5, 5, 15, 12))
        assert result.shape == (7, 10, 4)

    def test_rect_exceeding_bounds_is_clamped_to_the_image(self):
        image = column_marked_image(10)
        result = crop_to_rect(image, Rect(-5, 0, 100, 1))
        assert result.shape[1] == 10

    def test_rect_entirely_outside_the_image_yields_an_empty_result(self):
        image = column_marked_image(10)
        result = crop_to_rect(image, Rect(100, 100, 200, 200))
        assert result.size == 0

    def test_does_not_modify_the_input(self):
        image = column_marked_image(10)
        original = image.copy()
        crop_to_rect(image, Rect(2, 0, 5, 1))
        assert np.array_equal(image, original)


class TestCropOutVerticalStrip:
    def test_removes_the_column_band_and_splices_the_remainder(self):
        # Columns 0..9; removing [3,7) should leave 0,1,2,7,8,9 in order.
        image = column_marked_image(10)
        result = crop_out_vertical_strip(image, Rect(3, 0, 7, 1))
        assert list(result[0, :, 0]) == [0, 1, 2, 7, 8, 9]

    def test_output_width_shrinks_by_the_band_width_height_unchanged(self):
        image = np.zeros((20, 30, 4), dtype=np.uint8)
        result = crop_out_vertical_strip(image, Rect(5, 999, 15, -999))  # vertical axis ignored
        assert result.shape == (20, 20, 4)

    def test_removing_the_full_width_leaves_a_zero_width_image(self):
        image = column_marked_image(10)
        result = crop_out_vertical_strip(image, Rect(0, 0, 10, 1))
        assert result.shape[1] == 0

    def test_out_of_bounds_columns_are_clamped(self):
        image = column_marked_image(10)
        result = crop_out_vertical_strip(image, Rect(-5, 0, 3, 1))
        assert list(result[0, :, 0]) == [3, 4, 5, 6, 7, 8, 9]

    def test_does_not_modify_the_input(self):
        image = column_marked_image(10)
        original = image.copy()
        crop_out_vertical_strip(image, Rect(2, 0, 5, 1))
        assert np.array_equal(image, original)


class TestCropOutHorizontalStrip:
    def test_removes_the_row_band_and_splices_the_remainder(self):
        image = row_marked_image(10)
        result = crop_out_horizontal_strip(image, Rect(0, 3, 1, 7))
        assert list(result[:, 0, 0]) == [0, 1, 2, 7, 8, 9]

    def test_output_height_shrinks_by_the_band_height_width_unchanged(self):
        image = np.zeros((30, 20, 4), dtype=np.uint8)
        result = crop_out_horizontal_strip(image, Rect(999, 5, -999, 15))  # horizontal axis ignored
        assert result.shape == (20, 20, 4)

    def test_removing_the_full_height_leaves_a_zero_height_image(self):
        image = row_marked_image(10)
        result = crop_out_horizontal_strip(image, Rect(0, 0, 1, 10))
        assert result.shape[0] == 0

    def test_out_of_bounds_rows_are_clamped(self):
        image = row_marked_image(10)
        result = crop_out_horizontal_strip(image, Rect(0, -5, 1, 3))
        assert list(result[:, 0, 0]) == [3, 4, 5, 6, 7, 8, 9]


class TestAutocropRect:
    def _bordered_image(self, border_color=(255, 255, 255, 255), content_color=(10, 20, 30, 255)):
        image = np.zeros((20, 20, 4), dtype=np.uint8)
        image[:, :] = border_color
        image[5:15, 5:15] = content_color
        return image

    def test_finds_a_solid_uniform_border(self):
        image = self._bordered_image()
        rect = autocrop_rect(image)
        assert rect == Rect(5, 5, 15, 15)

    def test_applying_the_result_with_crop_to_rect_removes_the_border(self):
        image = self._bordered_image()
        rect = autocrop_rect(image)
        cropped = crop_to_rect(image, rect)
        assert cropped.shape == (10, 10, 4)
        assert np.all(cropped == (10, 20, 30, 255))

    def test_a_fully_uniform_image_has_nothing_to_crop(self):
        image = np.full((10, 10, 4), (1, 2, 3, 255), dtype=np.uint8)
        assert autocrop_rect(image) is None

    def test_difference_threshold_tolerates_near_matching_border_colors(self):
        image = self._bordered_image(border_color=(250, 250, 250, 255))
        image[0, 5] = (245, 245, 245, 255)  # within default difference of 10
        rect = autocrop_rect(image, difference=10)
        assert rect == Rect(5, 5, 15, 15)

    def test_zero_difference_requires_an_exact_match(self):
        image = self._bordered_image(border_color=(250, 250, 250, 255))
        image[0, 5] = (245, 245, 245, 255)
        rect = autocrop_rect(image, difference=0)
        # the stray pixel sits in row 0, so the top edge can't trim at
        # all under an exact-match requirement - but left/right/bottom,
        # whose scans don't include that pixel, still trim normally.
        assert rect == Rect(5, 0, 15, 15)

    def test_uses_the_majority_corner_color_when_one_corner_disagrees(self):
        # 3 of 4 corners are white, 1 (bottom-right) is black - the
        # majority (white) is used as the background hypothesis, not
        # the odd one out. Top/left, whose scans never touch the
        # anomalous pixel, trim all the way to the real content
        # boundary; bottom/right, whose full-width/height scans do
        # include it, can't trim past it - the documented limitation
        # of whole-row/column matching, not a bug in this test.
        image = self._bordered_image()
        image[19, 19] = (0, 0, 0, 255)
        rect = autocrop_rect(image)
        assert rect == Rect(5, 5, 20, 20)


# --- Property-based tests -------------------------------------------------

from hypothesis import given
from hypothesis import strategies as st

_dim = st.integers(min_value=1, max_value=50)
_coord = st.integers(min_value=-20, max_value=70)


@given(width=_dim, height=_dim, left=_coord, right=_coord)
def test_crop_out_vertical_strip_conserves_total_width(width, height, left, right):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    result = crop_out_vertical_strip(image, Rect(left, 0, right, 1))

    clamped_left = max(0, min(left, width))
    clamped_right = max(0, min(right, width))
    removed = max(0, clamped_right - clamped_left)

    assert result.shape[1] == width - removed
    assert result.shape[0] == height


@given(width=_dim, height=_dim, top=_coord, bottom=_coord)
def test_crop_out_horizontal_strip_conserves_total_height(width, height, top, bottom):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    result = crop_out_horizontal_strip(image, Rect(0, top, 1, bottom))

    clamped_top = max(0, min(top, height))
    clamped_bottom = max(0, min(bottom, height))
    removed = max(0, clamped_bottom - clamped_top)

    assert result.shape[0] == height - removed
    assert result.shape[1] == width


@given(width=_dim, height=_dim, left=_coord, top=_coord, right=_coord, bottom=_coord)
def test_crop_to_rect_output_never_exceeds_the_original_dimensions(width, height, left, top, right, bottom):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    result = crop_to_rect(image, Rect(left, top, right, bottom))
    assert result.shape[0] <= height
    assert result.shape[1] <= width
