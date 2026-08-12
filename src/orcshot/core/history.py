"""Undo/redo: a generic stack engine plus concrete mementos over Layer.

Behavioral port of IMemento and Surface's Undo/Redo/MakeUndoable. See
the module docstring in test_history.py for the architecture: why three
C# memento types collapse into ElementChangeMemento here, and the
merge-must-absorb subtlety that drove ElementChangeMemento's design.

BackgroundChangeMemento (undoing a whole-image effect) was originally
out of scope, per that same docstring, because it "needs a 'Surface'
document concept (base image + Layer) that doesn't exist yet" - now in
scope since ui/editor_window.py's EditorWindow provides exactly that
(a `base_image` property + `layer`), needed once core/effects.py's
whole-image effects (rotate/border/shadow/etc.) landed.
"""

from __future__ import annotations

from typing import List, Protocol, Sequence, runtime_checkable

from orcshot.core.drawing import Layer


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
        # Monotonic counter bumped by every push/undo/redo - a cheap
        # proxy for Surface.Modified (ISurface.cs:193), which real
        # Greenshot also sets true on undo/redo, not just fresh edits
        # (DrawableContainerList.cs:176 etc. - Restore() routes back
        # through the same Add/Remove that sets Modified regardless of
        # who called it). ui/editor_window.py's EditorWindow compares
        # this against the generation at its last successful save
        # (self._saved_generation) rather than every push call site
        # setting a dirty flag by hand.
        self.generation = 0

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def push(self, memento: Memento, allow_merge: bool = True) -> None:
        self.generation += 1
        if allow_merge and self._undo and self._undo[-1].merge(memento):
            return
        self._redo.clear()
        self._undo.append(memento)

    def undo(self) -> bool:
        if not self._undo:
            return False
        top = self._undo.pop()
        self._redo.append(top.restore())
        self.generation += 1
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        top = self._redo.pop()
        self._undo.append(top.restore())
        self.generation += 1
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


class BackgroundChangeMemento:
    """Restoring undoes a whole-image effect (rotate/border/shadow/
    autocrop/etc., core/effects.py): swaps the base image back to what
    it was, and swaps every element the effect repositioned back to
    its pre-effect version too, so annotations stay aligned with
    whichever effect moved or resized the canvas. Faithful port of
    SurfaceBackgroundChangeMemento (Greenshot.Editor/Memento/
    SurfaceBackgroundChangeMemento.cs) - see the module docstring for
    why it's in scope now. Never merges, matching the source (Merge()
    always returns false - every effect application is its own undo
    step, none coalesce).

    ``target`` is anything exposing a settable ``base_image`` (only
    ui/editor_window.py's EditorWindow today). ``element_pairs`` is a
    sequence of (old_shape, new_shape) for every element the effect
    repositioned/rescaled - built by the caller using
    core/tools.py's translate_shape/scale_shape/rotate_shape_90, since
    only the caller knows which transform a given effect applied; an
    effect that only changes pixels (grayscale, invert) passes an
    empty sequence.
    """

    def __init__(self, target, layer: Layer, before_image, after_image, element_pairs=()):
        self.target = target
        self.layer = layer
        self.before_image = before_image
        self.after_image = after_image
        self.element_pairs = list(element_pairs)

    def restore(self) -> "BackgroundChangeMemento":
        self.target.base_image = self.before_image
        for old_shape, new_shape in self.element_pairs:
            self.layer.replace(new_shape, old_shape)
        return BackgroundChangeMemento(
            self.target, self.layer, before_image=self.after_image, after_image=self.before_image,
            element_pairs=[(new, old) for old, new in self.element_pairs],
        )

    def merge(self, other: Memento) -> bool:
        return False


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
