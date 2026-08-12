"""Window filtering logic, ported from WindowDetails.IsTopLevel /
WindowDetails.IsVisible in the Windows source.

X11's _NET_CLIENT_LIST already excludes child windows and desktop/panel
chrome (the window manager curates it), which is why this port has no
equivalent of the Windows HasParent / IgnoreClasses("Progman","Dwm")
checks. What's left maps to _NET_WM_WINDOW_TYPE and is tested here,
independent of any X server.
"""

from orcshot.capture.window import WindowInfo, is_capturable
from orcshot.core.geometry import Rect


def window(
    title="Some Window",
    window_type="normal",
    bounds=None,
    is_minimized=False,
):
    return WindowInfo(
        window_id=1,
        title=title,
        class_name="some-app",
        bounds=bounds or Rect(0, 0, 800, 600),
        is_minimized=is_minimized,
        window_type=window_type,
        process_id=1234,
    )


class TestIsCapturable:
    def test_accepts_a_normal_window(self):
        assert is_capturable(window(window_type="normal"))

    def test_accepts_a_dialog(self):
        assert is_capturable(window(window_type="dialog"))

    def test_accepts_unknown_window_type(self):
        # Many ordinary apps never set _NET_WM_WINDOW_TYPE at all; treat
        # absence as "real", matching Greenshot's default-inclusive stance
        # (its filters are exclusions, not an allowlist).
        assert is_capturable(window(window_type="unknown"))

    def test_rejects_empty_title(self):
        # Ported directly from `window.Text.Length == 0`.
        assert not is_capturable(window(title=""))

    def test_rejects_zero_area_window(self):
        # Ported from `WindowRectangle.Size.Width * Height == 0`.
        zero_width = Rect(left=100, top=100, right=100, bottom=200)
        assert not is_capturable(window(bounds=zero_width))

    def test_accepts_a_minimized_normal_window(self):
        # GetTopLevelWindows requires Visible OR Iconic — minimized windows
        # are still real, capturable-in-principle windows for a picker
        # list; only genuinely gone/withdrawn windows are excluded.
        assert is_capturable(window(is_minimized=True))

    def test_rejects_chrome_window_types(self):
        # Ported from the WS_EX_TOOLWINDOW check plus
        # IgnoreClasses(Progman/Button/Dwm) — X11's equivalent signal is
        # _NET_WM_WINDOW_TYPE naming the window as desktop/panel chrome.
        chrome_types = [
            "desktop",
            "dock",
            "toolbar",
            "utility",
            "splash",
            "notification",
            "tooltip",
            "menu",
            "dropdown_menu",
            "popup_menu",
            "combo",
            "dnd",
        ]
        for window_type in chrome_types:
            assert not is_capturable(window(window_type=window_type)), window_type


# --- Property-based tests -------------------------------------------------
# Imports the real _CHROME_WINDOW_TYPES set (not a hardcoded duplicate)
# so these stay in sync with the implementation if that set ever changes.

from hypothesis import given
from hypothesis import strategies as st

from orcshot.capture.window import _CHROME_WINDOW_TYPES

_chrome_type = st.sampled_from(sorted(_CHROME_WINDOW_TYPES))
_non_chrome_type = st.sampled_from(["normal", "dialog", "unknown"])
_dim = st.integers(min_value=1, max_value=4_000)


@given(window_type=_chrome_type, title=st.text(min_size=1), w=_dim, h=_dim)
def test_chrome_types_are_never_capturable_regardless_of_other_fields(window_type, title, w, h):
    w = window(title=title, window_type=window_type, bounds=Rect(0, 0, w, h))
    assert not is_capturable(w)


@given(window_type=_non_chrome_type, title=st.text(min_size=1), w=_dim, h=_dim, minimized=st.booleans())
def test_non_chrome_types_with_a_title_and_area_are_always_capturable(
    window_type, title, w, h, minimized
):
    w = window(title=title, window_type=window_type, bounds=Rect(0, 0, w, h), is_minimized=minimized)
    assert is_capturable(w)


@given(window_type=_non_chrome_type, w=st.integers(0, 4_000), h=st.integers(0, 4_000))
def test_empty_title_is_never_capturable_regardless_of_type_or_size(window_type, w, h):
    w = window(title="", window_type=window_type, bounds=Rect(0, 0, w, h))
    assert not is_capturable(w)
