"""Editor canvas zoom - pure level-selection logic. See
core/zoom.py's module docstring for the Windows-source citation this
is ported from.
"""

from fractions import Fraction

from orcshot.core.zoom import ZOOM_LEVELS, best_fit_zoom, optimal_window_size, zoom_in, zoom_out, zoom_percent_label


class TestZoomIn:
    def test_steps_to_the_next_level_up(self):
        assert zoom_in(Fraction(1, 2)) == Fraction(2, 3)

    def test_from_actual_size_goes_to_200_percent(self):
        assert zoom_in(Fraction(1, 1)) == Fraction(2, 1)

    def test_at_the_top_level_stays_there(self):
        assert zoom_in(ZOOM_LEVELS[-1]) == ZOOM_LEVELS[-1]

    def test_a_value_between_two_levels_jumps_to_the_next_real_level(self):
        # e.g. after a Best Fit lands on an odd zoom value not in ZOOM_LEVELS
        assert zoom_in(Fraction(1, 3)) == Fraction(1, 2)


class TestZoomOut:
    def test_steps_to_the_next_level_down(self):
        assert zoom_out(Fraction(3, 4)) == Fraction(2, 3)

    def test_at_the_bottom_level_stays_there(self):
        assert zoom_out(ZOOM_LEVELS[0]) == ZOOM_LEVELS[0]

    def test_a_value_between_two_levels_drops_to_the_next_real_level_down(self):
        assert zoom_out(Fraction(9, 10)) == Fraction(3, 4)


class TestBestFitZoom:
    def test_picks_the_largest_level_that_fits(self):
        # a 500x500 image, 1100x1100 available: 200% (1000x1000) fits, 300% doesn't
        assert best_fit_zoom(500, 500, 1100, 1100) == Fraction(2, 1)

    def test_exact_fit_at_a_level_is_included(self):
        assert best_fit_zoom(500, 500, 1000, 1000) == Fraction(2, 1)

    def test_falls_back_to_the_smallest_level_if_nothing_fits(self):
        # even 25% of a huge image doesn't fit the tiny available space
        assert best_fit_zoom(100000, 100000, 200, 200) == ZOOM_LEVELS[0]

    def test_width_and_height_both_constrain(self):
        # wide-but-short available space: width would allow 300%, but
        # height only allows 100% - the smaller of the two wins.
        assert best_fit_zoom(400, 400, 5000, 450) == Fraction(1, 1)

    def test_content_smaller_than_available_still_only_goes_up_to_a_fixed_level(self):
        # tiny image, huge available space - capped at the top fixed
        # level (600%), not scaled arbitrarily large.
        assert best_fit_zoom(10, 10, 100000, 100000) == ZOOM_LEVELS[-1]


class TestOptimalWindowSize:
    def test_fits_comfortably_within_min_and_max(self):
        size = optimal_window_size(
            chrome_width=100, chrome_height=80, canvas_width=400, canvas_height=300,
            min_width=650, min_height=530, max_width=2560, max_height=1400,
        )
        # chrome+canvas (500x380) is below the minimum, so the minimum wins
        assert size == (650, 530)

    def test_grows_to_fit_a_larger_canvas(self):
        size = optimal_window_size(
            chrome_width=100, chrome_height=80, canvas_width=1000, canvas_height=800,
            min_width=650, min_height=530, max_width=2560, max_height=1400,
        )
        assert size == (1100, 880)

    def test_clamped_to_the_screen_work_area(self):
        size = optimal_window_size(
            chrome_width=100, chrome_height=80, canvas_width=5000, canvas_height=4000,
            min_width=650, min_height=530, max_width=2560, max_height=1400,
        )
        assert size == (2560, 1400)

    def test_width_and_height_are_clamped_independently(self):
        size = optimal_window_size(
            chrome_width=100, chrome_height=80, canvas_width=5000, canvas_height=300,
            min_width=650, min_height=530, max_width=2560, max_height=1400,
        )
        assert size == (2560, 530)


class TestZoomPercentLabel:
    def test_actual_size(self):
        assert zoom_percent_label(Fraction(1, 1)) == "100%"

    def test_two_thirds_rounds_to_a_whole_percent(self):
        assert zoom_percent_label(Fraction(2, 3)) == "67%"

    def test_quarter(self):
        assert zoom_percent_label(Fraction(1, 4)) == "25%"

    def test_six_hundred_percent(self):
        assert zoom_percent_label(Fraction(6, 1)) == "600%"
