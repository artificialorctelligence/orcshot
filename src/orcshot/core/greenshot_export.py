"""Exports Orcshot shapes to real Windows Greenshot's own object model,
serialized as NRBF (core/nrbf.py) - task #124, byte-compatible with real
Greenshot's .greenshot/.gst files, unlike core/orcshot_format.py's own
JSON-based .orcshot format (task #123, a deliberately different, simpler
scheme - see that module's docstring for why NRBF wasn't used there).

Scoped to RectangleContainer only for now (task #124's own first pass,
not general 14-shape-type coverage) - the real Windows field layout below
was independently verified via .NET reflection against the actual
Greenshot.Editor.dll/Greenshot.Base.dll on a real Windows 11 VM (not
guessed from source), and the resulting object graph was round-tripped
through real Greenshot's own BinaryFormatterHelper whitelist binder
(Greenshot.Editor/Helpers/BinaryFormatterHelper.cs in the reference
clone) successfully. See REQUIREMENTS.md's task #124 section for the
full trace and citations.

Real RectangleContainer's serializable shape (RectangleContainer.cs,
DrawableContainer.cs, AbstractFieldHolderWithChildren.cs,
AbstractFieldHolder.cs - only non-[NonSerialized] members):
    _defaultEditMode (EditStatus enum, appears twice under .NET's own
        FormatterServices.GetSerializableMembers - a protected field gets
        picked up once unqualified and once as "DrawableContainer+..." via
        two separate internal passes, not a bug in this port - see
        REQUIREMENTS.md), Children (List<IFieldHolder>, always empty -
        RectangleContainer never has any), left/top/width/height (Int32),
        accountForShadowChange (Boolean, always False - Orcshot doesn't
        track this shadow-resize bookkeeping state), fields
        (List<IField> - exactly the 4 Field entries
        RectangleContainer.InitializeFields() creates: LINE_THICKNESS,
        LINE_COLOR, FILL_COLOR, SHADOW - a 1:1 match with this port's own
        ShapeStyle dataclass).
"""
from __future__ import annotations

from orcshot.core.nrbf import Writer
from orcshot.core.shapes import RectangleShape

_LIB_EDITOR = 2
_LIB_BASE = 3
_LIB_SYSTEM_DRAWING = 4

_LIST_FIELDHOLDER = (
    "System.Collections.Generic.List`1[[Greenshot.Base.Interfaces.Drawing.IFieldHolder, "
    "Greenshot.Base, Version=1.3.0.0, Culture=neutral, PublicKeyToken=null]]"
)
_LIST_FIELD = (
    "System.Collections.Generic.List`1[[Greenshot.Base.Interfaces.Drawing.IField, "
    "Greenshot.Base, Version=1.3.0.0, Culture=neutral, PublicKeyToken=null]]"
)
_EDIT_STATUS = "Greenshot.Base.Interfaces.Drawing.EditStatus"
_FIELD_CLASS = "Greenshot.Editor.Drawing.Fields.Field"
_FIELD_TYPE_CLASS = "Greenshot.Editor.Drawing.Fields.FieldType"
_COLOR_CLASS = "System.Drawing.Color"


class _IdAllocator:
    """This port's own simple, consistent object-id scheme - NOT a replica
    of real BinaryFormatter's own breadth-first discovery-order IDs (an
    implementation-specific optimization detail, not a format
    requirement). Any unique-per-stream ids are valid NRBF; verified live
    against real Greenshot's own deserializer, not just assumed.
    """

    def __init__(self, start: int = 2):
        self._next = start

    def __call__(self) -> int:
        value = self._next
        self._next += 1
        return value


def _write_color(w: Writer, obj_id: int, class_schema_id: int | None, rgba: tuple) -> int:
    """Writes a System.Drawing.Color as an explicit ARGB value (state=2) -
    the general encoding any RGBA tuple maps to, not the "known color"
    optimization real Greenshot's own hardcoded defaults (e.g. Color.Red)
    happen to use - both are valid, real Greenshot only ever reads back
    .R/.G/.B/.A regardless of which encoding produced them.
    """
    r, g, b, a = rgba
    argb = (a << 24) | (r << 16) | (g << 8) | b
    if class_schema_id is None:
        w.class_with_members_and_types(
            obj_id, _COLOR_CLASS, ["name", "value", "knownColor", "state"],
            ["String", "Primitive", "Primitive", "Primitive"],
            [None, "Int64", "Int16", "Int16"], _LIB_SYSTEM_DRAWING,
        )
    else:
        w.class_with_id(obj_id, class_schema_id)
    w.object_null()  # name
    w.primitive_value("Int64", argb)
    w.primitive_value("Int16", 0)  # knownColor
    w.primitive_value("Int16", 2)  # state: STATE_ARGBVALUE
    return obj_id


def _write_field_type(w: Writer, ids: _IdAllocator, obj_id: int, class_schema_id: int | None, name: str) -> int:
    if class_schema_id is None:
        w.class_with_members_and_types(
            obj_id, _FIELD_TYPE_CLASS, ["<Name>k__BackingField"],
            ["String"], [None], _LIB_EDITOR,
        )
    else:
        w.class_with_id(obj_id, class_schema_id)
    w.binary_object_string(ids(), name)
    return obj_id


def rectangle_shape_to_greenshot_nrbf(shape: RectangleShape) -> bytes:
    """Returns the NRBF bytes for `shape` as a real Greenshot
    RectangleContainer - suitable for embedding in a real .greenshot/.gst
    file's own trailer format (task #124's remaining scope: wiring this
    into an actual file container, matching GreenshotFileFormatHandler.cs
    - not yet done, this function only covers the object-graph bytes).
    """
    ids = _IdAllocator()
    w = Writer()
    w.header(root_id=1)
    w.binary_library(_LIB_EDITOR, "Greenshot.Editor, Version=1.3.0.0, Culture=neutral, PublicKeyToken=null")
    w.binary_library(_LIB_BASE, "Greenshot.Base, Version=1.3.0.0, Culture=neutral, PublicKeyToken=null")
    w.binary_library(_LIB_SYSTEM_DRAWING, "System.Drawing, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a")

    bounds = shape.bounds
    style = shape.style

    children_id = ids()
    fields_id = ids()
    children_array_id = ids()
    fields_array_id = ids()
    edit_status_id = ids()

    w.class_with_members_and_types(
        1, "Greenshot.Editor.Drawing.RectangleContainer",
        ["_defaultEditMode", "Children", "DrawableContainer+_defaultEditMode",
         "DrawableContainer+left", "DrawableContainer+top", "DrawableContainer+width",
         "DrawableContainer+height", "DrawableContainer+accountForShadowChange",
         "AbstractFieldHolder+fields"],
        ["Class", "SystemClass", "Class", "Primitive", "Primitive", "Primitive",
         "Primitive", "Primitive", "SystemClass"],
        [(_EDIT_STATUS, _LIB_BASE), _LIST_FIELDHOLDER, (_EDIT_STATUS, _LIB_BASE),
         "Int32", "Int32", "Int32", "Int32", "Boolean", _LIST_FIELD],
        _LIB_EDITOR,
    )
    # _defaultEditMode: EditStatus.UNDRAWN (0) - matches real Greenshot's
    # own newly-placed-shape state (ImageEditorForm never persists an
    # in-progress-drawing status to a saved file).
    w.class_with_members_and_types(edit_status_id, _EDIT_STATUS, ["value__"], ["Primitive"], ["Int32"], _LIB_BASE)
    w.primitive_value("Int32", 0)
    w.member_reference(children_id)  # Children
    w.class_with_id(ids(), edit_status_id)  # DrawableContainer+_defaultEditMode, same enum
    w.primitive_value("Int32", 0)
    w.primitive_value("Int32", bounds.left)
    w.primitive_value("Int32", bounds.top)
    w.primitive_value("Int32", bounds.width)
    w.primitive_value("Int32", bounds.height)
    w.primitive_value("Boolean", False)  # accountForShadowChange
    w.member_reference(fields_id)  # fields

    w.system_class_with_members_and_types(
        children_id, _LIST_FIELDHOLDER, ["_items", "_size", "_version"],
        ["Class", "Primitive", "Primitive"],
        [("Greenshot.Base.Interfaces.Drawing.IFieldHolder[]", _LIB_BASE), "Int32", "Int32"],
    )
    w.member_reference(children_array_id)
    w.primitive_value("Int32", 0)
    w.primitive_value("Int32", 0)

    w.system_class_with_members_and_types(
        fields_id, _LIST_FIELD, ["_items", "_size", "_version"],
        ["Class", "Primitive", "Primitive"],
        [("Greenshot.Base.Interfaces.Drawing.IField[]", _LIB_BASE), "Int32", "Int32"],
    )
    w.member_reference(fields_array_id)
    w.primitive_value("Int32", 4)
    w.primitive_value("Int32", 4)

    w.binary_array_of_objects(children_array_id, 0, "Greenshot.Base.Interfaces.Drawing.IFieldHolder", _LIB_BASE)

    field_ids = [ids() for _ in range(4)]
    w.binary_array_of_objects(fields_array_id, 4, "Greenshot.Base.Interfaces.Drawing.IField", _LIB_BASE)
    for fid in field_ids:
        w.member_reference(fid)

    scope_id = ids()
    field_schema_id = None
    field_type_schema_id = None
    color_schema_id = None

    def write_field(obj_id, field_type_name, value_writer):
        nonlocal field_schema_id, field_type_schema_id
        if field_schema_id is None:
            w.class_with_members_and_types(
                obj_id, _FIELD_CLASS, ["_myValue", "<FieldType>k__BackingField", "<Scope>k__BackingField"],
                ["Object", "Class", "String"], [None, (_FIELD_TYPE_CLASS, _LIB_EDITOR), None], _LIB_EDITOR,
            )
            field_schema_id = obj_id
        else:
            w.class_with_id(obj_id, field_schema_id)
        value_writer()
        field_type_id = ids()
        _write_field_type(w, ids, field_type_id, field_type_schema_id, field_type_name)
        field_type_schema_id = field_type_id if field_type_schema_id is None else field_type_schema_id
        if scope_written[0]:
            w.member_reference(scope_id)
        else:
            w.binary_object_string(scope_id, "RectangleContainer")
            scope_written[0] = True

    scope_written = [False]

    write_field(field_ids[0], "LINE_THICKNESS", lambda: w.member_primitive_typed("Int32", style.line_thickness))

    def _color_value_writer(rgba):
        def inner():
            nonlocal color_schema_id
            color_id = ids()
            _write_color(w, color_id, color_schema_id, rgba)
            color_schema_id = color_id if color_schema_id is None else color_schema_id
        return inner

    write_field(field_ids[1], "LINE_COLOR", _color_value_writer(style.line_color))
    write_field(field_ids[2], "FILL_COLOR", _color_value_writer(style.fill_color))
    write_field(field_ids[3], "SHADOW", lambda: w.member_primitive_typed("Boolean", style.shadow))

    w.message_end()
    return w.bytes()
