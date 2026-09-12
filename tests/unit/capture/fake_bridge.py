"""A stand-in for capture.shell_bridge.ShellBridge for the capture
modules' tests: records requests, answers with a canned result or
error. Installed via the fake_bridge fixture in conftest-less style -
each test file imports what it needs from here."""

from orcshot.capture import shell_bridge


class FakeBridge:
    def __init__(self, capabilities=(), result=None, error=None):
        self.capabilities = frozenset(capabilities)
        self.calls = []
        self._result, self._error = result, error

    def has(self, kind):
        return kind in self.capabilities

    def request(self, kind, params=None, timeout_ms=5000):
        self.calls.append((kind, params))
        if self._error:
            raise self._error
        return self._result

    def request_async(self, kind, params, on_result, on_error, timeout_ms=None):
        if not self.has(kind):
            raise shell_bridge.ShellUnavailable(kind)
        self.calls.append((kind, params, on_result, on_error))
        return len(self.calls)


def install(monkeypatch, **kw):
    bridge = FakeBridge(**kw)
    monkeypatch.setattr(shell_bridge, "_bridge", bridge)
    return bridge
