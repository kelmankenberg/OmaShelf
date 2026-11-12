import QtQuick
import QtTest
import "../Selection.js" as Selection

TestCase {
  name: "LibrarySelection"
  property var ids: ["a", "b", "c", "d", "e"]

  function test_plain_click_replaces_selection() {
    var selected = Selection.select(["a", "c"], "c", "b", Qt.NoModifier, ids)
    compare(selected.ids, ["b"])
    compare(selected.anchor, "b")
    compare(Selection.select(["b"], "b", "b", Qt.NoModifier, ids).ids, ["b"])
  }

  function test_control_click_toggles_without_changing_other_items() {
    var previous = ["a"]
    var selected = Selection.select(previous, "a", "c", Qt.ControlModifier, ids)
    compare(selected.ids, ["a", "c"])
    compare(previous, ["a"])
    compare(selected.anchor, "c")
    compare(Selection.select(selected.ids, "c", "a", Qt.ControlModifier, ids).ids, ["c"])
    compare(Selection.select(["a"], "a", "a", Qt.ControlModifier, ids).ids, [])
  }

  function test_shift_selects_an_inclusive_range_and_preserves_anchor() {
    var selected = Selection.select(["b", "e"], "b", "d", Qt.ShiftModifier, ids)
    compare(selected.ids, ["b", "c", "d"])
    compare(selected.anchor, "b")
    selected = Selection.select(selected.ids, selected.anchor, "c", Qt.ShiftModifier, ids)
    compare(selected.ids, ["b", "c"])
    compare(Selection.select(["d"], "d", "b", Qt.ShiftModifier, ids).ids, ["b", "c", "d"])
  }

  function test_ranges_use_visible_order_and_do_not_include_filtered_items() {
    compare(Selection.select(["e"], "e", "b", Qt.ShiftModifier, ["e", "c", "b", "a"]).ids,
      ["e", "c", "b"])
    var selected = Selection.select(["a"], "a", "d", Qt.ShiftModifier, ["b", "d", "e"])
    compare(selected.ids, ["d"])
    compare(selected.anchor, "d")
    compare(Selection.select([], "", "b", Qt.ShiftModifier, ids).ids, ["b"])
  }

  function test_control_shift_adds_a_range_without_duplicates() {
    var selected = Selection.select(["a", "c", "e"], "c", "d",
      Qt.ControlModifier | Qt.ShiftModifier, ids)
    compare(selected.ids, ["a", "c", "e", "d"])
    compare(selected.anchor, "c")
  }
}
