"""Undo/redo: a generic stack engine plus concrete mementos over Layer.

Behavioral port of IMemento and Surface's Undo/Redo/MakeUndoable. See
the module docstring in test_history.py for the architecture: why three
C# memento types collapse into ElementChangeMemento here, why
SurfaceBackgroundChangeMemento is out of scope, and the merge-must-
absorb subtlety that drove ElementChangeMemento's design.
"""

from __future__ import annotations

from typing import List, Protocol, Sequence, runtime_checkable

from greenshot_linux.core.drawing import Layer


@runtime_checkable
class Memento(Protocol):
    def restore(self) -> "Memento":
        """Restore the target to the state this memento remembers.
        Returns a memento that would restore the state as it was just
        before this call."""

    def merge(self, other: "Memento") -> bool:
        """Try to absorb ``other`` into self, so it need not be pushed
        as a separate undo entry. Returns whether the merge happened."""


class UndoRedoStack:
    """The generic engine: ported verbatim from Surface's
    Undo/Redo/MakeUndoable. Knows nothing about what a memento
    represents — Layer, shapes, and concrete memento types are all
    layered on top of this.
    """

    def __init__(self):
        self._undo: List[Memento] = []
        self._redo: List[Memento] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def push(self, memento: Memento, allow_merge: bool = True) -> None:
        if allow_merge and self._undo and self._undo[-1].merge(memento):
            return
        self._redo.clear()
        self._undo.append(memento)

    def undo(self) -> bool:
        if not self._undo:
            return False
        top = self._undo.pop()
        self._redo.append(top.restore())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        top = self._redo.pop()
        self._undo.append(top.restore())
        return True


class AddElementMemento:
    """Restoring undoes an add: removes the element. Ported from
    AddElementMemento — never merges, matching the source.
    """

    def __init__(self, layer: Layer, element):
        self.layer = layer
        self.element = element

    def restore(self) -> "DeleteElementMemento":
        self.layer.remove(self.element)
        return DeleteElementMemento(self.layer, self.element)

    def merge(self, other: Memento) -> bool:
        return False


class DeleteElementMemento:
    """Restoring undoes a delete: re-adds the element. Ported from
    DeleteElementMemento, including its faithful quirk: AddElement
    always appends, so the element returns to the *top* of z-order, not
    its original stacking position. Never merges, matching the source.
    """

    def __init__(self, layer: Layer, element):
        self.layer = layer
        self.element = element

    def restore(self) -> AddElementMemento:
        self.layer.add(self.element)
        return AddElementMemento(self.layer, self.element)

    def merge(self, other: Memento) -> bool:
        return False


class ElementChangeMemento:
    """Restoring swaps ``after`` back to ``before`` at the same z-order
    index. Collapses DrawableContainerBoundsChangeMemento,
    ChangeFieldHolderMemento, and TextChangeMemento — see the module
    docstring in test_history.py.

    merge() absorbs the incoming memento's ``after`` into self when it
    continues the same edit chain (self.after is other.before) — this
    mutation is required, not optional: without it, a later restore
    would try to swap away a shape instance no longer in the layer.
    """

    def __init__(self, layer: Layer, before, after):
        self.layer = layer
        self.before = before
        self.after = after

    def restore(self) -> "ElementChangeMemento":
        self.layer.replace(self.after, self.before)
        return ElementChangeMemento(self.layer, before=self.after, after=self.before)

    def merge(self, other: Memento) -> bool:
        if not isinstance(other, ElementChangeMemento):
            return False
        if self.after is not other.before:
            return False
        self.after = other.after
        return True


class CompositeMemento:
    """Restoring restores every child in order, atomically as one undo
    step. Ported from AddElementsMemento/DeleteElementsMemento, which
    collapse into this single generic wrapper — batch adds/deletes are
    just N AddElementMemento/DeleteElementMemento instances grouped
    together. Never merges, matching the source's list mementos.
    """

    def __init__(self, mementos: Sequence[Memento]):
        self.mementos = list(mementos)

    def restore(self) -> "CompositeMemento":
        return CompositeMemento([m.restore() for m in self.mementos])

    def merge(self, other: Memento) -> bool:
        return False
