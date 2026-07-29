"""The editor color-picker palette - pure generation logic. See
core/color_palette.py's module docstring for the Windows-source
citation this is ported from.
"""

from greenshot_linux.core.color_palette import (
    RECENT_COLORS_MAX,
    SHADES_PER_COLUMN,
    add_recent_color,
    color_palette_grid,
)


class TestColorPaletteGrid:
    def test_has_thirteen_columns(self):
        grid = color_palette_grid()
        assert len(grid) == 13

    def test_each_column_has_eleven_rows(self):
        grid = color_palette_grid()
        for column in grid:
            assert len(column) == SHADES_PER_COLUMN

    def test_first_row_of_every_column_is_black(self):
        grid = color_palette_grid()
        for column in grid:
            assert column[0] == (0, 0, 0, 255)

    def test_last_row_of_every_column_is_white(self):
        grid = color_palette_grid()
        for column in grid:
            assert column[-1] == (255, 255, 255, 255)

    def test_middle_row_is_the_pure_hue(self):
        grid = color_palette_grid()
        # column order matches ColorDialog.cs:68-94's literal sequence
        expected_hues = [
            (255, 0, 0), (255, 127, 0), (255, 255, 0), (127, 255, 0),
            (0, 255, 0), (0, 255, 127), (0, 255, 255), (0, 127, 255),
            (0, 0, 255), (127, 0, 255), (255, 0, 255), (255, 0, 127),
            (127, 127, 127),
        ]
        for column, hue in zip(grid, expected_hues):
            assert column[5] == (*hue, 255)

    def test_exact_red_column_matches_hand_computed_values(self):
        # verified by hand-tracing CreateColorButtonColumn's truncating
        # integer division exactly, not just spot-checked.
        grid = color_palette_grid()
        red_column = grid[0]
        assert red_column == [
            (0, 0, 0, 255), (51, 0, 0, 255), (102, 0, 0, 255), (153, 0, 0, 255), (204, 0, 0, 255),
            (255, 0, 0, 255),
            (255, 51, 51, 255), (255, 102, 102, 255), (255, 153, 153, 255), (255, 204, 204, 255),
            (255, 255, 255, 255),
        ]

    def test_all_colors_are_fully_opaque(self):
        grid = color_palette_grid()
        for column in grid:
            for color in column:
                assert color[3] == 255


class TestAddRecentColor:
    def test_new_color_is_inserted_at_the_front(self):
        result = add_recent_color([(1, 1, 1, 255)], (2, 2, 2, 255))
        assert result == [(2, 2, 2, 255), (1, 1, 1, 255)]

    def test_re_picking_an_existing_color_moves_it_to_the_front_not_duplicated(self):
        existing = [(1, 1, 1, 255), (2, 2, 2, 255), (3, 3, 3, 255)]
        result = add_recent_color(existing, (2, 2, 2, 255))
        assert result == [(2, 2, 2, 255), (1, 1, 1, 255), (3, 3, 3, 255)]

    def test_truncates_to_max_count(self):
        existing = [(i, i, i, 255) for i in range(RECENT_COLORS_MAX)]
        result = add_recent_color(existing, (99, 99, 99, 255))
        assert len(result) == RECENT_COLORS_MAX
        assert result[0] == (99, 99, 99, 255)
        assert result[-1] != (RECENT_COLORS_MAX - 1, RECENT_COLORS_MAX - 1, RECENT_COLORS_MAX - 1, 255)

    def test_does_not_modify_the_input_list(self):
        original = [(1, 1, 1, 255)]
        add_recent_color(original, (2, 2, 2, 255))
        assert original == [(1, 1, 1, 255)]

    def test_empty_list_starts_fresh(self):
        assert add_recent_color([], (5, 5, 5, 255)) == [(5, 5, 5, 255)]
