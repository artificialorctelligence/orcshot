"""Minimal MS-NRBF (.NET Remoting Binary Format) writer - the wire format
real Windows Greenshot's own .greenshot/.gst files use under the hood
(.NET's System.Runtime.Serialization.Formatters.Binary.BinaryFormatter,
see GreenshotFileFormatHandler.cs and Surface.cs's SaveElementsToStream in
the reference clone). Task #124.

Record-writing logic is a Python 3 port of agix/NetBinaryFormatterParser's
JSON2dotnetBinaryFormatter.py (github.com/agix/NetBinaryFormatterParser,
MIT License, Copyright (c) 2016 NetBinaryFormatterParser), adapted from
Python 2's dict/JSON-driven design to a small typed Writer class, with two
real bugs fixed: Single/Double were packed with '<I'/'<Q' (reinterpreting
the raw bits as an unsigned integer) instead of '<f'/'<d' (actual IEEE 754
float encoding).

    MIT License

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions: the above copyright notice and this
    permission notice shall be included in all copies or substantial
    portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT
    WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.

The record layout itself (which fields batch together, the 7-bit varint
length prefix, etc.) was independently verified byte-for-byte against a
real Greenshot.Editor.dll RectangleContainer serialized on a real Windows
11 VM via .NET reflection + the actual BinaryFormatter - see
REQUIREMENTS.md's task #124 section for the full trace. That capture
(tests/fixtures/rectangle_container.nrbf) round-trips through real
Greenshot's own BinaryFormatterHelper whitelist binder unchanged, and this
module's own output for the same object graph matches it byte-for-byte.

Only the record types real Greenshot's own object graphs were confirmed to
actually use are implemented: SerializedStreamHeader, BinaryLibrary,
ClassWithMembersAndTypes, SystemClassWithMembersAndTypes, ClassWithId (for
a type whose full schema was already written), MemberReference (for an
already-written object), MemberPrimitiveTyped/primitive values, string
values, BinaryArray (single-dimension object arrays, what List<T>'s
backing store uses), and ObjectNull.
"""
from __future__ import annotations

import struct

PRIMITIVE_TYPE_CODES = {
    "Boolean": (1, "<B"), "Byte": (2, "<B"), "Char": (3, "<b"),
    "Double": (6, "<d"), "Int16": (7, "<h"), "Int32": (8, "<i"),
    "Int64": (9, "<q"), "SByte": (10, "<b"), "Single": (11, "<f"),
    "UInt16": (14, "<H"), "UInt32": (15, "<I"), "UInt64": (16, "<Q"),
}
_STRING_CODE = 18

BINARY_TYPE_CODES = {"Primitive": 0, "String": 1, "Object": 2, "SystemClass": 3,
                      "Class": 4, "ObjectArray": 5, "StringArray": 6, "PrimitiveArray": 7}


def length_prefixed_string(s: str) -> bytes:
    data = s.encode("utf-8")
    length = len(data)
    prefix = bytearray()
    while length >= 0x80:
        prefix.append((length | 0x80) & 0xFF)
        length >>= 7
    prefix.append(length)
    return bytes(prefix) + data


def _class_info(obj_id: int, class_name: str, member_names: list[str]) -> bytes:
    ret = struct.pack("<i", obj_id)
    ret += length_prefixed_string(class_name)
    ret += struct.pack("<i", len(member_names))
    for name in member_names:
        ret += length_prefixed_string(name)
    return ret


def _member_type_info(binary_type_enums: list[str], additional_infos: list) -> bytes:
    """MS-NRBF batches every BinaryTypeEnumeration byte together first,
    then every member's AdditionalInfo - NOT interleaved per-member. This
    tripped up this module's own first hand-decode attempt; see
    REQUIREMENTS.md's task #124 section.
    """
    ret = bytearray(BINARY_TYPE_CODES[bt] for bt in binary_type_enums)
    for bt, extra in zip(binary_type_enums, additional_infos):
        if bt in ("Primitive", "PrimitiveArray"):
            ret.append(_STRING_CODE if extra == "String" else PRIMITIVE_TYPE_CODES[extra][0])
        elif bt == "SystemClass":
            ret += length_prefixed_string(extra)
        elif bt == "Class":
            class_name, library_id = extra
            ret += length_prefixed_string(class_name)
            ret += struct.pack("<i", library_id)
        # String/Object/ObjectArray/StringArray: no additional info
    return bytes(ret)


class Writer:
    """Appends NRBF records in the exact order the caller provides - callers
    are responsible for matching real BinaryFormatter's own breadth-first
    write order for object identity (obj_id) purposes; this class does no
    graph-walking or id-bookkeeping of its own, matching task #124's own
    scope (a real per-shape-type template, not a generic object-graph
    serializer - see REQUIREMENTS.md).
    """

    def __init__(self):
        self.out = bytearray()

    def header(self, root_id: int = 1, header_id: int = -1, major: int = 1, minor: int = 0) -> None:
        self.out.append(0)
        self.out += struct.pack("<iiii", root_id, header_id, major, minor)

    def binary_library(self, library_id: int, name: str) -> None:
        self.out.append(12)
        self.out += struct.pack("<i", library_id)
        self.out += length_prefixed_string(name)

    def class_with_members_and_types(self, obj_id: int, class_name: str, member_names: list[str],
                                      binary_type_enums: list[str], additional_infos: list,
                                      library_id: int) -> None:
        self.out.append(5)
        self.out += _class_info(obj_id, class_name, member_names)
        self.out += _member_type_info(binary_type_enums, additional_infos)
        self.out += struct.pack("<i", library_id)

    def system_class_with_members_and_types(self, obj_id: int, class_name: str, member_names: list[str],
                                             binary_type_enums: list[str], additional_infos: list) -> None:
        self.out.append(4)
        self.out += _class_info(obj_id, class_name, member_names)
        self.out += _member_type_info(binary_type_enums, additional_infos)

    def class_with_id(self, obj_id: int, metadata_id: int) -> None:
        self.out.append(1)
        self.out += struct.pack("<ii", obj_id, metadata_id)

    def member_reference(self, id_ref: int) -> None:
        self.out.append(9)
        self.out += struct.pack("<i", id_ref)

    def object_null(self) -> None:
        self.out.append(10)

    def primitive_value(self, pt_name: str, value) -> None:
        if pt_name == "String":
            self.out += length_prefixed_string(value)
            return
        _code, fmt = PRIMITIVE_TYPE_CODES[pt_name]
        self.out += struct.pack(fmt, value)

    def member_primitive_typed(self, pt_name: str, value) -> None:
        code = _STRING_CODE if pt_name == "String" else PRIMITIVE_TYPE_CODES[pt_name][0]
        self.out.append(8)
        self.out.append(code)
        self.primitive_value(pt_name, value)

    def binary_object_string(self, obj_id: int, value: str) -> None:
        self.out.append(6)
        self.out += struct.pack("<i", obj_id)
        self.out += length_prefixed_string(value)

    def binary_array_of_objects(self, obj_id: int, length: int, item_class_name: str, item_library_id: int) -> None:
        """Single-dimensional, rank-1 object array - what every List<T>'s
        backing _items array uses. The array's own `length` elements (if
        any) must be written immediately after this call, in order, via
        whatever record each element needs (member_reference,
        class_with_members_and_types, etc.).
        """
        self.out.append(7)
        self.out += struct.pack("<i", obj_id)
        self.out.append(0)  # BinaryArrayTypeEnum.Single
        self.out += struct.pack("<i", 1)  # rank
        self.out += struct.pack("<i", length)
        self.out.append(4)  # item BinaryTypeEnumeration.Class
        self.out += length_prefixed_string(item_class_name)
        self.out += struct.pack("<i", item_library_id)

    def message_end(self) -> None:
        self.out.append(11)

    def bytes(self) -> bytes:
        return bytes(self.out)
