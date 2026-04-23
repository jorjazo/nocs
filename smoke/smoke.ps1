[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ArchivePath,
    [string]$Launcher = "bin\nocs.bat"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ArchivePath)) {
    Write-Error "archive not found: $ArchivePath"
    exit 2
}

$work = New-Item -ItemType Directory -Path (Join-Path $env:TEMP ([System.Guid]::NewGuid().ToString()))
$dataDir = New-Item -ItemType Directory -Path (Join-Path $env:TEMP ([System.Guid]::NewGuid().ToString()))
$logPath = Join-Path $work "out.log"
$proc = $null

try {
    Expand-Archive -Path $ArchivePath -DestinationPath $work -Force

    $top = Get-ChildItem -Path $work -Directory | Select-Object -First 1
    if (-not $top) { throw "no top-level directory inside archive" }

    $launcherPath = Join-Path $top.FullName $Launcher
    if (-not (Test-Path $launcherPath)) { throw "launcher missing: $launcherPath" }

    $env:NOCS_DATA_DIR = $dataDir.FullName

    $proc = Start-Process -FilePath $launcherPath `
        -RedirectStandardOutput $logPath `
        -RedirectStandardError $logPath `
        -PassThru -WindowStyle Hidden

    for ($i = 1; $i -le 60; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:8080/" -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) {
                Write-Host "NOCS is up after ${i}s (archive=$ArchivePath launcher=$Launcher)"
                exit 0
            }
        } catch {
            # not ready yet
        }
        if ($proc.HasExited) {
            Write-Error "launcher exited before serving HTTP; logs:"
            Get-Content $logPath | Write-Host
            exit 1
        }
        Start-Sleep -Seconds 1
    }

    Write-Error "NOCS did not start within 60s; logs:"
    Get-Content $logPath | Write-Host
    exit 1
}
finally {
    if ($null -ne $proc -and -not $proc.HasExited) {
        try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
    }
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $work
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $dataDir
}
