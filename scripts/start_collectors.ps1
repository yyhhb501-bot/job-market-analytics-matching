param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskProjectRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw '请先安装 Docker Desktop。' }
    $taskDockerReady = $false
    try {
        docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
        $taskDockerReady = $LASTEXITCODE -eq 0
    } catch { }
    if (-not $taskDockerReady) {
        Write-Host '正在启动 Docker…'
        docker desktop start --timeout 90
        if ($LASTEXITCODE -ne 0) { throw 'Docker 未能启动，请打开 Docker Desktop 查看提示后重试。' }
    }
    $taskOverride = Join-Path $env:TEMP 'jobseek-collector-ports.yml'
    @'
services:
  postgres:
    ports: !override
      - "127.0.0.1:15432:5432"
  redis:
    ports: !override
      - "127.0.0.1:16379:6379"
'@ | Set-Content -LiteralPath $taskOverride -Encoding utf8
    docker compose -p jobseek -f compose.dev.yml -f $taskOverride up -d --no-build --pull never postgres redis api web linkedin-importer
    if ($LASTEXITCODE -ne 0) { throw '采集服务启动失败。请检查 Docker 提示；已有数据不会被清空。' }
    $taskReady = $false
    for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
        try {
            $taskHealth = Invoke-RestMethod 'http://localhost:8010/health' -TimeoutSec 3
            $taskWeb = Invoke-WebRequest 'http://localhost:3000' -TimeoutSec 3
            if ($taskHealth.database -eq 'ok' -and $taskWeb.StatusCode -eq 200) { $taskReady = $true; break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $taskReady) { throw '服务启动后尚未就绪，请查看 docker logs jobseek-api-1 或 jobseek-web-1。' }
    Write-Host '采集服务已就绪。进入控制台，点击“一键开始采集”。' -ForegroundColor Green
    if (-not $NoBrowser) {
        $taskEdge = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
        if (Test-Path -LiteralPath $taskEdge) { Start-Process -FilePath $taskEdge -ArgumentList 'http://localhost:3000/admin/imports' }
        else { Start-Process 'http://localhost:3000/admin/imports' }
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
