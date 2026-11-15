"""Download verified public releases and replace the closed Windows executable."""
import base64
import hashlib
import os
from pathlib import Path
import re
import subprocess
import requests

VERSION = '2026.11.15.4'
REPOSITORY = 'hikorigy-ship-it/tul4n-launcher'


def version_key(value):
    return tuple(int(part) for part in re.findall(r'\d+', value))


def latest():
    response = requests.get(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',
                            headers={'User-Agent': 'TUL4N-Updater'}, timeout=(10, 30))
    response.raise_for_status()
    release = response.json()
    if version_key(release['tag_name']) <= version_key(VERSION):
        return None
    asset = next(a for a in release['assets'] if a['name'] == 'TUL4N.exe')
    digest = asset.get('digest', '')
    if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
        raise ValueError('В выпуске нет контрольной суммы SHA-256')
    expected_prefix = f'https://github.com/{REPOSITORY}/releases/download/'
    if not asset['browser_download_url'].startswith(expected_prefix):
        raise ValueError('Неизвестный источник обновления')
    return release['tag_name'], asset


def download(asset, target, progress):
    stage = Path(target).parent / '.updates' / 'TUL4N.new.exe'
    stage.parent.mkdir(exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    try:
        with requests.get(asset['browser_download_url'], stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            with stage.open('wb') as output:
                for chunk in response.iter_content(256 * 1024):
                    if chunk:
                        output.write(chunk)
                        digest.update(chunk)
                        total += len(chunk)
                        progress(f'Скачивание обновления: {total // 1024 // 1024} МБ')
        if total != asset['size'] or digest.hexdigest() != asset['digest'].split(':', 1)[1].lower():
            raise ValueError('Файл обновления повреждён. Повторите скачивание.')
        return stage
    except Exception:
        stage.unlink(missing_ok=True)
        raise


def restart(stage, target):
    def literal(path):
        return "'" + str(Path(path).resolve()).replace("'", "''") + "'"
    # A separate Windows process waits for this launcher to release its files.
    script = f"""
$ErrorActionPreference='Stop'
$target={literal(target)}
$stage={literal(stage)}
$backup=$target+'.previous'
try {{
    Wait-Process -Id {os.getpid()} -Timeout 120 -ErrorAction SilentlyContinue
    $installed=$false
    for($i=0;$i -lt 60;$i++) {{
        try {{
            [System.IO.File]::Replace($stage,$target,$backup,$true)
            $installed=$true
            break
        }} catch {{ Start-Sleep -Milliseconds 500 }}
    }}
    if(-not $installed) {{ throw 'Не удалось заменить файл лаунчера' }}
}} catch {{
    $_ | Out-File -LiteralPath ($target+'.update-error.log') -Encoding utf8
}}
Start-Process -FilePath $target -WorkingDirectory (Split-Path -LiteralPath $target)
"""
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                     creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)

