$ErrorActionPreference = "Stop"

$repoRoot = "C:\Users\SJK\Documents\project-radar"
$backendRoot = Join-Path $repoRoot "backend"
$healthUrl = "http://127.0.0.1:8787/health"
$deploymentsUrl = "http://127.0.0.1:8787/?view=deployments&filter=active&sync=deployments"

function Test-RadarHealth {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (-not (Test-RadarHealth)) {
    $startScript = Join-Path $repoRoot "scripts\start_dashboard.ps1"
    Start-Process powershell.exe -ArgumentList @(
        "-NoLogo",
        "-ExecutionPolicy", "Bypass",
        "-File", $startScript
    ) -WorkingDirectory $backendRoot -WindowStyle Normal

    $started = $false
    foreach ($attempt in 1..20) {
        Start-Sleep -Milliseconds 750
        if (Test-RadarHealth) {
            $started = $true
            break
        }
    }

    if (-not $started) {
        throw "Radar did not become healthy at $healthUrl"
    }
}

Start-Process $deploymentsUrl
