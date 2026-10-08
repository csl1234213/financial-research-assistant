# Start the canonical V8.2.0 Docker Compose stack on Windows.
#
# .\scripts\start.ps1       # React/Nginx UI on :3000
# .\scripts\start.ps1 dev   # API/worker stack; run Vite separately on :5173
param(
    [ValidateSet("prod", "stack", "dev")]
    [string]$Mode = "prod"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path "$ScriptDir\..").Path
$EnvFile = "$ProjectRoot\.env"
$EnvExample = "$ProjectRoot\.env.example"
$ApiUrl = "http://localhost:8000"
$MaxRetries = 30
$RetryInterval = 2

if (-not (Test-Path $EnvFile)) {
    Copy-Item $EnvExample $EnvFile
    Write-Host "Created $EnvFile from .env.example."
    Write-Host "Before production, set AUTH_SECRET_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD, DEEPSEEK_API_KEY, and CORS_ORIGINS."
}

Set-Location $ProjectRoot

if ($Mode -eq "dev") {
    $UiUrl = "http://localhost:5173"
    Write-Host "Starting API, worker, and stateful services for Vite development..."
    docker compose up -d --build backend agent-worker
    Write-Host "Run 'cd frontend; npm run dev' in another terminal for the React dev server."
} else {
    $UiUrl = "http://localhost:3000"
    Write-Host "Starting the complete V8.2.0 Compose stack..."
    docker compose up -d --build
}

Write-Host "Waiting for API health..."
for ($i = 1; $i -le $MaxRetries; $i++) {
    try {
        $response = Invoke-RestMethod -Uri "$ApiUrl/api/v1/health" -Method Get -TimeoutSec 3
        if ($response.status -eq "ok") {
            Write-Host "Financial Research Copilot is ready."
            Write-Host "  API:     $ApiUrl"
            Write-Host "  Swagger: $ApiUrl/docs"
            Write-Host "  UI:      $UiUrl"
            Write-Host "  Logs:    .\scripts\logs.sh"
            exit 0
        }
    } catch {
        # The service may still be bootstrapping its database and embedding model.
    }
    Write-Host "  [$i/$MaxRetries] Waiting..." -NoNewline
    Write-Host "`r" -NoNewline
    Start-Sleep -Seconds $RetryInterval
}

Write-Error "API did not become healthy. Inspect logs with: docker compose logs backend"
