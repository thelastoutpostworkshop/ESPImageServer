const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('espImageServerDesktop', {
  firmwareState: () => ipcRenderer.invoke('firmware-state'),
  firmwareReleases: () => ipcRenderer.invoke('firmware-releases'),
  checkFirmwareReleases: () => ipcRenderer.invoke('firmware-releases-check'),
  firmwareDownloadState: () => ipcRenderer.invoke('firmware-download-state'),
  cancelFirmwareDownload: () => ipcRenderer.invoke('firmware-download-cancel'),
  selectReleaseFirmware: request => ipcRenderer.invoke('firmware-release-select', request),
  firmwareLibrary: () => ipcRenderer.invoke('firmware-library'),
  checkFirmwareLibrary: () => ipcRenderer.invoke('firmware-library-check'),
  chooseFirmwareLibrary: () => ipcRenderer.invoke('firmware-library-choose'),
  selectLibraryFirmware: request => ipcRenderer.invoke('firmware-library-select', request),
  firmwarePorts: () => ipcRenderer.invoke('firmware-ports'),
  selectFirmwarePort: request => ipcRenderer.invoke('firmware-select-port', request),
  identifyFirmware: request => ipcRenderer.invoke('firmware-identify', request),
  refreshFirmwareIdentity: request => ipcRenderer.invoke('firmware-refresh-identity', request),
  startWifiSetup: request => ipcRenderer.invoke('firmware-wifi-start', request),
  cancelWifiSetup: () => ipcRenderer.invoke('firmware-wifi-cancel'),
  chooseFirmwarePackage: () => ipcRenderer.invoke('firmware-package'),
  installFirmware: request => ipcRenderer.invoke('firmware-install', request),
  chooseImageLibrary: () => ipcRenderer.invoke('choose-image-library'),
  revealImageLibrary: libraryPath => ipcRenderer.invoke('reveal-image-library', libraryPath),
  generationSetupAction: action => ipcRenderer.invoke('generation-setup-action', action),
  getStartupState: () => ipcRenderer.invoke('startup-state'),
  onServerStatus: callback => ipcRenderer.on('server-status', (_, update) => callback(update)),
  onServerLog: callback => ipcRenderer.on('server-log', (_, lines) => callback(lines))
})
