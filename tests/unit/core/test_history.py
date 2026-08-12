"""Undo/redo: a generic stack engine plus concrete mementos over Layer.

Behavioral port of IMemento + Surface's Undo/Redo/MakeUndoable (Surface.cs
lines ~644-718). The stack-management logic — pop, Restore(), push the
result to the other stack; clear the redo stack on a genuinely new
action; consult Merge() before pushing — is ported verbatim, since it's
a small, precise, easy-to-get-subtly-wrong algorithm. Tested first
against a bare-bones fake memento, independent of any concrete memento
type, exactly the way Layer's z-order logic was tested against
FakeDrawable before RectangleShape existed.

Three C# memento types collapse into one here: DrawableContainer-
BoundsChangeMemento, ChangeFieldHolderMemento, and TextChangeMemento all
become ElementChangeMemento, because all three are "swap the immutable
shape instance" in this model — the C# needed three because it mutated
different specific properties in place on a live object; an immutable
value object makes that distinction disappear. SurfaceBackgroundChange-
Memento (undoing a crop/background change) is out of scope — it needs a
"Surface" document concept (base image + Layer) that doesn't exist yet.

The one real subtlety, worth restating since it drove the whole design:
C# mementos never store an "after" snapshot — Restore() always reads
the *live* mutable object's current state fresh, which only works
because the object mutates in place. Immutable shapes can't do that, so
ElementChangeMemento stores "after" explicitly — which means merge()
must *absorb* the newer state into the existing entry, not just return
a bool, or a later undo would try to restore-away a shape instance
that's no longer in the layer at all. TestElementChangeMementoMerging
exercises this directly.
"""

from orcshot.core.drawing import Layer
from orcshot.core.geometry import Rect
from orcshot.core.history import (
    AddElementMemento,
    BackgroundChangeMemento,
    CompositeMemento,
    DeleteElementMemento,
    ElementChangeMemento,
    UndoRedoStack,
)


class FakeDrawable:
    def __init__(self, bounds, name=""):
        self.bounds = bounds
        self.name = name or repr(id(self))

    def __repr__(self):
        return f"FakeDrawable({self.name})"


def shape(name=""):
    return FakeDrawable(Rect(0, 0, 10, 10), name)


class FakeMemento:
    """A memento with no real target — just a label and a call log, for
    testing UndoRedoStack's pop/restore/push machinery in isolation."""

    def __init__(self, label, log, mergeable_with=None):
        self.label = label
        self.log = log
        self.mergeable_with = mergeable_with or set()

    def restore(self):
        self.log.append(f"restore({self.label})")
        return FakeMemento(f"~{self.label}", self.log, self.mergeable_with)

    def merge(self, other):
        return isinstance(other, FakeMemento) and other.label in self.mergeable_with


class TestUndoRedoStackBasics:
    def test_cannot_undo_or_redo_an_empty_stack(self):
        stack = UndoRedoStack()
        assert not stack.can_undo
        assert not stack.can_redo
        assert stack.undo() is False
        assert stack.redo() is False

    def test_push_makes_undo_available(self):
        stack = UndoRedoStack()
        stack.push(FakeMemento("A", []))
        assert stack.can_undo
        assert not stack.can_redo

    def test_undo_calls_restore_and_moves_the_result_to_redo(self):
        log = []
        stack = UndoRedoStack()
        stack.push(FakeMemento("A", log))

        assert stack.undo() is True

        assert log == ["restore(A)"]
        assert not stack.can_undo
        assert stack.can_redo

    def test_redo_calls_restore_and_moves_the_result_back_to_undo(self):
        log = []
        stack = UndoRedoStack()
        stack.push(FakeMemento("A", log))
        stack.undo()

        assert stack.redo() is True

        assert log == ["restore(A)", "restore(~A)"]
        assert stack.can_undo
        assert not stack.can_redo

    def test_a_new_push_clears_the_redo_stack(self):
        # Ported from MakeUndoable: any genuinely new action invalidates
        # whatever redo history existed.
        stack = UndoRedoStack()
        stack.push(FakeMemento("A", []))
        stack.undo()
        assert stack.can_redo

        stack.push(FakeMemento("B", []))

        assert not stack.can_redo

    def test_multiple_undo_redo_cycles_round_trip_correctly(self):
        log = []
        stack = UndoRedoStack()
        stack.push(FakeMemento("A", log))
        stack.push(FakeMemento("B", log))

        stack.undo()
        stack.undo()
        assert not stack.can_undo

        stack.redo()
        stack.redo()
        assert not stack.can_redo
        assert log == ["restore(B)", "restore(A)", "restore(~A)", "restore(~B)"]

    def test_generation_starts_at_zero(self):
        assert UndoRedoStack().generation == 0

    def test_generation_advances_on_push_undo_and_redo(self):
        stack = UndoRedoStack()
        stack.push(FakeMemento("A", []))
        assert stack.generation == 1

        stack.undo()
        assert stack.generation == 2

        stack.redo()
        assert stack.generation == 3

    def test_generation_advances_even_on_a_merged_push(self):
        # Surface.Modified goes true on any drawable-list change, merged
        # or not (DrawableContainerList.cs:176 etc.) - generation should
        # track the same way, not just "real" (non-absorbed) pushes.
        stack = UndoRedoStack()
        stack.push(FakeMemento("A", [], mergeable_with={"B"}))
        before = stack.generation

        stack.push(FakeMemento("B", []))  # absorbed by the merge above

        assert stack.generation == before + 1


class TestUndoRedoStackMerging:
    def test_a_mergeable_push_is_absorbed_not_pushed(self):
        stack = UndoRedoStack()
        stack.push(FakeMemento("A", [], mergeable_with={"B"}))

        stack.push(FakeMemento("B", []))

        stack.undo()
        assert not stack.can_undo  # only one entry existed to begin with

    def test_allow_merge_false_forces_a_separate_entry(self):
        stack = UndoRedoStack()
        stack.push(FakeMemento("A", [], mergeable_with={"B"}))

        stack.push(FakeMemento("B", []), allow_merge=False)

        stack.undo()
        assert stack.can_undo  # two entries: the merge was skipped

    def test_merging_still_clears_the_redo_stack(self):
        stack = UndoRedoStack()
        stack.push(FakeMemento("A", []))
        stack.undo()
        stack.push(FakeMemento("B", []))
        stack.undo()
        assert stack.can_redo

        stack.push(FakeMemento("C", [], mergeable_with={"D"}))
        stack.push(FakeMemento("D", []))

        assert not stack.can_redo


class TestAddDeleteElementMemento:
    def test_add_memento_restore_removes_the_element(self):
        layer = Layer()
        a = shape("a")
        layer.add(a)

        AddElementMemento(layer, a).restore()

        assert list(layer) == []

    def test_add_memento_restore_returns_a_delete_memento(self):
        layer = Layer()
        a = shape("a")
        layer.add(a)

        opposite = AddElementMemento(layer, a).restore()

        assert isinstance(opposite, DeleteElementMemento)

    def test_delete_memento_restore_re_adds_the_element(self):
        layer = Layer()
        a = shape("a")

        DeleteElementMemento(layer, a).restore()

        assert list(layer) == [a]

    def test_delete_then_undo_appends_to_the_top_not_the_original_index(self):
        # Faithful to the source: AddElement always appends. Undoing a
        # delete does not restore the element's original z-order
        # position — a real, if slightly surprising, ported behavior.
        layer = Layer()
        a, b, c = shape("a"), shape("b"), shape("c")
        for s in (a, b, c):
            layer.add(s)
        layer.remove(a)

        DeleteElementMemento(layer, a).restore()

        assert list(layer) == [b, c, a]

    def test_add_and_delete_mementos_never_merge(self):
        layer = Layer()
        a = shape("a")
        assert AddElementMemento(layer, a).merge(AddElementMemento(layer, a)) is False
        assert DeleteElementMemento(layer, a).merge(DeleteElementMemento(layer, a)) is False

    def test_full_add_undo_redo_round_trip_via_the_stack(self):
        layer = Layer()
        stack = UndoRedoStack()
        a = shape("a")

        layer.add(a)
        stack.push(AddElementMemento(layer, a))
        assert list(layer) == [a]

        stack.undo()
        assert list(layer) == []

        stack.redo()
        assert list(layer) == [a]


class TestElementChangeMemento:
    def test_restore_swaps_back_to_the_before_state(self):
        layer = Layer()
        before, after = shape("before"), shape("after")
        layer.add(before)
        layer.replace(before, after)

        ElementChangeMemento(layer, before=before, after=after).restore()

        assert list(layer) == [before]

    def test_restore_preserves_z_order_index(self):
        layer = Layer()
        x, before, after, z = shape("x"), shape("before"), shape("after"), shape("z")
        for s in (x, before, z):
            layer.add(s)
        layer.replace(before, after)

        ElementChangeMemento(layer, before=before, after=after).restore()

        assert list(layer) == [x, before, z]

    def test_restore_returns_the_opposite_memento(self):
        layer = Layer()
        before, after = shape("before"), shape("after")
        layer.add(before)
        layer.replace(before, after)

        opposite = ElementChangeMemento(layer, before=before, after=after).restore()

        assert opposite.before is after
        assert opposite.after is before


class TestElementChangeMementoMerging:
    def test_a_second_edit_to_the_same_evolving_shape_merges(self):
        # v0 -> v1 pushed; v1 -> v2 attempted. Same shape mid-edit
        # (e.g. dragging), so it must merge rather than push separately.
        layer = Layer()
        v0, v1, v2 = shape("v0"), shape("v1"), shape("v2")
        layer.add(v0)

        first = ElementChangeMemento(layer, before=v0, after=v1)
        assert first.merge(ElementChangeMemento(layer, before=v1, after=v2)) is True

    def test_merging_absorbs_the_newer_after_state(self):
        # The subtlety: merging must update the retained memento's
        # `after`, or a later restore would try to swap away a shape
        # instance no longer in the layer.
        layer = Layer()
        v0, v1, v2 = shape("v0"), shape("v1"), shape("v2")
        layer.add(v0)

        first = ElementChangeMemento(layer, before=v0, after=v1)
        first.merge(ElementChangeMemento(layer, before=v1, after=v2))

        assert first.after is v2

    def test_an_edit_to_a_different_shape_does_not_merge(self):
        layer = Layer()
        v0, v1 = shape("v0"), shape("v1")
        other_before, other_after = shape("other0"), shape("other1")

        first = ElementChangeMemento(layer, before=v0, after=v1)
        assert first.merge(ElementChangeMemento(layer, before=other_before, after=other_after)) is False

    def test_full_merged_edit_sequence_undoes_all_the_way_back_in_one_step(self):
        # Simulates a continuous drag: three quick edits pushed with
        # merging enabled must still undo back to the very first state
        # in a single undo() call.
        layer = Layer()
        stack = UndoRedoStack()
        v0, v1, v2, v3 = shape("v0"), shape("v1"), shape("v2"), shape("v3")
        layer.add(v0)

        for before, after in [(v0, v1), (v1, v2), (v2, v3)]:
            layer.replace(before, after)
            stack.push(ElementChangeMemento(layer, before=before, after=after))

        assert list(layer) == [v3]

        stack.undo()

        assert list(layer) == [v0]
        assert not stack.can_undo  # everything merged into a single entry


class TestCompositeMemento:
    def test_restore_restores_every_child_in_order(self):
        layer = Layer()
        a, b = shape("a"), shape("b")
        layer.add(a)
        layer.add(b)

        composite = CompositeMemento([AddElementMemento(layer, a), AddElementMemento(layer, b)])
        composite.restore()

        assert list(layer) == []

    def test_restore_returns_a_composite_of_the_opposites(self):
        layer = Layer()
        a, b = shape("a"), shape("b")
        layer.add(a)
        layer.add(b)

        composite = CompositeMemento([AddElementMemento(layer, a), AddElementMemento(layer, b)])
        opposite = composite.restore()

        assert isinstance(opposite, CompositeMemento)
        opposite.restore()
        assert list(layer) == [a, b]

    def test_never_merges(self):
        layer = Layer()
        a = shape("a")
        c1 = CompositeMemento([AddElementMemento(layer, a)])
        c2 = CompositeMemento([AddElementMemento(layer, a)])
        assert c1.merge(c2) is False

    def test_batch_delete_undo_redo_round_trip_via_the_stack(self):
        layer = Layer()
        stack = UndoRedoStack()
        a, b, c = shape("a"), shape("b"), shape("c")
        for s in (a, b, c):
            layer.add(s)

        # Batch-delete b and c together as one undo step.
        to_delete = [b, c]
        mementos = [DeleteElementMemento(layer, s) for s in to_delete]
        for s in to_delete:
            layer.remove(s)
        stack.push(CompositeMemento(mementos))

        assert list(layer) == [a]

        stack.undo()
        assert list(layer) == [a, b, c]

        stack.redo()
        assert list(layer) == [a]


class FakeSurfaceLikeTarget:
    """Stands in for ui/editor_window.py's EditorWindow - the only
    thing BackgroundChangeMemento needs from its target is a settable
    ``base_image``.
    """

    def __init__(self, base_image):
        self.base_image = base_image


class TestBackgroundChangeMemento:
    def test_restore_swaps_the_base_image_back(self):
        target = FakeSurfaceLikeTarget(base_image="after")
        memento = BackgroundChangeMemento(target, Layer(), before_image="before", after_image="after")

        memento.restore()

        assert target.base_image == "before"

    def test_restore_returns_the_opposite_memento(self):
        target = FakeSurfaceLikeTarget(base_image="after")
        memento = BackgroundChangeMemento(target, Layer(), before_image="before", after_image="after")

        opposite = memento.restore()
        opposite.restore()

        assert target.base_image == "after"

    def test_restore_swaps_repositioned_elements_back_too(self):
        layer = Layer()
        old_shape, new_shape = shape("old"), shape("new")
        layer.add(new_shape)
        target = FakeSurfaceLikeTarget(base_image="after")

        memento = BackgroundChangeMemento(
            target, layer, before_image="before", after_image="after",
            element_pairs=[(old_shape, new_shape)],
        )
        memento.restore()

        assert list(layer) == [old_shape]

    def test_pixel_only_effects_pass_no_element_pairs(self):
        layer = Layer()
        a = shape("a")
        layer.add(a)
        target = FakeSurfaceLikeTarget(base_image="after")

        memento = BackgroundChangeMemento(target, layer, before_image="before", after_image="after")
        memento.restore()

        assert list(layer) == [a]  # untouched - no element_pairs given

    def test_never_merges(self):
        target = FakeSurfaceLikeTarget(base_image="after")
        m1 = BackgroundChangeMemento(target, Layer(), before_image="a", after_image="b")
        m2 = BackgroundChangeMemento(target, Layer(), before_image="b", after_image="c")
        assert m1.merge(m2) is False

    def test_full_undo_redo_round_trip_via_the_stack(self):
        layer = Layer()
        old_shape, new_shape = shape("old"), shape("new")
        layer.add(new_shape)
        target = FakeSurfaceLikeTarget(base_image="after")
        stack = UndoRedoStack()

        stack.push(BackgroundChangeMemento(
            target, layer, before_image="before", after_image="after",
            element_pairs=[(old_shape, new_shape)],
        ))

        stack.undo()
        assert target.base_image == "before"
        assert list(layer) == [old_shape]

        stack.redo()
        assert target.base_image == "after"
        assert list(layer) == [new_shape]


# --- Property-based tests -------------------------------------------------

from hypothesis import given
from hypothesis import strategies as st


@given(n=st.integers(min_value=0, max_value=15))
def test_n_pushes_then_n_undos_then_n_redos_returns_to_fully_undoable(n):
    # Distinct, never-mergeable fake mementos, so no absorption muddies
    # the count — this is purely about the generic stack bookkeeping.
    stack = UndoRedoStack()
    for i in range(n):
        stack.push(FakeMemento(f"m{i}", []))

    for _ in range(n):
        stack.undo()
    assert not stack.can_undo
    assert stack.can_redo == (n > 0)

    for _ in range(n):
        stack.redo()
    assert stack.can_undo == (n > 0)
    assert not stack.can_redo


@given(n=st.integers(min_value=0, max_value=15))
def test_undo_count_never_exceeds_pushes_minus_undos(n):
    stack = UndoRedoStack()
    for i in range(n):
        stack.push(FakeMemento(f"m{i}", []))
    undone = 0
    while stack.undo():
        undone += 1
    assert undone == n


def test_element_change_memento_restore_is_self_inverting():
    # restore() then restore() again on the result must reproduce the
    # original layer state exactly — the structural property the whole
    # undo/redo system depends on.
    layer = Layer()
    before, after = shape("before"), shape("after")
    layer.add(before)
    layer.replace(before, after)

    memento = ElementChangeMemento(layer, before=before, after=after)
    redo_memento = memento.restore()
    assert list(layer) == [before]

    redo_memento.restore()
    assert list(layer) == [after]
