"""Low-level MS-NRBF record-writing correctness - the exact record layout
(batched type-info, 7-bit varint length prefix, etc.) was independently
verified byte-for-byte against a real BinaryFormatter capture; see
core/nrbf.py's own module docstring and REQUIREMENTS.md's task #124
section for that trace.
"""
import struct

from orcshot.core.nrbf import Writer, length_prefixed_string


def test_length_prefixed_string_short():
    assert length_prefixed_string("AB") == b"\x02AB"


def test_length_prefixed_string_needs_multibyte_varint():
    long_string = "x" * 200
    encoded = length_prefixed_string(long_string)
    # 200 = 0b11001000 -> low 7 bits with continuation bit set, then 1
    assert encoded[:2] == bytes([0xC8, 0x01])
    assert encoded[2:] == long_string.encode("utf-8")


def test_header_matches_real_binaryformatter_layout():
    w = Writer()
    w.header(root_id=1, header_id=-1, major=1, minor=0)
    assert w.bytes() == bytes([0]) + struct.pack("<iiii", 1, -1, 1, 0)


def test_binary_library_record():
    w = Writer()
    w.binary_library(2, "Greenshot.Editor")
    expected = bytes([12]) + struct.pack("<i", 2) + length_prefixed_string("Greenshot.Editor")
    assert w.bytes() == expected


def test_class_with_members_and_types_batches_type_info_before_additional_info():
    # This is the exact bug this port's own first hand-decode attempt hit:
    # MS-NRBF lists every BinaryTypeEnumeration byte together first, then
    # every member's AdditionalInfo - not interleaved per-member (i.e. the
    # wire order is "0, 3, 8, <name>", not "0, 8, 3, <name>").
    w = Writer()
    w.class_with_members_and_types(
        1, "Foo", ["a", "b"], ["Primitive", "SystemClass"], ["Int32", "Some.Type"], 5,
    )
    expected = (
        bytes([5])
        + struct.pack("<i", 1) + length_prefixed_string("Foo") + struct.pack("<i", 2)
        + length_prefixed_string("a") + length_prefixed_string("b")
        + bytes([0, 3])  # BinaryTypeEnumeration: Primitive, SystemClass
        + bytes([8])  # Int32's own primitive type tag
        + length_prefixed_string("Some.Type")  # SystemClass's own additional info
        + struct.pack("<i", 5)
    )
    assert w.bytes() == expected


def test_primitive_value_int32():
    w = Writer()
    w.primitive_value("Int32", 42)
    assert w.bytes() == struct.pack("<i", 42)


def test_single_and_double_use_real_ieee754_not_raw_bits():
    # The library this was ported from had a real bug here: it packed
    # Single/Double with '<I'/'<Q' (reinterpreting the bits as an unsigned
    # integer) instead of '<f'/'<d'.
    w = Writer()
    w.primitive_value("Single", 1.5)
    assert w.bytes() == struct.pack("<f", 1.5)

    w2 = Writer()
    w2.primitive_value("Double", 1.5)
    assert w2.bytes() == struct.pack("<d", 1.5)


def test_member_primitive_typed_boolean():
    w = Writer()
    w.member_primitive_typed("Boolean", True)
    assert w.bytes() == bytes([8, 1, 1])


def test_message_end_is_a_single_byte():
    w = Writer()
    w.message_end()
    assert w.bytes() == bytes([11])
