const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('espImageServerDesktop', {
  firmwareState: () => ipcRenderer.invoke('firmware-state'),
  firmwarePorts: () => ipcRenderer.invoke('firmware-ports'),
  selectFirmwarePort: request => ipcRenderer.invoke('firmware-select-port', request),
  identifyFirmware: request => ipcRenderer.invoke('firmware-identify', request),
  startWifiSetup: request => ipcRenderer.invoke('firmware-wifi-start', request),
  cancelWifiSetup: () => ipcRenderer.invoke('firmware-wifi-cancel'),
  chooseFirmwarePackage: () => ipcRenderer.invoke('firmware-package'),
  installFirmware: request => ipcRenderer.invoke('firmware-install', request),
  chooseImageLibrary: () => ipcRenderer.invoke('choose-image-library'),
  revealImageLibrary: libraryPath => ipcRenderer.invoke('reveal-image-library', libraryPath),
  getStartupState: () => ipcRenderer.invoke('startup-state'),
  onServerStatus: callback => ipcRenderer.on('server-status', (_, update) => callback(update)),
  onServerLog: callback => ipcRenderer.on('server-log', (_, lines) => callback(lines))
})
