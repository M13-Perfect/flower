import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("flowerDesktop", {
  chooseDirectory: () => ipcRenderer.invoke("flower:choose-directory") as Promise<string | null>,
  platform: process.platform,
});
