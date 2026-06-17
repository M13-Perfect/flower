import { app, BrowserWindow, dialog, ipcMain } from "electron";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

ipcMain.handle("flower:choose-directory", async () => {
  const result = await dialog.showOpenDialog({
    properties: ["openDirectory", "createDirectory"],
  });

  return result.canceled ? null : (result.filePaths[0] ?? null);
});

function createMainWindow() {
  const window = new BrowserWindow({
    width: 1280,
    height: 900,
    minWidth: 960,
    minHeight: 640,
    title: "Flower Editor",
    webPreferences: {
      preload: join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  const devServerUrl = process.env.VITE_DEV_SERVER_URL ?? "http://127.0.0.1:5173";
  if (process.env.NODE_ENV === "development") {
    void window.loadURL(devServerUrl);
    return;
  }

  void window.loadFile(join(__dirname, "../renderer/index.html"));
}

app.whenReady().then(() => {
  createMainWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
