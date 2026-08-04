<#
.SYNOPSIS
    Builds the React frontend into backend/static so FastAPI can serve it, then
    optionally syncs and deploys to Databricks Apps.

.DESCRIPTION
    Databricks Apps runs one process on one port, so the Vite bundle has to be
    served by the FastAPI app rather than deployed separately.

    The output goes to backend/static (NOT frontend/dist) on purpose:
    `databricks sync` honours .gitignore, and .gitignore excludes dist/ — a
    bundle built there would be silently left out of the deployment.

.PARAMETER ApiToken
    Value of RULE_AGENT_API_TOKEN. Baked into the browser bundle, which is
    acceptable only because Databricks Apps puts SSO in front of the app.

.PARAMETER AppName
    Databricks app name. Defaults to rule-agent.

.PARAMETER WorkspacePath
    Workspace folder to sync into, e.g. /Workspace/Users/you@org.com/rule-agent.
    Required with -Deploy.

.PARAMETER Deploy
    Also run `databricks sync` and `databricks apps deploy`.

.EXAMPLE
    ./build-databricks.ps1 -ApiToken $env:RULE_AGENT_API_TOKEN

.EXAMPLE
    ./build-databricks.ps1 -ApiToken $tok -Deploy `
        -WorkspacePath /Workspace/Users/you@org.com/rule-agent
#>
param(
    [Parameter(Mandatory = $true)][string]$ApiToken,
    [string]$AppName = 'rule-agent',
    [string]$WorkspacePath,
    [switch]$Deploy
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$staticDir = Join-Path $root 'backend/static'

if ($Deploy -and -not $WorkspacePath) {
    throw '-Deploy requires -WorkspacePath.'
}

Write-Host '==> Installing frontend dependencies' -ForegroundColor Cyan
Push-Location (Join-Path $root 'frontend')
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE" }

    Write-Host '==> Building frontend into backend/static' -ForegroundColor Cyan
    # Empty API base = same-origin. api.js prepends /api, which main.py serves.
    $env:VITE_API_BASE_URL = ''
    $env:VITE_API_TOKEN = $ApiToken
    npx vite build --outDir $staticDir --emptyOutDir
    if ($LASTEXITCODE -ne 0) { throw "vite build failed with exit code $LASTEXITCODE" }
}
finally {
    Remove-Item Env:VITE_API_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
    Pop-Location
}

if (-not (Test-Path (Join-Path $staticDir 'index.html'))) {
    throw "Build produced no index.html in $staticDir"
}
Write-Host "==> Built. Static root: $staticDir" -ForegroundColor Green

if (-not $Deploy) {
    Write-Host 'Skipping deploy (pass -Deploy to sync and deploy).' -ForegroundColor Yellow
    return
}

Write-Host "==> Syncing backend/ to $WorkspacePath" -ForegroundColor Cyan
Push-Location (Join-Path $root 'backend')
try {
    databricks sync . $WorkspacePath
    if ($LASTEXITCODE -ne 0) { throw "databricks sync failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}

Write-Host "==> Deploying app '$AppName'" -ForegroundColor Cyan
databricks apps deploy $AppName --source-code-path $WorkspacePath
if ($LASTEXITCODE -ne 0) { throw "databricks apps deploy failed with exit code $LASTEXITCODE" }

Write-Host '==> Deployed. Check the Logs tab, then hit /api/ready.' -ForegroundColor Green
