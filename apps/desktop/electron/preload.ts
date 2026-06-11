import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("flowerDesktop", {
  platform: process.platform,
});
