"""The .orcshot shape-layer schema (task #123) - pure shape <-> dict/
JSON mapping, no GTK/GdkPixbuf dependency at all (embedded shape
images - IconShape/CursorShape/ImageShape - are encoded as raw base64
numpy bytes here, not PNG, specifically to keep this module GTK-free;
see ui/orcshot_file.py for the actual on-disk container, which PNG-
encodes the *main* captured image via GdkPixbuf and calls into this
module for the shape layer's own JSON).

Loosely modeled on real Windows Greenshot's own .greenshot format
(save the full editable shape layer alongside the raster image, not
just flattened pixels) but not byte-compatible with it and not
attempting to be - Windows' own blob is raw .NET BinaryFormatter/NRBF,
which is impractical to hand-encode from Python (see task #124's own
research trail). This is our own sane JSON schema instead, covering
the same conceptual shape model but diverging freely where this
port's own tool set differs from Windows' (Solid Fill, Color Scramble,
and Highlight's four modes have no Windows equivalent at all).

Every shape type gets a "type" discriminator string plus its own
fields; ``serialize_shape``/``deserialize_shape`` dispatch on it.
ArrowShape is a subclass of LineShape with no new fields (only a
different hit-test margin) - dispatched by exact type, not
``isinstance``, so an Arrow round-trips back to an Arrow, not a Line.
"""

from __future__ import annotations

import base64

import numpy as np

from orcshot.core.geometry import Rect
from orcshot.core.shapes import (
    ArrowShape,
    Color,
    CursorShape,
    EllipseShape,
    FreehandShape,
    HighlightMode,
    HighlightShape,
    IconShape,
    ImageShape,
    LineShape,
    ObfuscateMode,
    ObfuscateShape,
    RectangleShape,
    ShapeStyle,
    SpeechBubbleShape,
    StepLabelShape,
    SvgShape,
    TextShape,
)


def _rect_to_list(rect: Rect) -> list:
    return [rect.left, rect.top, rect.right, rect.bottom]


def _rect_from_list(data: list) -> Rect:
    left, top, right, bottom = data
    return Rect(left, top, right, bottom)


def _color_to_list(color: Color) -> list:
    return list(color)


def _color_from_list(data: list) -> Color:
    r, g, b, a = data
    return (r, g, b, a)


def _style_to_dict(style: ShapeStyle) -> dict:
    return {
        "line_thickness": style.line_thickness,
        "line_color": _color_to_list(style.line_color),
        "fill_color": _color_to_list(style.fill_color),
        "shadow": style.shadow,
    }


def _style_from_dict(data: dict) -> ShapeStyle:
    return ShapeStyle(
        line_thickness=data["line_thickness"],
        line_color=_color_from_list(data["line_color"]),
        fill_color=_color_from_list(data["fill_color"]),
        shadow=data["shadow"],
    )


def _image_to_dict(image: np.ndarray) -> dict:
    height, width = image.shape[:2]
    return {
        "width": width,
        "height": height,
        "data": base64.b64encode(np.ascontiguousarray(image).tobytes()).decode("ascii"),
    }


def _image_from_dict(data: dict) -> np.ndarray:
    raw = base64.b64decode(data["data"])
    return np.frombuffer(raw, dtype=np.uint8).reshape(data["height"], data["width"], 4).copy()


def serialize_shape(shape) -> dict:
    """Dispatches on the shape's exact type (not isinstance - see this
    module's own docstring for why ArrowShape needs exact matching).
    Raises TypeError for any shape type not in the schema yet, rather
    than silently dropping it from a saved file.
    """
    shape_type = type(shape)
    serializer = _SERIALIZERS.get(shape_type)
    if serializer is None:
        raise TypeError(f"No .orcshot serializer registered for {shape_type.__name__}")
    return serializer(shape)


def deserialize_shape(data: dict):
    deserializer = _DESERIALIZERS.get(data["type"])
    if deserializer is None:
        raise TypeError(f"No .orcshot deserializer registered for shape type {data['type']!r}")
    return deserializer(data)


def serialize_layer(layer) -> list:
    return [serialize_shape(shape) for shape in layer]


def deserialize_layer_into(layer, data: list) -> None:
    for shape_data in data:
        layer.add(deserialize_shape(shape_data))


def _serialize_rectangle(shape: RectangleShape) -> dict:
    return {"type": "rectangle", "bounds": _rect_to_list(shape.bounds), "style": _style_to_dict(shape.style)}


def _deserialize_rectangle(data: dict) -> RectangleShape:
    return RectangleShape(bounds=_rect_from_list(data["bounds"]), style=_style_from_dict(data["style"]))


def _serialize_ellipse(shape: EllipseShape) -> dict:
    return {"type": "ellipse", "bounds": _rect_to_list(shape.bounds), "style": _style_to_dict(shape.style)}


def _deserialize_ellipse(data: dict) -> EllipseShape:
    return EllipseShape(bounds=_rect_from_list(data["bounds"]), style=_style_from_dict(data["style"]))


def _serialize_line(shape: LineShape) -> dict:
    return {
        "type": "line", "start": list(shape.start), "end": list(shape.end), "style": _style_to_dict(shape.style),
    }


def _deserialize_line(data: dict) -> LineShape:
    return LineShape(start=tuple(data["start"]), end=tuple(data["end"]), style=_style_from_dict(data["style"]))


def _serialize_arrow(shape: ArrowShape) -> dict:
    return {
        "type": "arrow", "start": list(shape.start), "end": list(shape.end), "style": _style_to_dict(shape.style),
    }


def _deserialize_arrow(data: dict) -> ArrowShape:
    return ArrowShape(start=tuple(data["start"]), end=tuple(data["end"]), style=_style_from_dict(data["style"]))


def _serialize_freehand(shape: FreehandShape) -> dict:
    return {
        "type": "freehand",
        "points": [list(p) for p in shape.points],
        "style": _style_to_dict(shape.style),
    }


def _deserialize_freehand(data: dict) -> FreehandShape:
    return FreehandShape(
        points=tuple(tuple(p) for p in data["points"]), style=_style_from_dict(data["style"]),
    )


def _serialize_text(shape: TextShape) -> dict:
    return {
        "type": "text",
        "bounds": _rect_to_list(shape.bounds),
        "text": shape.text,
        "font_family": shape.font_family,
        "font_size": shape.font_size,
        "bold": shape.bold,
        "italic": shape.italic,
        "horizontal_alignment": shape.horizontal_alignment,
        "vertical_alignment": shape.vertical_alignment,
        "style": _style_to_dict(shape.style),
    }


def _deserialize_text(data: dict) -> TextShape:
    return TextShape(
        bounds=_rect_from_list(data["bounds"]),
        text=data["text"],
        font_family=data["font_family"],
        font_size=data["font_size"],
        bold=data["bold"],
        italic=data["italic"],
        horizontal_alignment=data["horizontal_alignment"],
        vertical_alignment=data["vertical_alignment"],
        style=_style_from_dict(data["style"]),
    )


def _serialize_speech_bubble(shape: SpeechBubbleShape) -> dict:
    return {
        "type": "speech_bubble",
        "bubble_bounds": _rect_to_list(shape.bubble_bounds),
        "target": list(shape.target),
        "text": shape.text,
        "font_family": shape.font_family,
        "font_size": shape.font_size,
        "bold": shape.bold,
        "italic": shape.italic,
        "horizontal_alignment": shape.horizontal_alignment,
        "vertical_alignment": shape.vertical_alignment,
        "style": _style_to_dict(shape.style),
    }


def _deserialize_speech_bubble(data: dict) -> SpeechBubbleShape:
    return SpeechBubbleShape(
        bubble_bounds=_rect_from_list(data["bubble_bounds"]),
        target=tuple(data["target"]),
        text=data["text"],
        font_family=data["font_family"],
        font_size=data["font_size"],
        bold=data["bold"],
        italic=data["italic"],
        horizontal_alignment=data["horizontal_alignment"],
        vertical_alignment=data["vertical_alignment"],
        style=_style_from_dict(data["style"]),
    )


def _serialize_step_label(shape: StepLabelShape) -> dict:
    return {
        "type": "step_label",
        "bounds": _rect_to_list(shape.bounds),
        "number": shape.number,
        "style": _style_to_dict(shape.style),
    }


def _deserialize_step_label(data: dict) -> StepLabelShape:
    return StepLabelShape(
        bounds=_rect_from_list(data["bounds"]), number=data["number"], style=_style_from_dict(data["style"]),
    )


def _serialize_icon(shape: IconShape) -> dict:
    return {"type": "icon", "bounds": _rect_to_list(shape.bounds), "image": _image_to_dict(shape.image)}


def _deserialize_icon(data: dict) -> IconShape:
    return IconShape(bounds=_rect_from_list(data["bounds"]), image=_image_from_dict(data["image"]))


def _serialize_cursor(shape: CursorShape) -> dict:
    return {"type": "cursor", "bounds": _rect_to_list(shape.bounds), "image": _image_to_dict(shape.image)}


def _deserialize_cursor(data: dict) -> CursorShape:
    return CursorShape(bounds=_rect_from_list(data["bounds"]), image=_image_from_dict(data["image"]))


def _serialize_image(shape: ImageShape) -> dict:
    return {
        "type": "image", "bounds": _rect_to_list(shape.bounds), "image": _image_to_dict(shape.image),
        "shadow": shape.shadow,
    }


def _deserialize_image(data: dict) -> ImageShape:
    return ImageShape(
        bounds=_rect_from_list(data["bounds"]), image=_image_from_dict(data["image"]), shadow=data["shadow"],
    )


def _serialize_svg(shape: SvgShape) -> dict:
    return {"type": "svg", "bounds": _rect_to_list(shape.bounds), "svg_data": shape.svg_data}


def _deserialize_svg(data: dict) -> SvgShape:
    return SvgShape(bounds=_rect_from_list(data["bounds"]), svg_data=data["svg_data"])


def _serialize_highlight(shape: HighlightShape) -> dict:
    return {
        "type": "highlight",
        "bounds": _rect_to_list(shape.bounds),
        "mode": shape.mode.value,
        "fill_color": _color_to_list(shape.fill_color),
        "brightness": shape.brightness,
        "blur_radius": shape.blur_radius,
        "magnification_factor": shape.magnification_factor,
    }


def _deserialize_highlight(data: dict) -> HighlightShape:
    return HighlightShape(
        bounds=_rect_from_list(data["bounds"]),
        mode=HighlightMode(data["mode"]),
        fill_color=_color_from_list(data["fill_color"]),
        brightness=data["brightness"],
        blur_radius=data["blur_radius"],
        magnification_factor=data["magnification_factor"],
    )


def _serialize_obfuscate(shape: ObfuscateShape) -> dict:
    return {
        "type": "obfuscate",
        "bounds": _rect_to_list(shape.bounds),
        "mode": shape.mode.value,
        "amount": shape.amount,
        "fill_color": _color_to_list(shape.fill_color),
        "fill_text": shape.fill_text,
        "text_color": _color_to_list(shape.text_color),
        # Persisted even though compare=False (doesn't affect shape
        # equality) - needed so a reopened file renders identical
        # noise instead of reshuffling on load, matching the
        # original's own field-level docstring on why it's pinned at
        # creation time in the first place.
        "seed": shape.seed,
    }


def _deserialize_obfuscate(data: dict) -> ObfuscateShape:
    return ObfuscateShape(
        bounds=_rect_from_list(data["bounds"]),
        mode=ObfuscateMode(data["mode"]),
        amount=data["amount"],
        fill_color=_color_from_list(data["fill_color"]),
        fill_text=data["fill_text"],
        text_color=_color_from_list(data["text_color"]),
        seed=data["seed"],
    )


_SERIALIZERS = {
    RectangleShape: _serialize_rectangle,
    EllipseShape: _serialize_ellipse,
    LineShape: _serialize_line,
    ArrowShape: _serialize_arrow,
    FreehandShape: _serialize_freehand,
    TextShape: _serialize_text,
    SpeechBubbleShape: _serialize_speech_bubble,
    StepLabelShape: _serialize_step_label,
    IconShape: _serialize_icon,
    CursorShape: _serialize_cursor,
    ImageShape: _serialize_image,
    SvgShape: _serialize_svg,
    HighlightShape: _serialize_highlight,
    ObfuscateShape: _serialize_obfuscate,
}

_DESERIALIZERS = {
    "rectangle": _deserialize_rectangle,
    "ellipse": _deserialize_ellipse,
    "line": _deserialize_line,
    "arrow": _deserialize_arrow,
    "freehand": _deserialize_freehand,
    "text": _deserialize_text,
    "speech_bubble": _deserialize_speech_bubble,
    "step_label": _deserialize_step_label,
    "icon": _deserialize_icon,
    "cursor": _deserialize_cursor,
    "image": _deserialize_image,
    "svg": _deserialize_svg,
    "highlight": _deserialize_highlight,
    "obfuscate": _deserialize_obfuscate,
}
