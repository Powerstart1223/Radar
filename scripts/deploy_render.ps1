$ErrorActionPreference = "Stop"
$repoRoot = "C:\Users\SJK\Documents\project-radar"
Set-Location $repoRoot

Write-Host "Project Radar deploy launcher" -ForegroundColor Cyan
Write-Host "Repo: $repoRoot"
Write-Host ""

$branch = (git branch --show-current).Trim()
$statusLines = @(git status --short)

Write-Host "Branch: $branch"
if ($statusLines.Count -gt 0) {
    Write-Host "Working tree changes:" -ForegroundColor Yellow
    $statusLines | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "Working tree is clean." -ForegroundColor Green
}
Write-Host ""

if ($branch -ne "main") {
    Write-Host "Deploy is configured from main. Switch to main before using this launcher." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

if ($statusLines.Count -gt 0) {
    $commitChoice = Read-Host "Commit current changes before deploy? (y/N)"
    if ($commitChoice -match '^(y|yes)$') {
        $message = Read-Host "Commit message"
        if ([string]::IsNullOrWhiteSpace($message)) {
            Write-Host "Commit message is required. Aborting." -ForegroundColor Red
            Read-Host "Press Enter to close"
            exit 1
        }
        git add -A
        git commit -m $message
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Commit failed. Aborting." -ForegroundColor Red
            Read-Host "Press Enter to close"
            exit 1
        }
    } else {
        Write-Host "Leaving working tree unchanged. Push will only succeed if the current branch state is already ready." -ForegroundColor Yellow
    }
    Write-Host ""
}

$confirm = Read-Host "Push main to origin and trigger Render auto-deploy? (y/N)"
if ($confirm -notmatch '^(y|yes)$') {
    Write-Host "Cancelled."
    Read-Host "Press Enter to close"
    exit 0
}

git push origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "Push failed." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Push succeeded. Render autoDeploy is enabled for project-radar." -ForegroundColor Green
Start-Process "https://dashboard.render.com/"
Read-Host "Press Enter to close"
