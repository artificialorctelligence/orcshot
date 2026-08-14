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
