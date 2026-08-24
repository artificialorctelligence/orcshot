from tests.unit._i18n_scan import scan_source


class TestScanSource:
    def test_flags_an_unwrapped_label_kwarg(self):
        source = 'Gtk.Label(label="Hello")\n'
        violations = scan_source(source)
        assert len(violations) == 1
        assert violations[0].line == 1

    def test_does_not_flag_an_already_wrapped_label(self):
        source = 'Gtk.Label(label=_("Hello"))\n'
        assert scan_source(source) == []

    def test_does_not_flag_a_call_outside_the_sink_list(self):
        source = 'subprocess.run(["echo", "Hello"])\n'
        assert scan_source(source) == []

    def test_respects_a_noqa_comment_on_the_same_line(self):
        source = 'dialog.set_program_name("Orcshot")  # noqa: i18n (proper noun)\n'
        assert scan_source(source) == []

    def test_flags_an_unwrapped_method_call_sink(self):
        source = 'widget.set_tooltip_text("Click to capture")\n'
        violations = scan_source(source)
        assert len(violations) == 1

    def test_flags_gio_notification_new(self):
        source = 'Gio.Notification.new("Update available")\n'
        violations = scan_source(source)
        assert len(violations) == 1
