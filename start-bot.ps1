<#
.SYNOPSIS
    Starts the QQRecorder bot using uv and ncatbot.

.DESCRIPTION
    This script changes to the correct directory and starts the QQRecorder bot.
    It includes error checking and follows PowerShell best practices.
#>

# Error handling preference
$ErrorActionPreference = "Stop"

# Get the directory where this script is located
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectPath = $scriptDir

# Check if the directory exists
if (-not (Test-Path -LiteralPath $projectPath -PathType Container)) {
    Write-Error "Project directory not found: $projectPath"
    exit 1
}

# Change to the project directory
try {
    Set-Location -LiteralPath $projectPath -ErrorAction Stop
}
catch {
    Write-Error "Failed to change directory to: $projectPath`nError: $_"
    exit 1
}

# Check if uv is available
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv command not found. Please install uv first."
    exit 1
}

# Start the bot
try {
    Write-Host "Starting QQRecorder bot..." -ForegroundColor Green
    uv run ncatbot run
}
catch {
    Write-Error "Failed to start the bot`nError: $_"
    exit 1
}