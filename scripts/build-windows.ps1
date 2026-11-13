$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
Write-Host '1/4 Installing frontend and Electron dependencies...'
npm --prefix frontend install
if ($LASTEXITCODE -ne 0) { throw 'Frontend install failed' }
if (!(Test-Path 'node_modules')) { npm install; if ($LASTEXITCODE -ne 0) { throw 'Electron install failed' } }
Write-Host '2/4 Building React frontend...'
npm run build:frontend
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
Write-Host '3/4 Packaging Python backend (one-folder)...'
if (!(Test-Path 'backend/.venv/Scripts/python.exe')) { py -m venv backend/.venv }
$python = Join-Path $root 'backend/.venv/Scripts/python.exe'
& $python -m pip install -r backend/requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Python install failed' }
& $python -m PyInstaller --noconfirm --clean --onedir --name bci-backend `
  --distpath "$root\backend-dist" --workpath "$root\build\python" --specpath "$root\build\python" `
  --paths "$root\backend" `
  --add-data "$root\backend\datasets;datasets" `
  --add-data "$root\frontend\dist;frontend-dist" `
  "$root\backend\main.py"
if ($LASTEXITCODE -ne 0) { throw 'Python packaging failed' }
Write-Host '4/4 Building Windows installer...'
npm run package:win
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
Write-Host 'Done. See release/ for the installer.'
