import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Selection.js" as Selection

Panel {
  id: root
  moduleName: "kel.omashelf"
  ipcTarget: "kel.omashelf"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property bool openedFromHotkey: false
  property bool applicationWindowVisible: false
  property bool scanning: false
  property string launchMode: "docked"
  property string message: ""
  property string errorMessage: ""
  property var searchTerms: []
  property string searchDraft: ""
  readonly property string selectedDiskId: selectedDiskIds.length === 1 ? selectedDiskIds[0] : ""
  property var selectedDiskIds: []
  property string selectionAnchorId: ""
  property var disks: []
  property int fileCount: 0
  property var mounted: []
  property var audioDrives: []
  property var searchResults: []
  property bool searchTruncated: false
  property bool commandRunning: false
  property string pendingAction: ""
  property var queuedActions: []
  property bool searchPending: false
  property bool refreshPending: false
  property string commandOutput: ""
  property string commandError: ""
  signal diskEditFinished(string diskId, bool saved, string error)
  signal bulkEditFinished(bool saved, string error)
  signal importInspected(var preview, string error)
  signal importFinished(bool saved, string error)
  property string editingDiskId: ""

  readonly property string pluginDir: {
    var url = String(Qt.resolvedUrl("./"))
    if (url.indexOf("file://") !== 0) return ""
    try { return decodeURIComponent(url.substring(7)).replace(/\/$/, "") } catch (e) { return "" }
  }
  readonly property string helperPath: pluginDir + "/bin/omashelf.py"
  readonly property string dataDir: Quickshell.env("OMASHELF_DATA_DIR")
    || ((Quickshell.env("XDG_DATA_HOME") || (Quickshell.env("HOME") + "/.local/share"))
      + "/omashelf")
  readonly property string statusPath: dataDir + "/status.json"

  function run(action, args) {
    if (commandRunning) return false
    if (!helperPath) {
      errorMessage = "OmaShelf helper path is unavailable."
      return false
    }
    pendingAction = action
    if (action === "edit-disk") editingDiskId = args[0]
    commandRunning = true
    if (action !== "overview" && action !== "search-terms") errorMessage = ""
    process.command = ["python3", helperPath, action].concat(args || [])
    process.running = true
    return true
  }

  function runOrQueue(action, args) {
    if (!helperPath) {
      errorMessage = "OmaShelf helper path is unavailable."
      return false
    }
    if (!commandRunning) return run(action, args)

    var queued = queuedActions.slice()
    if (action === "set-mode")
      queued = queued.filter(function(item) { return item.action !== "set-mode" })
    if (action === "scan")
      queued = queued.filter(function(item) {
        return item.action !== "scan" || item.args[0] !== args[0]
      })
    queued.push({ action: action, args: args || [] })
    queuedActions = queued
    if (action === "set-mode")
      message = "Switching to " + (args[0] === "app" ? "app" : "docked") + " mode…"
    else if (action === "scan")
      message = "Queued scan of " + args[0]
    return true
  }

  function parseResponse(raw) {
    try {
      return JSON.parse(String(raw || "").trim())
    } catch (error) {
      return null
    }
  }

  function applyOverview(value) {
    disks = Array.isArray(value.disks) ? value.disks : []
    selectedDiskIds = selectedDiskIds.filter(function(id) {
      return disks.some(function(disk) { return disk.id === id })
    })
    if (!disks.some(function(disk) { return disk.id === root.selectionAnchorId }))
      selectionAnchorId = ""
    fileCount = Number(value.fileCount || 0)
    mounted = Array.isArray(value.mounted) ? value.mounted : []
    audioDrives = Array.isArray(value.audioDrives) ? value.audioDrives : []
    launchMode = value.mode === "app" ? "app" : "docked"
    searchCatalog()
  }

  function handleOutput(raw) {
    var action = pendingAction
    var value = parseResponse(raw)
    if (!value || value.ok !== true) {
      errorMessage = value && value.error ? String(value.error) : "OmaShelf received an invalid response."
      if (action === "edit-disk") diskEditFinished(editingDiskId, false, errorMessage)
      if (action === "edit-disks") bulkEditFinished(false, errorMessage)
      if (action === "inspect-import") importInspected(null, errorMessage)
      if (action === "import-library") importFinished(false, errorMessage)
      return
    }
    if (action === "overview") {
      applyOverview(value)
    } else if (action === "search-terms") {
      searchResults = Array.isArray(value.results) ? value.results : []
      searchTruncated = value.truncated === true
    } else if (action === "scan") {
      message = "Catalogued " + String(value.label || "disk") + " (" + String(value.files || 0) + " files)."
      if (value.partial) errorMessage = (value.errors || []).join("\n")
      refresh()
    } else if (action === "identify-audio") {
      message = (value.identified ? "Identified " : "Added audio CD: ")
        + String(value.title || "Audio CD")
        + (value.artist ? " — " + String(value.artist) : "")
      if (value.lookupError) errorMessage = String(value.lookupError)
      refresh()
    } else if (action === "edit-disk") {
      message = "Saved disc details."
      diskEditFinished(String(value.diskId), true, "")
      refresh()
    } else if (action === "edit-disks") {
      message = "Updated " + String(value.updated) + " discs."
      bulkEditFinished(true, "")
      refresh()
    } else if (action === "export-library") {
      message = "Exported " + String(value.diskCount) + " discs to " + String(value.path)
    } else if (action === "inspect-import") {
      importInspected(value, "")
    } else if (action === "import-library") {
      clearDiskSelection()
      searchResults = []
      message = "Imported library: " + String(value.added) + " added, "
        + String(value.updated) + " replaced, " + String(value.skipped) + " kept."
      importFinished(true, "")
      refresh()
    } else if (action === "delete-disk" || action === "delete-disks") {
      var deletedIds = Array.isArray(value.diskIds) ? value.diskIds : [value.diskId]
      clearDiskSelection()
      searchResults = []
      var deletedCount = Number(value.deleted || deletedIds.length)
      message = "Removed " + String(deletedCount)
        + (deletedCount === 1 ? " disk from" : " disks from") + " the library."
      refresh()
    } else if (action === "set-mode") {
      launchMode = value.mode === "app" ? "app" : "docked"
      if (launchMode === "app") openAsApp()
      else closeApplicationWindow()
    }
  }

  function finishCommand(exitCode) {
    handleOutput(commandOutput)
    if (exitCode !== 0 && !parseResponse(commandOutput)) {
      errorMessage = commandError || "OmaShelf helper failed."
    }
    commandRunning = false
    pendingAction = ""
    if (queuedActions.length) {
      var next = queuedActions[0]
      queuedActions = queuedActions.slice(1)
      Qt.callLater(function() { root.run(next.action, next.args) })
      return
    }
    if (refreshPending) {
      refreshPending = false
      Qt.callLater(refresh)
      return
    }
    if (searchPending) {
      searchPending = false
      Qt.callLater(searchCatalog)
    }
  }

  function refresh() {
    if (commandRunning) {
      refreshPending = true
      return
    }
    run("overview", [])
  }

  function scanPath(path) {
    if (!path) return
    message = "Scanning " + path
    runOrQueue("scan", [path])
  }

  function identifyAudio(device) {
    if (!device) return
    message = "Identifying audio CD in " + device
    runOrQueue("identify-audio", [device])
  }

  function deleteDisk(diskId) {
    if (!diskId) return
    runOrQueue("delete-disk", [diskId])
  }

  function editDisk(diskId, values) {
    return runOrQueue("edit-disk", [diskId, JSON.stringify(values)])
  }

  function editDisks(diskIds, changes) {
    return runOrQueue("edit-disks", [JSON.stringify(diskIds), JSON.stringify(changes)])
  }

  function exportLibrary(path) {
    return runOrQueue("export-library", [path])
  }

  function inspectImport(path) {
    return runOrQueue("inspect-import", [path])
  }

  function importLibrary(preview, mode, conflicts) {
    return runOrQueue("import-library", [preview.path, mode, conflicts, preview.fingerprint])
  }

  function deleteDisks(diskIds) {
    if (!Array.isArray(diskIds) || !diskIds.length) return
    runOrQueue("delete-disks", diskIds)
  }

  function selectDisk(diskId, modifiers, visibleIds) {
    var selection = Selection.select(selectedDiskIds, selectionAnchorId, diskId, modifiers, visibleIds)
    selectedDiskIds = selection.ids
    selectionAnchorId = selection.anchor
  }

  function clearDiskSelection() {
    selectedDiskIds = []
    selectionAnchorId = ""
  }

  function setMode(mode) {
    if (mode !== "app" && mode !== "docked") return
    runOrQueue("set-mode", [mode])
  }

  function searchCatalog() {
    if (commandRunning) {
      searchPending = true
      return
    }
    var terms = searchTerms.slice()
    if (searchDraft.trim()) terms.push(searchDraft.trim())
    run("search-terms", [selectedDiskId].concat(terms))
  }

  function activateFromBar() {
    if (launchMode === "app") openAsApp()
    else toggle()
  }

  function openAsApp() {
    applicationWindowVisible = true
    appWindow.visible = true
    appWindow.requestActivate()
    close()
  }

  function closeApplicationWindow() {
    applicationWindowVisible = false
    appWindow.visible = false
  }

  function openFromHotkey() {
    if (launchMode === "app") openAsApp()
    else {
      openedFromHotkey = true
      controller.show()
      refresh()
    }
  }

  function closeForPopoutSwitch() {
    popoutSwitchClosing = true
    close()
    Qt.callLater(function() { popoutSwitchClosing = false })
  }

  function switchPanel(direction) {
    if (bar && typeof bar.switchPanelFrom === "function")
      return bar.switchPanelFrom(hostWidget || root, direction)
    return false
  }

  onSearchTermsChanged: searchTimer.restart()
  onSearchDraftChanged: searchTimer.restart()
  onSelectedDiskIdChanged: searchTimer.restart()

  Component.onCompleted: refresh()

  Timer {
    id: searchTimer
    interval: 220
    onTriggered: root.searchCatalog()
  }

  Process {
    id: process
    stdout: SplitParser {
      onRead: function(line) { root.commandOutput += line + "\n" }
    }
    stderr: SplitParser {
      onRead: function(line) { root.commandError += line + "\n" }
    }
    onStarted: {
      root.commandOutput = ""
      root.commandError = ""
    }
    onExited: function(exitCode) {
      Qt.callLater(function() { root.finishCommand(exitCode) })
    }
  }

  FileView {
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      var value = root.parseResponse(text())
      root.scanning = !!(value && value.scanning === true)
    }
    onLoadFailed: root.scanning = false
  }

  KeyboardPanel {
    id: popup
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    centerOnBar: false
    focusTarget: popup.loadedContent
    contentWidth: popup.fittedContentWidth(Style.space(920))
    contentHeight: popup.fittedContentHeight(Style.space(650))
    content: Item {
      anchors.fill: parent
      CatalogView {
        anchors.fill: parent
        controller: root
      }
    }
  }

  Window {
    id: appWindow
    title: "OmaShelf"
    width: 1040
    height: 720
    minimumWidth: 760
    minimumHeight: 520
    visible: root.applicationWindowVisible
    color: Color.background

    onClosing: function(event) {
      root.applicationWindowVisible = false
    }

    CatalogView {
      anchors.fill: parent
      controller: root
      standalone: true
    }
  }
}
