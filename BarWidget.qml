import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "kel.omashelf"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  readonly property string pluginDir: {
    var url = String(Qt.resolvedUrl("./"))
    if (url.indexOf("file://") !== 0) return ""
    try { return decodeURIComponent(url.substring(7)).replace(/\/$/, "") } catch (e) { return "" }
  }
  readonly property string dataDir: Quickshell.env("OMASHELF_DATA_DIR")
    || ((Quickshell.env("XDG_DATA_HOME") || (Quickshell.env("HOME") + "/.local/share"))
      + "/omashelf")
  readonly property string statusPath: dataDir + "/status.json"
  property bool scanning: false
  property real spinAngle: 0

  function injectPanel() {
    var panel = panelLoader.item
    if (!panel) return
    panel.bar = root.bar
    panel.settings = root.settings
    panel.anchorItem = button
    panel.hostWidget = root
  }

  function activateFromBar() {
    if (panelLoader.item && panelLoader.item.activateFromBar)
      panelLoader.item.activateFromBar()
  }

  function refresh() {
    if (panelLoader.item && panelLoader.item.refresh)
      panelLoader.item.refresh()
  }

  readonly property bool opened: panelLoader.item
    ? panelLoader.item.opened === true || panelLoader.item.applicationWindowVisible === true
    : false
  readonly property bool popoutSwitchClosing: panelLoader.item
    ? panelLoader.item.popoutSwitchClosing === true : false

  function open() {
    if (panelLoader.item && panelLoader.item.openFromHotkey)
      panelLoader.item.openFromHotkey()
  }

  function close() {
    if (panelLoader.item && panelLoader.item.close)
      panelLoader.item.close()
    if (panelLoader.item && panelLoader.item.closeApplicationWindow)
      panelLoader.item.closeApplicationWindow()
  }

  function closeForPopoutSwitch() {
    if (panelLoader.item && panelLoader.item.closeForPopoutSwitch)
      panelLoader.item.closeForPopoutSwitch()
  }

  function updateScanStatus(raw) {
    try {
      var value = JSON.parse(raw || "{}")
      scanning = value.scanning === true
    } catch (error) {
      scanning = false
    }
  }

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  FileView {
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.updateScanStatus(text())
    onLoadFailed: root.scanning = false
  }

  NumberAnimation {
    target: root
    property: "spinAngle"
    from: 0
    to: 360
    duration: Style.duration(1000)
    loops: Animation.Infinite
    running: root.scanning && !Style.reduceMotion
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    iconComponent: Component {
      Item {
        id: disc
        width: 32
        height: 32
        readonly property color discColor: root.scanning ? Color.accent : button.foreground
        rotation: root.scanning ? root.spinAngle : 0

        Rectangle {
          anchors.fill: parent
          anchors.margins: 2
          radius: width / 2
          color: "transparent"
          border.color: disc.discColor
          border.width: 2
        }
        Rectangle {
          anchors.centerIn: parent
          width: 18
          height: 18
          radius: width / 2
          color: "transparent"
          border.color: disc.discColor
          border.width: 1
        }
        Rectangle {
          anchors.centerIn: parent
          width: 6
          height: 6
          radius: width / 2
          color: "transparent"
          border.color: disc.discColor
          border.width: 1
        }
        Rectangle {
          anchors.horizontalCenter: parent.horizontalCenter
          y: 4
          width: 1
          height: 6
          color: disc.discColor
        }
      }
    }
    tooltipText: "OmaShelf"

    onPressed: function(mouseButton) {
      if (mouseButton === Qt.LeftButton) root.activateFromBar()
      else if (mouseButton === Qt.MiddleButton) root.refresh()
    }
  }
}
