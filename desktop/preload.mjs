import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('espImageServerDesktop', {
  chooseImageLibrary: () => ipcRenderer.invoke('choose-image-library'),
  revealImageLibrary: libraryPath => ipcRenderer.invoke('reveal-image-library', libraryPath),
  onServerStatus: callback => ipcRenderer.on('server-status', (_, update) => callback(update))
})
