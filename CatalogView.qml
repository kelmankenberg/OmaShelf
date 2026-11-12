import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import Quickshell
import qs.Commons

Item {
  id: root
  property var controller: null
  property bool standalone: false
  property bool restorePanelAfterPicker: false
  property string tab: "dashboard"
  property bool deleteConfirmationOpen: false
  property string deleteConfirmationText: ""
  property var deleteDiskIds: []
  property string diskTypeFilter: "all"
  property var diskLabelTerms: []
  property string diskLabelDraft: ""
  property string editingDiskId: ""
  property var editingDiskIds: []
  property bool editBulk: false
  property bool editingAudio: false
  property var editingTags: []
  property string editingTagDraft: ""
  property bool editSaving: false
  property string editError: ""
  property var importPreview: null
  property bool importBusy: false
  property string importError: ""
  readonly property var filteredDisks: {
    var disks = root.controller ? root.controller.disks : []
    var labelTerms = root.diskLabelTerms.concat([root.diskLabelDraft.trim()])
    return disks.filter(function(disk) {
      var typeMatches = root.diskTypeFilter === "all" || disk.kind === root.diskTypeFilter
      var labelMatches = labelTerms.every(function(term) {
        return String(disk.label || "").toLowerCase().indexOf(term.toLowerCase()) >= 0
          || (disk.tags || []).some(function(tag) {
            return tag.toLowerCase().indexOf(term.toLowerCase()) >= 0
          })
      })
      return typeMatches && labelMatches
    })
  }
  implicitWidth: Style.space(920)
  implicitHeight: Style.space(650)

  component PlainText: Text {
    textFormat: Text.PlainText
    color: Color.popups.text
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    wrapMode: Text.Wrap
  }

  component ActionButton: Item {
    id: action
    property string text: ""
    property bool discAccent: false
    signal clicked()
    implicitWidth: buttonText.implicitWidth + Style.space(24)
    implicitHeight: Style.space(34)
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.5
    Rectangle {
      anchors.fill: parent
      radius: Style.cornerRadius
      color: action.discAccent ? Color.accent : buttonMouse.containsMouse ? Color.popups.border : "transparent"
      border.color: action.discAccent ? Color.accent : Color.popups.border
      border.width: 1
    }
    PlainText {
      id: buttonText
      anchors.centerIn: parent
      width: parent.width - Style.space(16)
      text: action.text
      color: action.discAccent ? Color.background : Color.popups.text
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
      elide: Text.ElideRight
    }
    Keys.onReturnPressed: clicked()
    Keys.onEnterPressed: clicked()
    Keys.onSpacePressed: clicked()
    MouseArea {
      id: buttonMouse
      anchors.fill: parent
      enabled: action.enabled
      hoverEnabled: true
      cursorShape: action.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: action.clicked()
    }
  }

  component FieldToggle: CheckBox {
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    palette.windowText: Color.popups.text
  }

  component EditInput: TextField {
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    color: Color.popups.text
    selectByMouse: true
    activeFocusOnTab: true
    padding: Style.space(8)
    background: Rectangle {
      radius: Style.cornerRadius
      color: Color.background
      border.color: parent.activeFocus ? Color.accent : Color.popups.border
      border.width: 1
    }
  }

  component TermFilter: Item {
    id: filter
    property var terms: []
    property string draft: ""
    property string placeholderText: "Filter…"
    property string additionalPlaceholderText: "Narrow by another term…"
    signal termsEdited(var value)
    signal draftEdited(string value)
    implicitHeight: Style.space(38)
    implicitWidth: Style.space(300)

    function removeTerm(index) {
      var next = terms.slice()
      next.splice(index, 1)
      termsEdited(next)
      termInput.forceActiveFocus()
    }

    function addTerm() {
      var term = termInput.text.trim()
      if (!term) return
      if (!terms.some(function(value) { return value.toLowerCase() === term.toLowerCase() }))
        termsEdited(terms.concat([term]))
      draftEdited("")
    }

    Rectangle {
      anchors.fill: parent
      radius: Style.cornerRadius
      color: Color.background
      border.color: termInput.activeFocus ? Color.accent : Color.popups.border
      border.width: 1
    }

    RowLayout {
      anchors.fill: parent
      anchors.margins: Style.space(5)
      spacing: Style.space(6)

      Item {
        Layout.preferredWidth: Style.space(20)
        Layout.fillHeight: true
        Rectangle {
          anchors.centerIn: parent
          width: Style.space(10)
          height: width
          radius: width / 2
          color: "transparent"
          border.color: Color.muted
          border.width: 1
          Rectangle {
            x: parent.width - 1
            y: parent.height - 2
            width: Style.space(5)
            height: 1
            rotation: 45
            transformOrigin: Item.Left
            color: Color.muted
          }
        }
      }

      Flickable {
        id: chips
        visible: filter.terms.length > 0
        Layout.preferredWidth: Math.min(chipRow.width, filter.width * 0.6)
        Layout.fillHeight: true
        contentWidth: chipRow.width
        contentHeight: height
        flickableDirection: Flickable.HorizontalFlick
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        onContentWidthChanged: contentX = Math.max(0, contentWidth - width)
        onWidthChanged: contentX = Math.max(0, contentWidth - width)

        Row {
          id: chipRow
          height: parent.height
          spacing: Style.space(4)
          Repeater {
            model: filter.terms
            delegate: Item {
              required property string modelData
              required property int index
              width: Math.min(chipText.implicitWidth + Style.space(36), filter.width * 0.5)
              height: chipRow.height
              Rectangle {
                anchors.fill: parent
                color: "transparent"
                border.color: Color.popups.border
                border.width: 1
                radius: Style.space(3)
              }
              PlainText {
                id: chipText
                anchors.left: parent.left
                anchors.leftMargin: Style.space(7)
                anchors.right: removeChip.left
                anchors.verticalCenter: parent.verticalCenter
                text: modelData
                font.pixelSize: Style.font.bodySmall
                wrapMode: Text.NoWrap
                elide: Text.ElideRight
              }
              ActionButton {
                id: removeChip
                anchors.right: parent.right
                height: parent.height
                width: Style.space(24)
                text: "×"
                onClicked: filter.removeTerm(index)
              }
            }
          }
        }
      }

      TextField {
        id: termInput
        Layout.fillWidth: true
        Layout.fillHeight: true
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        color: Color.popups.text
        placeholderTextColor: Color.muted
        placeholderText: filter.terms.length ? filter.additionalPlaceholderText : filter.placeholderText
        text: filter.draft
        maximumLength: 300
        padding: 0
        selectByMouse: true
        activeFocusOnTab: true
        background: Item {}
        onTextEdited: filter.draftEdited(text)
        onAccepted: filter.addTerm()
        Keys.onPressed: function(event) {
          if (event.key === Qt.Key_Backspace && !text.length && filter.terms.length) {
            filter.removeTerm(filter.terms.length - 1)
            event.accepted = true
          } else {
            event.accepted = false
          }
        }
      }

      ActionButton {
        visible: filter.terms.length > 0 || filter.draft.length > 0
        Layout.preferredWidth: Style.space(28)
        Layout.fillHeight: true
        text: "×"
        onClicked: {
          filter.termsEdited([])
          filter.draftEdited("")
          termInput.forceActiveFocus()
        }
      }
    }
  }

  function requestEdit(disk) {
    root.editBulk = false
    root.editingDiskId = String(disk.id)
    root.editingAudio = disk.kind === "audio"
    editLabel.text = String(disk.label || "")
    editArtist.text = String(disk.artist || "")
    editPath.text = String(disk.path || "")
    editNumber.text = disk.disc_number ? String(disk.disc_number) : ""
    editTotal.text = disk.disc_count ? String(disk.disc_count) : ""
    root.editingTags = (disk.tags || []).slice()
    root.editingTagDraft = ""
    root.editError = ""
    root.editSaving = false
    editDialog.open()
    editLabel.forceActiveFocus()
  }

  function requestBulkEdit() {
    if (!root.controller || !root.controller.selectedDiskIds.length) return
    root.editBulk = true
    root.editingDiskId = ""
    root.editingDiskIds = root.controller.selectedDiskIds.slice()
    root.editingAudio = root.editingDiskIds.every(function(id) {
      return root.controller.disks.some(function(disk) {
        return disk.id === id && disk.kind === "audio"
      })
    })
    editLabel.text = ""
    editArtist.text = ""
    editPath.text = ""
    editNumber.text = ""
    editTotal.text = ""
    changeLabel.checked = false
    changeArtist.checked = false
    changePath.checked = false
    changeNumber.checked = false
    tagOperation.currentIndex = 0
    root.editingTags = []
    root.editingTagDraft = ""
    root.editError = ""
    root.editSaving = false
    editDialog.open()
    changeLabel.forceActiveFocus()
  }

  function saveEdit() {
    var number = editNumber.text.trim()
    var total = editTotal.text.trim()
    if (root.editingAudio && (!root.editBulk || changeNumber.checked) && (number || total)
        && (!/^\d+$/.test(number) || !/^\d+$/.test(total)
          || Number(number) < 1 || Number(number) > Number(total) || Number(total) > 1000)) {
      root.editError = "Enter a CD number and total between 1 and 1000, or leave both blank."
      return
    }
    var tags = root.editingTags.slice()
    if (root.editingTagDraft.trim()) tags.push(root.editingTagDraft.trim())
    if (!root.controller) return
    root.editError = ""
    root.editSaving = true
    var fields = {}
    if (!root.editBulk || changeLabel.checked) fields.label = editLabel.text
    if (!root.editBulk || changeArtist.checked) fields.artist = editArtist.text
    if (!root.editBulk || changePath.checked) fields.path = editPath.text
    if (!root.editBulk || changeNumber.checked) {
      fields.disc_number = root.editingAudio && number ? Number(number) : null
      fields.disc_count = root.editingAudio && total ? Number(total) : null
    }
    var submitted
    if (root.editBulk) {
      submitted = root.controller.editDisks(root.editingDiskIds, {
        fields: fields,
        tagOperation: ["keep", "add", "remove", "replace"][tagOperation.currentIndex],
        tags: tagOperation.currentIndex === 0 ? [] : tags
      })
    } else {
      fields.tags = tags
      submitted = root.controller.editDisk(root.editingDiskId, fields)
    }
    if (!submitted) {
      root.editSaving = false
      root.editError = root.controller.errorMessage
    }
  }

  Connections {
    target: root.controller
    function onDiskEditFinished(diskId, saved, error) {
      if (root.editBulk || diskId !== root.editingDiskId || !editDialog.visible) return
      root.editSaving = false
      if (saved) editDialog.close()
      else root.editError = error
    }
    function onBulkEditFinished(saved, error) {
      if (!root.editBulk || !editDialog.visible) return
      root.editSaving = false
      if (saved) editDialog.close()
      else root.editError = error
    }
  }

  function requestDelete(ids) {
    if (!root.controller || !Array.isArray(ids) || !ids.length) return
    root.deleteDiskIds = ids.slice()
    if (ids.length === 1) {
      var disk = root.controller.disks.find(function(item) { return item.id === ids[0] })
      var label = disk ? String(disk.label || "Untitled disk") : "selected disk"
      root.deleteConfirmationText = "Remove \"" + label
        + "\" and its indexed file list? The original media will not be changed."
    } else {
      root.deleteConfirmationText = "Remove " + String(ids.length)
        + " selected disks and their indexed file lists? The original media will not be changed."
    }
    root.deleteConfirmationOpen = true
  }

  function localFilePath(url) {
    var value = String(url)
    try {
      if (value.indexOf("file:///") !== 0) throw new Error("Choose a local file.")
      return decodeURIComponent(value.substring(7))
    } catch (error) {
      if (root.controller) root.controller.errorMessage = "Could not use the selected file: " + String(error)
      return ""
    }
  }

  function openLibraryPicker(picker) {
    if (picker === exportPicker) {
      var filename = "OmaShelf_backup_" + Qt.formatDateTime(new Date(), "yyyy-MM-dd_HH-mm-ss")
        + "." + exportPicker.defaultSuffix
      exportPicker.selectedFile = String(exportPicker.currentFolder).replace(/\/$/, "") + "/" + filename
    }
    root.restorePanelAfterPicker = !root.standalone && !!root.controller && root.controller.opened
    if (root.restorePanelAfterPicker) root.controller.close()
    picker.open()
  }

  function restoreLibraryPanel() {
    if (!root.restorePanelAfterPicker) return
    root.restorePanelAfterPicker = false
    if (root.controller) root.controller.openFromHotkey()
  }

  function requestImport(path) {
    root.importPreview = null
    root.importError = ""
    root.importBusy = true
    importMode.currentIndex = 0
    importConflicts.currentIndex = 0
    replaceConfirmation.checked = false
    importDialog.open()
    if (!root.controller || !root.controller.inspectImport(path)) {
      root.importBusy = false
      root.importError = root.controller ? root.controller.errorMessage : "OmaShelf is unavailable."
    }
  }

  function openFeedback(bug) {
    var title = bug ? "Bug report: " : "Feature request: "
    var body = bug
      ? "## What happened?\n\n\n## Steps to reproduce\n\n1. \n\n## Expected behavior\n\n\n## Environment\n\nOmaShelf version:\nOmarchy version:\n\n## Screenshots or logs (optional)\n\nReview attachments for private information before submitting."
      : "## Desired feature\n\n\n## Why would this help?\n\n\n## Suggested behavior\n\n"
    if (!Qt.openUrlExternally("https://github.com/kelmankenberg/OmaShelf/issues/new?title="
        + encodeURIComponent(title) + "&body=" + encodeURIComponent(body))) {
      if (root.controller) root.controller.errorMessage = "Could not open GitHub in your browser."
    }
  }

  function diskType(disk) {
    if (disk.kind !== "audio") return "Data disk"
    if (disk.disc_number && disk.disc_count)
      return "CD " + String(disk.disc_number) + " of " + String(disk.disc_count)
    return "Audio CD"
  }

  function diskStatus(disk) {
    if (!root.controller) return "Offline"
    for (var i = 0; i < root.controller.mounted.length; i++) {
      var volume = root.controller.mounted[i]
      if (disk.id === volume.id)
        return "Mounted"
    }
    for (var j = 0; j < root.controller.audioDrives.length; j++) {
      var drive = root.controller.audioDrives[j]
      if (disk.id === "audio:" + drive.discId && drive.present) return "In drive"
    }
    return "Offline"
  }

  FolderDialog {
    id: folderPicker
    currentFolder: "file://" + Quickshell.env("HOME")
    onAccepted: {
      var localPath = selectedFolder.toLocalFile()
      if (root.controller) root.controller.scanPath(localPath)
    }
  }

  FileDialog {
    id: exportPicker
    title: "Export OmaShelf library"
    fileMode: FileDialog.SaveFile
    nameFilters: ["JSON library (*.json)", "XML library (*.xml)"]
    defaultSuffix: selectedNameFilter.index === 1 ? "xml" : "json"
    currentFolder: "file://" + Quickshell.env("HOME")
    onAccepted: {
      root.restoreLibraryPanel()
      var path = root.localFilePath(selectedFile)
      if (path && root.controller) root.controller.exportLibrary(path)
    }
    onRejected: root.restoreLibraryPanel()
  }

  FileDialog {
    id: importPicker
    title: "Import OmaShelf library"
    fileMode: FileDialog.OpenFile
    nameFilters: ["OmaShelf libraries (*.json *.xml)"]
    currentFolder: "file://" + Quickshell.env("HOME")
    onAccepted: {
      root.restoreLibraryPanel()
      var path = root.localFilePath(selectedFile)
      if (path) root.requestImport(path)
    }
    onRejected: root.restoreLibraryPanel()
  }

  Rectangle {
    anchors.fill: parent
    color: Color.popups.background
    radius: Style.cornerRadius
    border.color: Color.popups.border
    border.width: 1
  }

  ColumnLayout {
    anchors.fill: parent
    anchors.margins: Style.space(18)
    spacing: Style.space(12)

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(8)
      PlainText {
        text: "OmaShelf"
        font.pixelSize: Style.font.title
        font.bold: true
        Layout.fillWidth: true
      }
      PlainText {
        text: root.controller && root.controller.scanning ? "Scanning…" : "Local catalog"
        color: root.controller && root.controller.scanning ? Color.accent : Color.muted
      }
      ActionButton {
        text: root.controller && root.controller.launchMode === "app" ? "Use docked mode" : "Open as app"
        onClicked: {
          if (root.controller)
            root.controller.setMode(root.controller.launchMode === "app" ? "docked" : "app")
        }
      }
      ActionButton {
        text: "Refresh"
        enabled: root.controller && !root.controller.commandRunning
        onClicked: if (root.controller) root.controller.refresh()
      }
      ActionButton {
        text: "×"
        visible: root.standalone
        onClicked: if (root.controller) root.controller.closeApplicationWindow()
      }
    }

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(8)
      ActionButton {
        text: "Dashboard"
        discAccent: root.tab === "dashboard"
        onClicked: root.tab = "dashboard"
      }
      ActionButton {
        text: "Library"
        discAccent: root.tab === "library"
        onClicked: root.tab = "library"
      }
      Item { Layout.fillWidth: true }
      ActionButton {
        text: "Export…"
        enabled: !!root.controller && !root.controller.commandRunning
        onClicked: root.openLibraryPicker(exportPicker)
      }
      ActionButton {
        text: "Import…"
        enabled: !!root.controller && !root.controller.commandRunning
        onClicked: root.openLibraryPicker(importPicker)
      }
      ActionButton {
        text: "Feedback"
        onClicked: feedbackMenu.open()
        Menu {
          id: feedbackMenu
          MenuItem { text: "Request a feature…"; onTriggered: root.openFeedback(false) }
          MenuItem { text: "Report a bug…"; onTriggered: root.openFeedback(true) }
        }
      }
      PlainText {
        text: root.controller
          ? String(root.controller.disks.length) + " disks · " + String(root.controller.fileCount || 0) + " files"
          : ""
        color: Color.muted
      }
    }

    PlainText {
      visible: !!(root.controller && root.controller.message)
      text: root.controller ? root.controller.message : ""
      color: Color.accent
      Layout.fillWidth: true
      elide: Text.ElideRight
    }

    PlainText {
      visible: !!(root.controller && root.controller.errorMessage)
      text: root.controller ? root.controller.errorMessage : ""
      color: Color.urgent
      Layout.fillWidth: true
      maximumLineCount: 3
      elide: Text.ElideRight
    }

    Item {
      Layout.fillWidth: true
      Layout.fillHeight: true

      ColumnLayout {
        anchors.fill: parent
        visible: root.tab === "dashboard"
        spacing: Style.space(14)

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(10)
          Repeater {
            model: [
              { label: "Disks in library", value: root.controller ? root.controller.disks.length : 0 },
              { label: "Catalogued files", value: root.controller ? root.controller.fileCount : 0 },
              { label: "Mounted volumes", value: root.controller ? root.controller.mounted.length : 0 }
            ]
            delegate: Rectangle {
              required property var modelData
              Layout.fillWidth: true
              Layout.preferredHeight: Style.space(84)
              radius: Style.cornerRadius
              color: Color.background
              border.color: Color.popups.border
              Column {
                anchors.fill: parent
                anchors.margins: Style.space(12)
                spacing: Style.space(4)
                PlainText {
                  text: String(modelData.value)
                  font.pixelSize: Style.font.title
                  font.bold: true
                }
                PlainText {
                  text: modelData.label
                  color: Color.muted
                  font.pixelSize: Style.font.bodySmall
                }
              }
            }
          }
        }

        RowLayout {
          Layout.fillWidth: true
          PlainText {
            text: "Mounted volumes"
            font.bold: true
            Layout.fillWidth: true
          }
          ActionButton {
            text: "Scan a folder…"
            enabled: root.controller && !root.controller.commandRunning
            onClicked: folderPicker.open()
          }
        }

        ListView {
          id: mountedList
          Layout.fillWidth: true
          Layout.fillHeight: true
          clip: true
          spacing: Style.space(6)
          model: root.controller ? root.controller.mounted : []
          visible: count > 0
          delegate: Rectangle {
            required property var modelData
            width: mountedList.width
            height: Style.space(58)
            radius: Style.cornerRadius
            color: Color.background
            border.color: Color.popups.border
            RowLayout {
              anchors.fill: parent
              anchors.margins: Style.space(10)
              spacing: Style.space(10)
              ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                PlainText {
                  text: String(modelData.label || modelData.path)
                  font.bold: true
                  elide: Text.ElideRight
                  Layout.fillWidth: true
                }
                PlainText {
                  text: String(modelData.path) + " · " + String(modelData.fstype)
                  color: Color.muted
                  font.pixelSize: Style.font.bodySmall
                  elide: Text.ElideMiddle
                  Layout.fillWidth: true
                }
              }
              PlainText {
                text: modelData.catalogued ? "Catalogued" : "Not catalogued"
                color: modelData.catalogued ? Color.accent : Color.muted
              }
              ActionButton {
                text: modelData.catalogued ? "Rescan" : "Scan"
                enabled: !!root.controller
                onClicked: root.controller.scanPath(String(modelData.path))
              }
            }
          }
        }

        PlainText {
          visible: !mountedList.count
          text: "No mounted data volumes found. Insert or mount a disk, then refresh."
          color: Color.muted
        }

        PlainText {
          text: "Audio CDs"
          font.bold: true
        }
        ListView {
          Layout.fillWidth: true
          Layout.preferredHeight: Math.min(contentHeight, Style.space(120))
          clip: true
          spacing: Style.space(6)
          model: root.controller ? root.controller.audioDrives : []
          delegate: Rectangle {
            required property var modelData
            width: ListView.view.width
            height: Style.space(54)
            radius: Style.cornerRadius
            color: Color.background
            border.color: Color.popups.border
            RowLayout {
              anchors.fill: parent
              anchors.margins: Style.space(10)
              PlainText {
                text: String(modelData.device) + (modelData.present
                  ? " · " + String(modelData.tracks) + " tracks · " + (modelData.catalogued ? "Catalogued" : "Not catalogued")
                  : " · No readable audio CD")
                Layout.fillWidth: true
                color: modelData.present && !modelData.catalogued ? Color.accent : Color.popups.text
              }
              ActionButton {
                visible: modelData.present
                text: modelData.catalogued ? "Identify again" : "Identify & add"
                enabled: root.controller && !root.controller.commandRunning
                onClicked: root.controller.identifyAudio(String(modelData.device))
              }
            }
          }
        }
        PlainText {
          text: "Identify & add sends the CD's disc ID to MusicBrainz; artwork is requested from Cover Art Archive."
          color: Color.muted
          font.pixelSize: Style.font.bodySmall
          Layout.fillWidth: true
        }
      }

      ColumnLayout {
        anchors.fill: parent
        visible: root.tab === "library"
        spacing: Style.space(8)

        RowLayout {
          objectName: "libraryFilters"
          Layout.fillWidth: true
          Layout.fillHeight: false
          PlainText { text: "Type"; color: Color.muted }
          ComboBox {
            Layout.preferredWidth: Style.space(160)
            model: ["All disks", "Data disks", "Audio CDs"]
            currentIndex: root.diskTypeFilter === "data" ? 1
              : root.diskTypeFilter === "audio" ? 2 : 0
            onActivated: function(index) {
              root.diskTypeFilter = index === 1 ? "data" : index === 2 ? "audio" : "all"
            }
          }
          PlainText { text: "Label / tags"; color: Color.muted }
          TermFilter {
            Layout.fillWidth: true
            placeholderText: "Filter labels or tags…"
            terms: root.diskLabelTerms
            draft: root.diskLabelDraft
            onTermsEdited: function(value) { root.diskLabelTerms = value }
            onDraftEdited: function(value) { root.diskLabelDraft = value }
          }
        }

        Rectangle {
          Layout.fillWidth: true
          Layout.preferredHeight: Style.space(46)
          Layout.maximumHeight: Style.space(46)
          radius: Style.cornerRadius
          color: "transparent"
          border.color: root.controller && root.controller.selectedDiskIds.length
            ? Color.accent : Color.popups.border
          border.width: 1

          RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Style.space(12)
            anchors.rightMargin: Style.space(12)
            spacing: Style.space(8)
            PlainText {
              text: String(root.controller ? root.controller.selectedDiskIds.length : 0)
                + " selected"
              font.bold: true
            }
            ActionButton {
              text: "Edit Selected"
              enabled: !!(root.controller && root.controller.selectedDiskIds.length)
              onClicked: root.requestBulkEdit()
            }
            ActionButton {
              text: "Delete Selected"
              discAccent: true
              enabled: !!(root.controller && root.controller.selectedDiskIds.length)
              onClicked: root.requestDelete(root.controller.selectedDiskIds.slice())
            }
            ActionButton {
              text: "Clear Selection"
              enabled: !!(root.controller && root.controller.selectedDiskIds.length)
              onClicked: if (root.controller) root.controller.clearDiskSelection()
            }
          }
        }

        RowLayout {
          objectName: "libraryHeader"
          Layout.fillWidth: true
          Layout.preferredHeight: Style.space(26)
          Layout.maximumHeight: Style.space(26)
          spacing: Style.space(6)
          PlainText {
            text: "Disk label"
            color: Color.muted
            font.pixelSize: Style.font.bodySmall
            Layout.fillWidth: true
          }
          PlainText {
            text: "Disk type"
            color: Color.muted
            font.pixelSize: Style.font.bodySmall
            Layout.preferredWidth: Style.space(88)
          }
          PlainText {
            text: "Location"
            color: Color.muted
            font.pixelSize: Style.font.bodySmall
            Layout.preferredWidth: Style.space(140)
          }
          PlainText {
            text: "Files"
            color: Color.muted
            font.pixelSize: Style.font.bodySmall
            Layout.preferredWidth: Style.space(48)
          }
          PlainText {
            text: "Status"
            color: Color.muted
            font.pixelSize: Style.font.bodySmall
            Layout.preferredWidth: Style.space(70)
          }
          PlainText {
            text: "Last scanned (UTC)"
            color: Color.muted
            font.pixelSize: Style.font.bodySmall
            Layout.preferredWidth: Style.space(150)
          }
          Item { Layout.preferredWidth: Style.space(24) }
        }

        Rectangle {
          Layout.fillWidth: true
          Layout.preferredHeight: 1
          Layout.maximumHeight: 1
          color: Color.popups.border
        }

        ListView {
          id: diskList
          objectName: "libraryDisks"
          Layout.fillWidth: true
          Layout.preferredHeight: Math.max(Style.space(28), Math.min(contentHeight, Style.space(220)))
          Layout.maximumHeight: Layout.preferredHeight
          Layout.fillHeight: false
          clip: true
          model: root.filteredDisks
          delegate: Item {
            id: diskRow
            objectName: "libraryDiskRow"
            required property var modelData
            width: diskList.width
            height: Style.space(28)
            activeFocusOnTab: true

            function select(modifiers) {
              if (root.controller)
                root.controller.selectDisk(modelData.id, modifiers,
                  root.filteredDisks.map(function(disk) { return disk.id }))
            }

            Keys.onSpacePressed: function(event) { diskRow.select(event.modifiers) }
            Keys.onReturnPressed: function(event) { diskRow.select(event.modifiers) }
            Keys.onEnterPressed: function(event) { diskRow.select(event.modifiers) }

            Rectangle {
              anchors.fill: parent
              color: root.controller
                && root.controller.selectedDiskIds.indexOf(modelData.id) >= 0
                ? Color.popups.border : "transparent"
            }
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: function(mouse) {
                diskRow.forceActiveFocus()
                diskRow.select(mouse.modifiers)
              }
            }
            RowLayout {
              anchors.fill: parent
              spacing: Style.space(6)
              Item {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.fillHeight: true
                PlainText {
                  anchors.left: parent.left
                  anchors.right: rowTags.visible ? rowTags.left : parent.right
                  anchors.rightMargin: rowTags.visible ? Style.space(6) : 0
                  anchors.verticalCenter: parent.verticalCenter
                  text: String(modelData.label || "Untitled disk")
                  font.pixelSize: Style.font.bodySmall
                  wrapMode: Text.NoWrap
                  elide: Text.ElideRight
                }
                PlainText {
                  id: rowTags
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  width: Math.min(implicitWidth, parent.width * 0.4)
                  visible: !!(modelData.tags && modelData.tags.length)
                  text: (modelData.tags || []).join(" · ")
                  color: Color.accent
                  font.pixelSize: Style.font.bodySmall
                  wrapMode: Text.NoWrap
                  elide: Text.ElideRight
                }
              }
              PlainText {
                text: root.diskType(modelData)
                color: Color.muted
                font.pixelSize: Style.font.bodySmall
                Layout.preferredWidth: Style.space(88)
              }
              PlainText {
                text: String(modelData.path || modelData.source || "")
                color: Color.muted
                font.pixelSize: Style.font.bodySmall
                wrapMode: Text.NoWrap
                elide: Text.ElideMiddle
                Layout.preferredWidth: Style.space(140)
              }
              PlainText {
                text: String(modelData.file_count || 0)
                color: Color.muted
                font.pixelSize: Style.font.bodySmall
                Layout.preferredWidth: Style.space(48)
              }
              PlainText {
                text: root.diskStatus(modelData)
                color: text === "Offline" ? Color.muted : Color.accent
                font.pixelSize: Style.font.bodySmall
                Layout.preferredWidth: Style.space(70)
              }
              PlainText {
                text: String(modelData.scanned_at || "Unknown")
                color: Color.muted
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
                Layout.preferredWidth: Style.space(150)
              }
              Item {
                Layout.preferredWidth: Style.space(24)
                Layout.preferredHeight: Style.space(24)
                Menu {
                  id: diskMenu
                  MenuItem {
                    text: "Edit"
                    onTriggered: root.requestEdit(modelData)
                  }
                  MenuItem {
                    text: "Delete"
                    onTriggered: root.requestDelete([String(modelData.id)])
                  }
                }
                ActionButton {
                  anchors.fill: parent
                  text: "⋮"
                  onClicked: diskMenu.open()
                }
              }
            }
            Rectangle {
              anchors.bottom: parent.bottom
              width: parent.width
              height: 1
              color: Color.popups.border
              opacity: 0.5
            }
          }
        }

        PlainText {
          visible: root.controller && root.controller.disks.length === 0
          text: "No disks catalogued yet."
          color: Color.muted
        }
        PlainText {
          visible: !!(root.controller && root.controller.disks.length && !diskList.count)
          text: "No disks match these filters."
          color: Color.muted
        }

        Rectangle {
          Layout.fillWidth: true
          Layout.preferredHeight: 1
          Layout.maximumHeight: 1
          color: Color.popups.border
        }

        RowLayout {
          Layout.fillWidth: true
          Layout.fillHeight: false
          PlainText {
            text: "File search"
            font.bold: true
            Layout.fillWidth: true
          }
          ActionButton {
            visible: !!(root.controller && root.controller.selectedDiskId)
            text: "All disks"
            onClicked: if (root.controller) root.controller.clearDiskSelection()
          }
          PlainText {
            text: root.controller && root.controller.selectedDiskId
              ? "Selected disk"
              : "All disks"
            color: Color.muted
            font.pixelSize: Style.font.bodySmall
          }
        }

        TermFilter {
          Layout.fillWidth: true
          Layout.fillHeight: false
          placeholderText: "Filter file paths or disc tags…"
          terms: root.controller ? root.controller.searchTerms : []
          draft: root.controller ? root.controller.searchDraft : ""
          onTermsEdited: function(value) {
            if (root.controller) root.controller.searchTerms = value
          }
          onDraftEdited: function(value) {
            if (root.controller) root.controller.searchDraft = value
          }
        }

        PlainText {
          text: "Enter adds a term; all terms must match a file path or disc tag. × removes terms."
          color: Color.muted
          font.pixelSize: Style.font.bodySmall
          Layout.fillWidth: true
        }

        ListView {
          id: resultsList
          objectName: "libraryFiles"
          Layout.fillWidth: true
          Layout.fillHeight: true
          clip: true
          visible: !!(root.controller
            && (root.controller.selectedDiskId || root.controller.searchTerms.length || root.controller.searchDraft))
          model: root.controller ? root.controller.searchResults : []
          delegate: Item {
            required property var modelData
            width: resultsList.width
            height: Style.space(46)
            RowLayout {
              anchors.fill: parent
              spacing: Style.space(8)
              ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                PlainText {
                  text: String(modelData.path || "")
                  font.pixelSize: Style.font.bodySmall
                  elide: Text.ElideMiddle
                  Layout.fillWidth: true
                }
                PlainText {
                  text: String(modelData.label || "")
                    + (modelData.kind === "audio" && modelData.disc_number
                      ? " - " + root.diskType(modelData) : "")
                  color: Color.muted
                  font.pixelSize: Style.font.bodySmall
                  elide: Text.ElideRight
                  Layout.fillWidth: true
                }
              }
              ActionButton {
                visible: !!modelData.external_url
                text: "MusicBrainz"
                onClicked: Qt.openUrlExternally(String(modelData.external_url))
              }
            }
            Rectangle {
              anchors.bottom: parent.bottom
              width: parent.width
              height: 1
              color: Color.popups.border
              opacity: 0.5
            }
          }
        }
        PlainText {
          visible: !resultsList.visible
          text: "Select a disk or enter a file filter to browse files."
          color: Color.muted
        }
        PlainText {
          visible: resultsList.visible && resultsList.count === 0 && !!(root.controller
            && (root.controller.searchTerms.length || root.controller.searchDraft))
          text: "No catalogued files match these filters."
          color: Color.muted
        }
        PlainText {
          visible: root.controller && root.controller.searchTruncated && resultsList.visible
          text: "Showing the first 500 matches. Add another filter to narrow the results."
          color: Color.muted
        }
        Item {
          Layout.fillHeight: true
          visible: !resultsList.visible
        }
      }
    }
  }

  Popup {
    id: importDialog
    parent: root
    anchors.centerIn: parent
    width: Math.min(root.width - Style.space(32), Style.space(560))
    height: Math.min(root.height - Style.space(32), importContents.implicitHeight + Style.space(32))
    padding: Style.space(16)
    modal: true
    focus: true
    closePolicy: root.importBusy ? Popup.NoAutoClose : Popup.CloseOnEscape
    background: Rectangle {
      color: Color.popups.background
      border.color: Color.popups.border
      border.width: 1
      radius: Style.cornerRadius
    }
    contentItem: ScrollView {
      id: importScroll
      contentWidth: availableWidth
      clip: true
      ColumnLayout {
        id: importContents
        width: importScroll.availableWidth
        spacing: Style.space(10)
        PlainText { text: "Import library"; font.bold: true; font.pixelSize: Style.font.title }
        PlainText {
          text: root.importBusy ? "Reading or importing library…"
            : root.importPreview ? String(root.importPreview.diskCount) + " discs, "
              + String(root.importPreview.fileCount) + " indexed files.\n"
              + String(root.importPreview.matchingCount) + " discs already exist in your library."
            : "The selected file could not be imported."
          Layout.fillWidth: true
        }
        ComboBox {
          id: importMode
          Layout.fillWidth: true
          enabled: !!root.importPreview && !root.importBusy
          model: ["Merge with existing library", "Replace entire library"]
          onActivated: replaceConfirmation.checked = false
        }
        ComboBox {
          id: importConflicts
          visible: importMode.currentIndex === 0
          Layout.fillWidth: true
          enabled: !!root.importPreview && !root.importBusy
          model: ["Keep existing matching discs", "Replace matching discs with imported data"]
          onActivated: replaceConfirmation.checked = false
        }
        PlainText {
          text: importMode.currentIndex === 1
            ? "Replace removes every current library entry and restores the imported library. Source media is never changed."
            : importConflicts.currentIndex === 1
              ? "Matching disc IDs will be replaced, including their indexed files, tags, and saved edits. Other discs are kept."
              : "New discs are added. Existing matching discs, tags, and edits remain unchanged."
          color: importMode.currentIndex === 1 || importConflicts.currentIndex === 1 ? Color.accent : Color.muted
          Layout.fillWidth: true
        }
        FieldToggle {
          id: replaceConfirmation
          visible: importMode.currentIndex === 1 || importConflicts.currentIndex === 1
          enabled: !root.importBusy
          text: "I confirm replacing the entries described above."
        }
        PlainText {
          visible: !!root.importError
          text: root.importError
          color: Color.urgent
          Layout.fillWidth: true
        }
        RowLayout {
          Layout.fillWidth: true
          Item { Layout.fillWidth: true }
          ActionButton {
            text: "Cancel"
            enabled: !root.importBusy
            onClicked: importDialog.close()
          }
          ActionButton {
            text: "Import"
            discAccent: true
            enabled: !!root.importPreview && !root.importBusy
              && ((importMode.currentIndex === 0 && importConflicts.currentIndex === 0)
                || replaceConfirmation.checked)
            onClicked: {
              root.importBusy = true
              root.importError = ""
              if (!root.controller.importLibrary(root.importPreview,
                    importMode.currentIndex === 1 ? "replace" : "merge",
                    importConflicts.currentIndex === 1 ? "overwrite" : "keep")) {
                root.importBusy = false
                root.importError = root.controller.errorMessage
              }
            }
          }
        }
      }
    }
  }

  Connections {
    target: root.controller
    function onImportInspected(preview, error) {
      if (!importDialog.visible) return
      root.importBusy = false
      root.importPreview = preview
      root.importError = error
    }
    function onImportFinished(saved, error) {
      if (!importDialog.visible) return
      root.importBusy = false
      if (saved) importDialog.close()
      else root.importError = error
    }
  }

  Popup {
    id: editDialog
    parent: root
    anchors.centerIn: parent
    width: Math.min(root.width - Style.space(32), Style.space(560))
    height: Math.min(root.height - Style.space(32), editContents.implicitHeight + Style.space(32))
    padding: Style.space(16)
    modal: true
    focus: true
    closePolicy: root.editSaving ? Popup.NoAutoClose : Popup.CloseOnEscape
    background: Rectangle {
      color: Color.popups.background
      border.color: Color.popups.border
      border.width: 1
      radius: Style.cornerRadius
    }
    contentItem: ScrollView {
      id: editScroll
      contentWidth: availableWidth
      clip: true
      ColumnLayout {
        id: editContents
        width: editScroll.availableWidth
        spacing: Style.space(8)
        enabled: !root.editSaving
        PlainText {
          text: root.editBulk ? "Edit " + String(root.editingDiskIds.length) + " selected discs" : "Edit disc"
          font.bold: true
          font.pixelSize: Style.font.title
        }
        PlainText {
          visible: root.editBulk
          text: "Only checked fields change. Each enabled value is applied to every selected disc."
          color: Color.muted
          Layout.fillWidth: true
        }
        FieldToggle { id: changeLabel; visible: root.editBulk; text: "Change disc label" }
        PlainText { visible: !root.editBulk; text: "Disc label"; color: Color.muted }
        EditInput {
          id: editLabel
          Layout.fillWidth: true
          maximumLength: 240
          enabled: !root.editBulk || changeLabel.checked
          placeholderText: root.editBulk && !changeLabel.checked ? "Unchanged" : ""
        }
        FieldToggle { id: changeArtist; visible: root.editBulk; text: "Change artist" }
        PlainText { visible: !root.editBulk; text: "Artist"; color: Color.muted }
        EditInput {
          id: editArtist
          Layout.fillWidth: true
          maximumLength: 240
          enabled: !root.editBulk || changeArtist.checked
          placeholderText: root.editBulk && !changeArtist.checked ? "Unchanged" : ""
        }
        FieldToggle { id: changePath; visible: root.editBulk; text: "Change location / path" }
        PlainText { visible: !root.editBulk; text: "Location / path"; color: Color.muted }
        EditInput {
          id: editPath
          Layout.fillWidth: true
          maximumLength: 4096
          enabled: !root.editBulk || changePath.checked
          placeholderText: root.editBulk && !changePath.checked ? "Unchanged" : ""
        }
        PlainText {
          text: "Catalog location only; this does not move files or change the scan source."
          color: Color.muted
          font.pixelSize: Style.font.bodySmall
          Layout.fillWidth: true
        }
        FieldToggle {
          id: changeNumber
          visible: root.editBulk
          text: "Change CD number / total"
          enabled: root.editingAudio
        }
        PlainText {
          visible: root.editBulk && !root.editingAudio
          text: "CD numbering requires an audio-CD-only selection."
          color: Color.muted
          font.pixelSize: Style.font.bodySmall
          Layout.fillWidth: true
        }
        RowLayout {
          visible: root.editingAudio
          enabled: !root.editBulk || changeNumber.checked
          Layout.fillWidth: true
          PlainText { text: "CD"; color: Color.muted }
          EditInput { id: editNumber; Layout.fillWidth: true; maximumLength: 4; placeholderText: "Number" }
          PlainText { text: "of"; color: Color.muted }
          EditInput { id: editTotal; Layout.fillWidth: true; maximumLength: 4; placeholderText: "Total" }
        }
        PlainText { text: "Tags"; color: Color.muted }
        ComboBox {
          id: tagOperation
          visible: root.editBulk
          Layout.fillWidth: true
          model: ["Keep existing tags", "Add tags", "Remove tags", "Replace all tags"]
        }
        TermFilter {
          Layout.fillWidth: true
          visible: !root.editBulk || tagOperation.currentIndex !== 0
          placeholderText: "Add a tag, then press Enter…"
          additionalPlaceholderText: "Add another tag…"
          terms: root.editingTags
          draft: root.editingTagDraft
          onTermsEdited: function(value) { root.editingTags = value }
          onDraftEdited: function(value) { root.editingTagDraft = value }
        }
        PlainText {
          visible: root.editBulk && tagOperation.currentIndex === 3
          text: "Replace overwrites every selected disc's tags. An empty list clears all tags."
          color: Color.accent
          Layout.fillWidth: true
        }
        PlainText {
          text: "Tags also match the library and file-search filters. Edits survive rescanning."
          color: Color.muted
          font.pixelSize: Style.font.bodySmall
          Layout.fillWidth: true
        }
        PlainText {
          visible: !!root.editError
          text: root.editError
          color: Color.urgent
          Layout.fillWidth: true
        }
        RowLayout {
          Layout.fillWidth: true
          Item { Layout.fillWidth: true }
          ActionButton { text: "Cancel"; onClicked: editDialog.close() }
          ActionButton {
            text: root.editSaving ? "Saving…" : root.editBulk ? "Apply to selected" : "Save"
            discAccent: true
            onClicked: root.saveEdit()
          }
        }
      }
    }
  }

  Item {
    anchors.fill: parent
    visible: root.deleteConfirmationOpen
    z: 100

    Rectangle {
      anchors.fill: parent
      color: "#80000000"
      MouseArea {
        anchors.fill: parent
      }
    }

    Rectangle {
      anchors.centerIn: parent
      width: Math.min(parent.width - Style.space(32), Style.space(460))
      height: confirmationContent.implicitHeight + Style.space(32)
      radius: Style.cornerRadius
      color: Color.popups.background
      border.color: Color.popups.border
      border.width: 1

      ColumnLayout {
        id: confirmationContent
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Style.space(16)
        spacing: Style.space(12)

        PlainText {
          text: "Remove disk from library?"
          font.bold: true
        }
        PlainText {
          Layout.fillWidth: true
          text: root.deleteConfirmationText
        }
        RowLayout {
          Layout.fillWidth: true
          Item { Layout.fillWidth: true }
          ActionButton {
            text: "Cancel"
            onClicked: root.deleteConfirmationOpen = false
          }
          ActionButton {
            text: "Delete"
            discAccent: true
            onClicked: {
              root.deleteConfirmationOpen = false
              if (root.controller) root.controller.deleteDisks(root.deleteDiskIds)
            }
          }
        }
      }
    }
  }
}
