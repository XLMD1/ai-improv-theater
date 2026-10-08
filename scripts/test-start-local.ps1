$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $repoRoot 'scripts/start-local.ps1'
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$fixture = Join-Path $tempRoot ("ai-improv-start-test-" + [guid]::NewGuid().ToString('N'))

try {
    New-Item -ItemType Directory -Path (Join-Path $fixture 'scripts') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $fixture 'backend') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $fixture 'frontend') -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination (Join-Path $fixture 'scripts/start-local.ps1')

    $output = & pwsh -NoProfile -File (Join-Path $fixture 'scripts/start-local.ps1') 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0 -or $output -notmatch '\.venv') {
        throw "Missing Python environment was not reported: $output"
    }

    $pythonDir = Join-Path $fixture 'backend/.venv/Scripts'
    New-Item -ItemType Directory -Path $pythonDir -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $pythonDir 'python.exe') | Out-Null
    $output = & pwsh -NoProfile -File (Join-Path $fixture 'scripts/start-local.ps1') 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0 -or $output -notmatch 'npm ci') {
        throw "Missing frontend dependencies were not reported: $output"
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
        $output = & pwsh -NoProfile -File (Join-Path $fixture 'scripts/start-local.ps1') 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0 -or $output -notmatch '端口 8000 已被占用') {
            throw "Occupied API port was not reported: $output"
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
