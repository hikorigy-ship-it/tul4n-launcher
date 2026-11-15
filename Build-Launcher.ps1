$ErrorActionPreference='Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    py -3.12 -m venv .build-env
    if($LASTEXITCODE -ne 0){throw 'Install Python 3.12 to build from source'}
    $python=Join-Path $PSScriptRoot '.build-env\Scripts\python.exe'
    & $python -m pip install -r requirements.txt pyinstaller pillow
    if($LASTEXITCODE -ne 0){throw 'Dependencies could not be installed'}
    & $python -m PyInstaller --noconfirm --onefile --windowed --name TUL4N --icon chunk.ico --add-data 'chunk.ico;.' --collect-all customtkinter --collect-all minecraft_launcher_lib launcher.py
    if($LASTEXITCODE -ne 0){throw 'Build failed'}
    Copy-Item -LiteralPath 'dist\TUL4N.exe' -Destination 'TUL4N.exe' -Force
    Write-Output 'TUL4N.exe is ready. Run Build-Installer.ps1 with the public HTTPS URL to build the installer.'
} finally { Pop-Location }

