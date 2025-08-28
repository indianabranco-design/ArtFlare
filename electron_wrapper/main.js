// Electron minimal wrapper
const {app, BrowserWindow} = require('electron');
const APP_URL = process.env.APP_URL || "https://SEU-URL-DA-APP.example.com";
function createWindow () {
  const win = new BrowserWindow({width: 1200, height: 800, webPreferences:{contextIsolation:true}});
  win.loadURL(APP_URL);
}
app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
