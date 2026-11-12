.pragma library

function select(selectedIds, anchorId, diskId, modifiers, visibleIds) {
  var control = (modifiers & Qt.ControlModifier) !== 0
  var shift = (modifiers & Qt.ShiftModifier) !== 0
  var anchorIndex = visibleIds.indexOf(anchorId)
  var index = visibleIds.indexOf(diskId)

  if (shift && anchorIndex >= 0 && index >= 0) {
    var range = visibleIds.slice(Math.min(anchorIndex, index), Math.max(anchorIndex, index) + 1)
    if (control) {
      range = selectedIds.concat(range.filter(function(id) { return selectedIds.indexOf(id) < 0 }))
    }
    return { ids: range, anchor: anchorId }
  }

  if (control && !shift) {
    var selection = selectedIds.slice()
    var selectedIndex = selection.indexOf(diskId)
    if (selectedIndex >= 0) selection.splice(selectedIndex, 1)
    else selection.push(diskId)
    return { ids: selection, anchor: diskId }
  }

  return { ids: [diskId], anchor: diskId }
}
