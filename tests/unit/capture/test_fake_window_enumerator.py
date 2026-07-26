from greenshot_linux.capture.fake import FakeWindowEnumerator
from greenshot_linux.capture.window import WindowInfo
from greenshot_linux.core.geometry import Rect


def make_window(window_id, title="Window", window_type="normal", **overrides):
    defaults = dict(
        window_id=window_id,
        title=title,
        class_name="app",
        bounds=Rect(0, 0, 800, 600),
        is_minimized=False,
        window_type=window_type,
        process_id=100 + window_id,
    )
    defaults.update(overrides)
    return WindowInfo(**defaults)


def test_defaults_to_no_windows():
    assert FakeWindowEnumerator().list_windows() == []
    assert FakeWindowEnumerator().active_window() is None


def test_lists_the_given_windows():
    windows = [make_window(1, title="Editor"), make_window(2, title="Browser")]

    enumerator = FakeWindowEnumerator(windows=windows)

    assert list(enumerator.list_windows()) == windows


def test_filters_out_uncapturable_windows():
    real = make_window(1, title="Editor")
    chrome = make_window(2, title="", window_type="dock")

    enumerator = FakeWindowEnumerator(windows=[real, chrome])

    assert list(enumerator.list_windows()) == [real]


def test_active_window_is_settable_independently_of_the_list():
    editor = make_window(1, title="Editor")
    browser = make_window(2, title="Browser")

    enumerator = FakeWindowEnumerator(windows=[editor, browser], active=browser)

    assert enumerator.active_window() == browser


def test_active_window_defaults_to_none_even_with_windows_present():
    enumerator = FakeWindowEnumerator(windows=[make_window(1)])

    assert enumerator.active_window() is None
