"""The .orcshot shape-layer schema (task #123) - round-trip every
shape type through serialize_shape/deserialize_shape and confirm the
result is equal to the original (or, for ObfuscateShape's seed field,
explicitly equal despite compare=False not requiring it - the seed
must survive the round trip so a reopened file renders identical
noise, not just an equal-by-dataclass-comparison shape).
"""

import numpy as np
import pytest

from orcshot.core.drawing import Layer
from orcshot.core.geometry import Rect
from orcshot.core.orcshot_format import (
    deserialize_layer_into,
    deserialize_shape,
    serialize_layer,
    serialize_shape,
)
from orcshot.core.shapes import (
    ArrowShape,
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

_STYLE = ShapeStyle(line_thickness=3, line_color=(10, 20, 30, 255), fill_color=(40, 50, 60, 128), shadow=True)


def _small_image() -> np.ndarray:
    image = np.arange(2 * 3 * 4, dtype=np.uint8).reshape(2, 3, 4)
    return image


class TestRoundTripEachShapeType:
    def test_rectangle(self):
        shape = RectangleShape(bounds=Rect(1, 2, 3, 4), style=_STYLE)
        assert deserialize_shape(serialize_shape(shape)) == shape

    def test_ellipse(self):
        shape = EllipseShape(bounds=Rect(1, 2, 3, 4), style=_STYLE)
        assert deserialize_shape(serialize_shape(shape)) == shape

    def test_line(self):
        shape = LineShape(start=(1, 2), end=(3, 4), style=_STYLE)
        assert deserialize_shape(serialize_shape(shape)) == shape

    def test_arrow_round_trips_as_arrow_not_line(self):
        shape = ArrowShape(start=(1, 2), end=(3, 4), style=_STYLE)
        result = deserialize_shape(serialize_shape(shape))
        assert type(result) is ArrowShape
        assert result == shape

    def test_freehand(self):
        shape = FreehandShape(points=((0, 0), (5, 5), (10, 0)), style=_STYLE)
        assert deserialize_shape(serialize_shape(shape)) == shape

    def test_text(self):
        shape = TextShape(
            bounds=Rect(0, 0, 100, 40), text="Hello, world!", font_family="serif", font_size=14.5,
            bold=True, italic=True, horizontal_alignment="far", vertical_alignment="near", style=_STYLE,
        )
        assert deserialize_shape(serialize_shape(shape)) == shape

    def test_speech_bubble(self):
        shape = SpeechBubbleShape(
            bubble_bounds=Rect(0, 0, 100, 40), target=(150, 90), text="Boo!",
            font_family="monospace", font_size=18.0, bold=False, italic=True,
            horizontal_alignment="near", vertical_alignment="far", style=_STYLE,
        )
        assert deserialize_shape(serialize_shape(shape)) == shape

    def test_step_label(self):
        shape = StepLabelShape(bounds=Rect(0, 0, 30, 30), number=7, style=_STYLE)
        assert deserialize_shape(serialize_shape(shape)) == shape

    def test_icon(self):
        shape = IconShape(bounds=Rect(0, 0, 3, 2), image=_small_image())
        result = deserialize_shape(serialize_shape(shape))
        assert result.bounds == shape.bounds
        assert np.array_equal(result.image, shape.image)

    def test_cursor(self):
        shape = CursorShape(bounds=Rect(0, 0, 3, 2), image=_small_image())
        result = deserialize_shape(serialize_shape(shape))
        assert result.bounds == shape.bounds
        assert np.array_equal(result.image, shape.image)

    def test_image(self):
        shape = ImageShape(bounds=Rect(0, 0, 3, 2), image=_small_image(), shadow=True)
        result = deserialize_shape(serialize_shape(shape))
        assert result.bounds == shape.bounds
        assert np.array_equal(result.image, shape.image)
        assert result.shadow == shape.shadow

    def test_svg(self):
        shape = SvgShape(bounds=Rect(0, 0, 50, 50), svg_data="<svg></svg>")
        assert deserialize_shape(serialize_shape(shape)) == shape

    def test_highlight(self):
        shape = HighlightShape(
            bounds=Rect(0, 0, 20, 20), mode=HighlightMode.MAGNIFICATION, fill_color=(1, 2, 3, 4),
            brightness=0.5, blur_radius=7, magnification_factor=3,
        )
        assert deserialize_shape(serialize_shape(shape)) == shape

    def test_obfuscate(self):
        shape = ObfuscateShape(
            bounds=Rect(0, 0, 20, 20), mode=ObfuscateMode.SOLID_FILL, amount=9,
            fill_color=(5, 6, 7, 8), fill_text="REDACTED", text_color=(255, 255, 255, 255), seed=123456789,
        )
        result = deserialize_shape(serialize_shape(shape))
        assert result == shape  # seed is compare=False, so this alone wouldn't catch a lost seed
        assert result.seed == shape.seed  # explicit check: seed must survive the round trip


class TestUnknownType:
    def test_serialize_unregistered_shape_type_raises(self):
        class NotAShape:
            pass

        with pytest.raises(TypeError):
            serialize_shape(NotAShape())

    def test_deserialize_unknown_type_string_raises(self):
        with pytest.raises(TypeError):
            deserialize_shape({"type": "nonsense"})


class TestLayerRoundTrip:
    def test_empty_layer(self):
        layer = Layer()
        data = serialize_layer(layer)
        assert data == []

        restored = Layer()
        deserialize_layer_into(restored, data)
        assert len(restored) == 0

    def test_preserves_order_and_every_shape(self):
        layer = Layer()
        shapes = [
            RectangleShape(bounds=Rect(0, 0, 1, 1)),
            EllipseShape(bounds=Rect(1, 1, 2, 2)),
            TextShape(bounds=Rect(2, 2, 3, 3), text="hi"),
        ]
        for shape in shapes:
            layer.add(shape)

        data = serialize_layer(layer)
        restored = Layer()
        deserialize_layer_into(restored, data)

        assert list(restored) == shapes
