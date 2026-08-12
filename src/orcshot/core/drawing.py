"""The annotation layer: z-order, hit-testing, and bounds aggregation.

Behavioral port of DrawableContainerList from the Windows source. List
position IS z-order — index 0 is drawn first (bottommost), the last
index is drawn last (topmost) — the same painter's-algorithm convention
Windows uses. Concrete shape types (rectangle, text, ...) are a separate
slice; this module is the container/ordering backbone they attach to.
"""

from __future__ import annotations

from typing import Iterator, List, Optional, Protocol, Sequence, runtime_checkable

from orcshot.core.geometry import Rect

HIT_TEST_MARGIN = 5


@runtime_checkable
class Drawable(Protocol):
    bounds: Rect


def hit_test(drawable: Drawable, x: int, y: int) -> bool:
    """Whether (x, y) counts as a click on ``drawable``.

    Shapes with their own ``clickable_at`` (Rectangle, Ellipse, Line,
    Arrow, ...) use it — mirroring ClickableAt being virtual/overridden
    per-shape in the Windows source, so a hollow shape is only
    clickable near its outline, not its whole bounding box. Shapes
    without one fall back to bounds inflated by HIT_TEST_MARGIN, so
    thin shapes stay clickable a few pixels past their edge — ported
    from the base DrawableContainer.ClickableAt's Inflate(5, 5).
    """
    clickable_at = getattr(drawable, "clickable_at", None)
    if clickable_at is not None:
        return clickable_at(x, y)

    b = drawable.bounds
    inflated = Rect(
        b.left - HIT_TEST_MARGIN,
        b.top - HIT_TEST_MARGIN,
        b.right + HIT_TEST_MARGIN,
        b.bottom + HIT_TEST_MARGIN,
    )
    return inflated.contains(x, y)


def _index_by_identity(items: List[Drawable], target: Drawable) -> int:
    for index, item in enumerate(items):
        if item is target:
            return index
    raise ValueError(f"{target!r} is not in this layer")


class Layer:
    def __init__(self):
        self._items: List[Drawable] = []

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Drawable]:
        return iter(self._items)

    def add(self, drawable: Drawable) -> None:
        self._items.append(drawable)

    def remove(self, drawable: Drawable) -> None:
        self._items.pop(_index_by_identity(self._items, drawable))

    def replace(self, old: Drawable, new: Drawable) -> None:
        """Swap ``old`` for ``new`` at the same z-order index.

        Distinct from remove+add: modifying a shape in place (move,
        restyle, edit text) must not send it to the top of the stack
        the way delete-then-re-add does.
        """
        self._items[_index_by_identity(self._items, old)] = new

    @property
    def bounds(self) -> Optional[Rect]:
        return Rect.union_all(d.bounds for d in self._items)

    def intersects(self, rect: Rect) -> bool:
        return any(d.bounds.intersect(rect) is not None for d in self._items)

    def topmost_at(self, x: int, y: int) -> Optional[Drawable]:
        for drawable in reversed(self._items):
            if hit_test(drawable, x, y):
                return drawable
        return None

    def can_bring_forward(self, elements: Sequence[Drawable]) -> bool:
        if not elements or len(elements) == len(self._items):
            return False
        threshold = len(self._items) - len(elements)
        return any(_index_by_identity(self._items, e) < threshold for e in elements)

    def bring_forward(self, elements: Sequence[Drawable]) -> None:
        selected = {id(e) for e in elements}
        for i in range(len(self._items) - 1, -1, -1):
            if id(self._items[i]) not in selected:
                continue
            if i + 1 < len(self._items) and id(self._items[i + 1]) not in selected:
                self._items[i], self._items[i + 1] = self._items[i + 1], self._items[i]

    def bring_to_front(self, elements: Sequence[Drawable]) -> None:
        selected = {id(e) for e in elements}
        for drawable in list(self._items):
            if id(drawable) in selected:
                self.remove(drawable)
                self._items.append(drawable)

    def can_send_backward(self, elements: Sequence[Drawable]) -> bool:
        if not elements or len(elements) == len(self._items):
            return False
        return any(_index_by_identity(self._items, e) >= len(elements) for e in elements)

    def send_backward(self, elements: Sequence[Drawable]) -> None:
        selected = {id(e) for e in elements}
        for i in range(len(self._items)):
            if id(self._items[i]) not in selected:
                continue
            if i > 0 and id(self._items[i - 1]) not in selected:
                self._items[i], self._items[i - 1] = self._items[i - 1], self._items[i]

    def send_to_back(self, elements: Sequence[Drawable]) -> None:
        selected = {id(e) for e in elements}
        for drawable in reversed(list(self._items)):
            if id(drawable) in selected:
                self.remove(drawable)
                self._items.insert(0, drawable)
