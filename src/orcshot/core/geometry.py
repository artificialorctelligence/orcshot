from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @classmethod
    def from_points(cls, x1: int, y1: int, x2: int, y2: int) -> Rect:
        return cls(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def intersect(self, other: Rect) -> Rect | None:
        left = max(self.left, other.left)
        top = max(self.top, other.top)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        if left >= right or top >= bottom:
            return None
        return Rect(left, top, right, bottom)

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def union(self, other: Rect) -> Rect:
        return Rect(
            min(self.left, other.left),
            min(self.top, other.top),
            max(self.right, other.right),
            max(self.bottom, other.bottom),
        )

    @classmethod
    def union_all(cls, rects: Iterable[Rect]) -> Rect | None:
        result = None
        for rect in rects:
            result = rect if result is None else result.union(rect)
        return result
