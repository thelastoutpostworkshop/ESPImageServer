const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('espImageServerDesktop', {
  chooseImageLibrary: () => ipcRenderer.invoke('choose-image-library'),
  revealImageLibrary: libraryPath => ipcRenderer.invoke('reveal-image-library', libraryPath),
  getStartupState: () => ipcRenderer.invoke('startup-state'),
  onServerStatus: callback => ipcRenderer.on('server-status', (_, update) => callback(update)),
  onServerLog: callback => ipcRenderer.on('server-log', (_, lines) => callback(lines))
})
