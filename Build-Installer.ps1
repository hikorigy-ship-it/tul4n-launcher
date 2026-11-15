param([Parameter(Mandatory=$true)][string]$DownloadUrl)
$ErrorActionPreference='Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
$uri=[Uri]$DownloadUrl
if($uri.Scheme -ne 'https'){throw 'An HTTPS download URL is required'}
$hash=(Get-FileHash -LiteralPath 'TUL4N.exe' -Algorithm SHA256).Hash.ToLowerInvariant()
$escaped=$DownloadUrl.Replace('\','\\').Replace('"','\"')
$generated='static class ReleaseInfo { public const string DownloadUrl="'+$escaped+'"; public const string Sha256="'+$hash+'"; }'
$config=Join-Path $PSScriptRoot 'ReleaseInfo.generated.cs'
[IO.File]::WriteAllText($config,$generated,[Text.UTF8Encoding]::new($false))
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:winexe /platform:anycpu /codepage:65001 /optimize+ /win32icon:chunk.ico /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:Microsoft.CSharp.dll /out:TUL4N-Setup.exe Setup.cs ReleaseInfo.generated.cs
if($LASTEXITCODE -ne 0){throw 'Installer compilation failed'}
Write-Output 'TUL4N-Setup.exe is ready for the specified mirror.'
} finally { Pop-Location }

