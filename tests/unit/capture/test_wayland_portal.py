"""Pure coverage for the parts of wayland_portal.py that don't need a
real D-Bus session or portal service - the actual request_screenshot()
round trip is only verified live (see REQUIREMENTS.md's Wayland
section), since it can block on a real permission dialog.
"""

import pytest

from greenshot_linux.capture.wayland_portal import (
    PortalRequestCancelled,
    PortalRequestFailed,
    _next_handle_token,
    _parse_response,
)


class TestNextHandleToken:
    def test_tokens_are_unique_across_calls(self):
        tokens = {_next_handle_token() for _ in range(10)}
        assert len(tokens) == 10

    def test_token_is_a_valid_dbus_object_path_element(self):
        token = _next_handle_token()
        assert all(c.isalnum() or c == "_" for c in token)
        assert not token[0].isdigit()


class TestParseResponse:
    def test_success_returns_the_uri(self):
        uri = _parse_response(0, {"uri": "file:///home/user/Pictures/Screenshot.png"})
        assert uri == "file:///home/user/Pictures/Screenshot.png"

    def test_cancelled_raises_portal_request_cancelled(self):
        with pytest.raises(PortalRequestCancelled):
            _parse_response(1, {})

    def test_other_failure_raises_portal_request_failed(self):
        with pytest.raises(PortalRequestFailed):
            _parse_response(2, {})
