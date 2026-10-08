$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendDir = Join-Path $repoRoot 'backend'
$frontendDir = Join-Path $repoRoot 'frontend'
$python = Join-Path $backendDir '.venv/Scripts/python.exe'
$next = Join-Path $frontendDir 'node_modules/.bin/next.cmd'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw '缺少 backend/.venv。请在 backend 目录运行 python -m venv .venv，然后运行 .\.venv\Scripts\python.exe -m pip install -e .'
}
if (-not (Test-Path -LiteralPath $next -PathType Leaf)) {
    throw '缺少前端依赖。请在 frontend 目录运行 npm ci。'
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw '未找到 npm.cmd。请安装 Node.js 和 npm。'
}
function Test-LocalPortInUse([int]$port) {
    foreach ($address in @([System.Net.IPAddress]::Loopback, [System.Net.IPAddress]::IPv6Loopback)) {
        $client = [System.Net.Sockets.TcpClient]::new($address.AddressFamily)
        try {
            $client.Connect($address, $port)
            return $true
        }
        catch [System.Net.Sockets.SocketException] { }
        finally { $client.Dispose() }
    }
    return $false
}
foreach ($port in 8000, 3000) {
    if (Test-LocalPortInUse $port) {
        throw "端口 $port 已被占用，请先停止占用它的服务。"
    }
}

Push-Location $backendDir
try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw '数据库迁移失败。请确认本地 PostgreSQL 已启动，且 DATABASE_URL / MIGRATION_DATABASE_URL 正确。' }
}
finally { Pop-Location }

$logBase = Join-Path ([System.IO.Path]::GetTempPath()) "ai-improv-api-$PID"
$backendProcess = $null
try {
    $backendProcess = Start-Process -FilePath $python -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000' -WorkingDirectory $backendDir -WindowStyle Hidden -RedirectStandardOutput "$logBase.out.log" -RedirectStandardError "$logBase.err.log" -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if ($backendProcess.HasExited) { break }
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 1
            if ($health.ok -eq $true) { $ready = $true; break }
        }
        catch { }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "后端未能启动；查看 $logBase.err.log" }

    Write-Host '后端已就绪：http://127.0.0.1:8000'
    Write-Host '前端启动后打开 http://localhost:3000；按 Ctrl+C 停止。'
    Push-Location $frontendDir
    try {
        & npm.cmd run dev -- --hostname localhost --port 3000
        if ($LASTEXITCODE -ne 0) { throw '前端进程异常退出。' }
    }
    finally { Pop-Location }
}
finally {
    if ($backendProcess -and -not $backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id -Force
        Write-Host '后端已停止。'
    }
}
