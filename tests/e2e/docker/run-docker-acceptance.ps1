# Alberto Isolated Docker E2E Acceptance Test Runner (PowerShell)
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = (Resolve-Path "$scriptDir\..\..\..").Path
$composeFile = "$scriptDir\docker-compose.test.yml"
$testUrl = "http://127.0.0.1:8001"

Write-Host "=== Alberto Docker Acceptance Suite ==="
Write-Host "Starting isolated test container on port 8001..."

try {
    docker compose -f $composeFile up -d --build

    Write-Host "Waiting for container health check at $testUrl/health..."
    $ready = $false
    for ($i = 1; $i -le 30; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "$testUrl/health" -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }

    if (-not $ready) {
        Write-Error "Error: Docker test container failed to become healthy within 60s."
        docker compose -f $composeFile logs
        exit 1
    }

    Write-Host "Container is healthy. Running Playwright Docker acceptance tests..."
    $env:DOCKER_TEST_URL = $testUrl
    cmd.exe /c "npx --prefix `"$rootDir\frontend`" playwright test --config=`"$rootDir\tests\e2e\playwright.config.ts`" --project=docker"
    Write-Host "Docker acceptance tests completed."
} finally {
    Write-Host "Tearing down acceptance container..."
    docker compose -f $composeFile down
    Write-Host "Container teardown complete."
}
