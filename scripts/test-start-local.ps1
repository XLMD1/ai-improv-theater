$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $repoRoot 'scripts/start-local.ps1'
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$fixture = Join-Path $tempRoot ("ai-improv-start-test-" + [guid]::NewGuid().ToString('N'))

function Invoke-Launcher([string]$shell, [string]$path) {
    $previousPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 turns expected child stderr into error records.
        $ErrorActionPreference = 'Continue'
        if ($shell -eq 'powershell.exe') {
            $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $path 2>&1 | Out-String
        }
        else {
            $output = & pwsh -NoProfile -File $path 2>&1 | Out-String
        }
        return @{ Output = $output; ExitCode = $LASTEXITCODE }
    }
    finally { $ErrorActionPreference = $previousPreference }
}

try {
    New-Item -ItemType Directory -Path (Join-Path $fixture 'scripts') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $fixture 'backend') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $fixture 'frontend') -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination (Join-Path $fixture 'scripts/start-local.ps1')

    $legacyResult = Invoke-Launcher 'powershell.exe' (Join-Path $fixture 'scripts/start-local.ps1')
    if ($legacyResult.ExitCode -eq 0 -or $legacyResult.Output -notmatch 'backend/.venv' -or $legacyResult.Output -match 'ParserError|Unexpected token') {
        throw "Windows PowerShell 5.1 could not parse the launcher: $($legacyResult.Output)"
    }

    $result = Invoke-Launcher 'pwsh' (Join-Path $fixture 'scripts/start-local.ps1')
    if ($result.ExitCode -eq 0 -or $result.Output -notmatch '\.venv') {
        throw "Missing Python environment was not reported: $($result.Output)"
    }

    $rootPythonDir = Join-Path $fixture '.venv/Scripts'
    New-Item -ItemType Directory -Path $rootPythonDir -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $rootPythonDir 'python.exe') | Out-Null
    $legacyResult = Invoke-Launcher 'powershell.exe' (Join-Path $fixture 'scripts/start-local.ps1')
    if ($legacyResult.ExitCode -eq 0 -or $legacyResult.Output -notmatch 'npm ci') {
        throw "Repository root virtual environment was not accepted: $($legacyResult.Output)"
    }

    $pythonDir = Join-Path $fixture 'backend/.venv/Scripts'
    New-Item -ItemType Directory -Path $pythonDir -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $pythonDir 'python.exe') | Out-Null
    $result = Invoke-Launcher 'pwsh' (Join-Path $fixture 'scripts/start-local.ps1')
    if ($result.ExitCode -eq 0 -or $result.Output -notmatch 'npm ci') {
        throw "Missing frontend dependencies were not reported: $($result.Output)"
    }

    $nextDir = Join-Path $fixture 'frontend/node_modules/.bin'
    New-Item -ItemType Directory -Path $nextDir -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $nextDir 'next.cmd') | Out-Null
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 8000)
    try {
        $listener.Start()
    }
    catch [System.Net.Sockets.SocketException] {
        # Another process already owns the port; that still exercises the guard.
    }
    try {
        $result = Invoke-Launcher 'pwsh' (Join-Path $fixture 'scripts/start-local.ps1')
        if ($result.ExitCode -eq 0 -or $result.Output -notmatch '端口 8000 已被占用') {
            throw "Occupied API port was not reported: $($result.Output)"
        }
    }
    finally { $listener.Stop() }

    Write-Output 'Launcher preflight tests passed.'
}
finally {
    $resolved = [System.IO.Path]::GetFullPath($fixture)
    if (-not $resolved.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not ([System.IO.Path]::GetFileName($resolved) -like 'ai-improv-start-test-*')) {
        throw "Unsafe fixture cleanup path: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
}
