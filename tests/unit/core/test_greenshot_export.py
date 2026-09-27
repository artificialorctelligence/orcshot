"""Task #124's NRBF export, verified two ways: (1) offline, byte-pattern
checks here (no VM/Windows dependency, so this runs in normal CI), and (2)
separately, live against real Greenshot's own BinaryFormatterHelper
whitelist binder on a real Windows 11 VM (not repeatable in CI - see
REQUIREMENTS.md's task #124 section for that trace, including the exact
values this test also checks).
"""
import struct

from orcshot.core.geometry import Rect
from orcshot.core.greenshot_export import rectangle_shape_to_greenshot_nrbf
from orcshot.core.shapes import RectangleShape, ShapeStyle


def test_declares_a_system_drawing_library_for_color_fields():
    # Regression test for a real bug caught live against the VM: Color
    # fields referenced library id 4 without ever emitting a BinaryLibrary
    # record declaring it - real Greenshot's deserializer rejected that
    # with "No assembly ID for object type '4 System.Drawing.Color'".
    shape = RectangleShape(bounds=Rect(0, 0, 10, 10), style=ShapeStyle())
    data = rectangle_shape_to_greenshot_nrbf(shape)
    assert b"System.Drawing, Version=4.0.0.0" in data
    assert b"Greenshot.Editor, Version=1.3.0.0" in data
    assert b"Greenshot.Base, Version=1.3.0.0" in data


def test_starts_with_a_valid_header_and_ends_with_message_end():
    shape = RectangleShape(bounds=Rect(0, 0, 10, 10), style=ShapeStyle())
    data = rectangle_shape_to_greenshot_nrbf(shape)
    assert data[0] == 0  # SerializedStreamHeader
    assert data[-1] == 11  # MessageEnd


def test_bounds_and_style_values_appear_correctly_in_the_stream():
    # Same values this project's own REQUIREMENTS.md task #124 section
    # documents as live-verified against real Greenshot's deserializer.
    shape = RectangleShape(
        bounds=Rect(10, 20, 110, 70),
        style=ShapeStyle(line_thickness=3, line_color=(200, 30, 30, 255), fill_color=(0, 0, 0, 0), shadow=True),
    )
    data = rectangle_shape_to_greenshot_nrbf(shape)

    # left/top/width/height are 4 consecutive Int32 values (10, 20, 100, 50)
    needle = struct.pack("<iiii", 10, 20, 100, 50)
    assert needle in data

    # LINE_THICKNESS's boxed Int32 value (MemberPrimitiveTyped code 8, type
    # tag 8=Int32, value 3)
    assert bytes([8, 8]) + struct.pack("<i", 3) in data

    # LINE_COLOR packed ARGB(255,200,30,30) as the unsigned Int64 'value' field
    argb = (255 << 24) | (200 << 16) | (30 << 8) | 30
    assert struct.pack("<q", argb) in data

    # FILL_COLOR packed ARGB(0,0,0,0)
    assert struct.pack("<q", 0) in data

    # SHADOW's boxed True (MemberPrimitiveTyped code 8, type tag 1=Boolean, value 1)
    assert bytes([8, 1, 1]) in data


# --------------------------------------------------------------------
# Wire-format pinning (BACKLOG #220 mutation debt)
#
# This module had 124 surviving mutants - the largest single pool in the
# project - and they were almost all NRBF member names and primitive
# constants: "knownColor" -> "knowncolor", state 2 -> 3, the Color
# member list reordered. The three tests above check that a few values
# *appear somewhere* in the stream, which no amount of renaming or
# reordering disturbs.
#
# That matters more here than the line count suggests. This is not
# internal state: it is a wire format read by real Greenshot on Windows,
# and REQUIREMENTS.md's task #124 section records it being verified live
# against that deserializer's own whitelist binder on a Windows 11 VM.
# A silently changed member name produces a file that this project's
# tests are perfectly happy with and that real Greenshot rejects - which
# is exactly the bug the "No assembly ID for object type" regression
# above already was once.
# --------------------------------------------------------------------

from pathlib import Path

import pytest

from orcshot.core.greenshot_export import _IdAllocator
from orcshot.core.nrbf import length_prefixed_string

GOLDEN = Path(__file__).parent.parent.parent / "fixtures" / "rectangle_shape_exported.nrbf"

# The exact shape the golden was produced from. Deliberately asymmetric
# in every field - distinct bounds, a line colour whose channels are all
# different, and a fill colour that is not the line colour - so a swapped
# pair or a copied field changes the bytes.
GOLDEN_SHAPE = RectangleShape(
    bounds=Rect(12, 34, 120, 80),
    style=ShapeStyle(line_thickness=3, line_color=(200, 30, 40, 255), fill_color=(1, 2, 3, 4), shadow=True),
)


def test_the_serialised_stream_is_byte_for_byte_unchanged():
    """The format is a contract with a program we do not control.

    Any difference here is a change to what real Greenshot would be asked
    to read, so it must not happen by accident. But not every difference
    needs the same answer, and it is worth being precise rather than
    sending someone to boot a Windows VM over a renumbered object id:

    - **Needs re-verification on the windows11 VM** before the golden is
      regenerated: class names, library declarations, member names,
      member order, type enums, and the state constant. These are what
      real Greenshot's BinaryFormatterHelper whitelist binder binds
      against - the same path Object > Load Objects uses. That round trip
      is how the missing-BinaryLibrary bug ("No assembly ID for object
      type '4 System.Drawing.Color'") was caught; see REQUIREMENTS.md's
      task #124 section.
    - **Does not**: object ids. _IdAllocator's own docstring records,
      verified live, that any unique-per-stream ids are valid NRBF.
    - **Does not**: the payload values (bounds, colours, thickness).
      Those are data, not format.

    Note also that task #124 is PARKED and nothing in src/ calls this
    exporter, so no user-reachable behaviour depends on it today. That is
    a reason to keep the golden cheap to regenerate, not a reason to let
    the format drift unnoticed.

    Regenerate with:
        python3 -c "import sys; sys.path.insert(0,'src'); \\
          from orcshot.core.greenshot_export import rectangle_shape_to_greenshot_nrbf as f; \\
          from orcshot.core.shapes import RectangleShape, ShapeStyle; \\
          from orcshot.core.geometry import Rect; \\
          open('tests/fixtures/rectangle_shape_exported.nrbf','wb').write(f(RectangleShape( \\
            bounds=Rect(12,34,120,80), \\
            style=ShapeStyle(line_thickness=3, line_color=(200,30,40,255), \\
                             fill_color=(1,2,3,4), shadow=True))))"
    """
    assert rectangle_shape_to_greenshot_nrbf(GOLDEN_SHAPE) == GOLDEN.read_bytes()


def test_the_export_is_deterministic():
    """Two exports of the same shape must be identical, or the golden
    above would be untestable and a diff would mean nothing.
    """
    assert rectangle_shape_to_greenshot_nrbf(GOLDEN_SHAPE) == rectangle_shape_to_greenshot_nrbf(GOLDEN_SHAPE)


class TestColorRecord:
    """System.Drawing.Color's four members, by name and by value.

    Real Greenshot reads .R/.G/.B/.A back regardless of which encoding
    produced them, but it reads them *by member name* off a class it
    matched by name - so these strings are load-bearing, and the exact
    spelling and order are what the deserializer binds against.
    """

    @pytest.mark.parametrize("member", ["name", "value", "knownColor", "state"])
    def test_each_member_name_is_written_exactly_as_spelled(self, member):
        data = rectangle_shape_to_greenshot_nrbf(GOLDEN_SHAPE)

        assert length_prefixed_string(member) in data

    def test_the_member_names_appear_in_declaration_order(self):
        """NRBF binds members positionally against the declared order, so
        a reordering is a different class, not a cosmetic change.
        """
        data = rectangle_shape_to_greenshot_nrbf(GOLDEN_SHAPE)
        positions = [data.index(length_prefixed_string(m)) for m in ("name", "value", "knownColor", "state")]

        assert positions == sorted(positions)

    def test_a_case_changed_member_name_is_not_present(self):
        """The mutants that survived were case changes - "knowncolor",
        "KNOWNCOLOR". .NET member binding is case-sensitive, so these are
        real breakage, not spelling preference.
        """
        data = rectangle_shape_to_greenshot_nrbf(GOLDEN_SHAPE)

        assert length_prefixed_string("knowncolor") not in data
        assert length_prefixed_string("KnownColor") not in data

    def test_the_colour_is_packed_argb_not_rgba(self):
        """(a << 24) | (r << 16) | (g << 8) | b. Every channel distinct so
        any swapped pair changes the value.
        """
        data = rectangle_shape_to_greenshot_nrbf(
            RectangleShape(
                bounds=Rect(0, 0, 10, 10),
                style=ShapeStyle(line_color=(200, 30, 40, 255), fill_color=(0, 0, 0, 0)),
            )
        )
        expected = (255 << 24) | (200 << 16) | (30 << 8) | 40

        assert struct.pack("<q", expected) in data

    def test_the_alpha_channel_reaches_the_high_byte(self):
        """A half-transparent fill must differ from an opaque one in the
        top byte, which a mutant dropping the << 24 would not manage.
        """
        translucent = rectangle_shape_to_greenshot_nrbf(
            RectangleShape(bounds=Rect(0, 0, 10, 10), style=ShapeStyle(fill_color=(10, 20, 30, 128)))
        )
        opaque = rectangle_shape_to_greenshot_nrbf(
            RectangleShape(bounds=Rect(0, 0, 10, 10), style=ShapeStyle(fill_color=(10, 20, 30, 255)))
        )

        assert struct.pack("<q", (128 << 24) | (10 << 16) | (20 << 8) | 30) in translucent
        assert struct.pack("<q", (255 << 24) | (10 << 16) | (20 << 8) | 30) in opaque

    def test_the_state_constant_is_argbvalue_and_knowncolor_is_zero(self):
        """state=2 is STATE_ARGBVALUE, which is what tells real Greenshot
        to read the explicit value rather than a named colour; knownColor
        must be 0 because no named colour is being claimed. Both were
        mutated and both survived.
        """
        data = rectangle_shape_to_greenshot_nrbf(GOLDEN_SHAPE)

        # Int16 knownColor=0 immediately followed by Int16 state=2, as
        # _write_color emits them back to back after the Int64 value.
        assert struct.pack("<hh", 0, 2) in data
        assert struct.pack("<hh", 0, 3) not in data


class TestIdAllocator:
    def test_ids_start_at_two(self):
        """1 is the root object's own id, so allocation starts after it."""
        assert _IdAllocator()() == 2

    def test_each_id_is_one_more_than_the_last(self):
        allocate = _IdAllocator()

        assert [allocate() for _ in range(4)] == [2, 3, 4, 5]

    def test_every_id_in_a_stream_is_unique(self):
        """The docstring's actual requirement: any unique-per-stream ids
        are valid NRBF. Uniqueness is the contract, not the numbering.
        """
        allocate = _IdAllocator()
        ids = [allocate() for _ in range(50)]

        assert len(set(ids)) == 50

    def test_a_custom_start_is_honoured(self):
        assert _IdAllocator(start=10)() == 10
