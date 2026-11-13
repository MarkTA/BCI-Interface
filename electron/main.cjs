const { app, BrowserWindow, dialog, shell } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const http = require('node:http');

let backend = null;
let mainWindow = null;
const BASE_URL = 'http://127.0.0.1:8000';

function healthCheck() {
  return new Promise(resolve => {
    const req = http.get(BASE_URL + '/api/health', { timeout: 700 }, res => {
      let body = '';
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => {
        try { resolve(res.statusCode === 200 && JSON.parse(body).service === 'bci-interface'); }
        catch { resolve(false); }
      });
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

async function waitForBackend() {
  for (let i = 0; i < 100; i++) {
    if (backend && backend.exitCode !== null) break;
    if (await healthCheck()) return true;
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  return false;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1250, height: 860, minWidth: 850, minHeight: 600,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true }
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(BASE_URL + '/')) event.preventDefault();
  });
}

app.whenReady().then(async () => {
  if (await healthCheck()) {
    dialog.showErrorBox('Backend port already in use',
      'Port 8000 is already running a BCI backend. Close the existing process before launching the desktop app.');
    app.quit(); return;
  }
  const exe = app.isPackaged
    ? path.join(process.resourcesPath, 'backend', 'bci-backend', 'bci-backend.exe')
    : null;
  if (exe && !fs.existsSync(exe)) {
    dialog.showErrorBox('Missing backend', `Python backend not found: ${exe}`);
    app.quit(); return;
  }
  if (exe) {
    backend = spawn(exe, [], { windowsHide: true, stdio: 'ignore', env: { ...process.env, BCI_PORT: '8000' } });
  } else {
    dialog.showErrorBox('Development mode', 'Run the Python backend manually, then use npm run dev for the React app. The Electron executable is intended for packaged builds.');
    app.quit(); return;
  }
  if (!(await waitForBackend())) {
    dialog.showErrorBox('Backend failed to start', 'Check that the packaged backend and its dependencies are installed correctly.');
    app.quit(); return;
  }
  createWindow();
  await mainWindow.loadURL(BASE_URL);
});

app.on('before-quit', () => {
  if (backend && backend.exitCode === null) backend.kill();
});
app.on('window-all-closed', () => app.quit());
