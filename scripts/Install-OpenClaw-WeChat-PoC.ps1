[CmdletBinding()]
param(
    [switch]$InstallOpenClaw,
    [switch]$InstallWeChatPlugin,
    [switch]$Status
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Stop-PoC {
    param([string]$Message)

    Write-Error $Message
    exit 1
}

function Get-RequiredCommand {
    param(
        [string]$Name,
        [string]$Guidance
    )

    try {
        $command = Get-Command -Name $Name -ErrorAction Stop
    }
    catch {
        Stop-PoC "Missing required command '$Name'. $Guidance"
    }

    Write-Host "Found ${Name}: $($command.Source)"
}

function Test-NodeAndNpm {
    Get-RequiredCommand -Name 'node' -Guidance 'Install Node.js manually from https://nodejs.org/en/download, reopen PowerShell, then run this script again.'
    Get-RequiredCommand -Name 'npm' -Guidance 'Reinstall Node.js manually from https://nodejs.org/en/download, reopen PowerShell, then run this script again.'
}

function Test-OpenClaw {
    Get-RequiredCommand -Name 'openclaw' -Guidance 'Run this script with -InstallOpenClaw, then reopen PowerShell.'
}

function Confirm-Install {
    param([string]$Description)

    $answer = Read-Host "$Description Type INSTALL to continue"
    if ($answer -cne 'INSTALL') {
        Stop-PoC 'Installation cancelled by user.'
    }
}

if (-not [Environment]::UserInteractive) {
    Stop-PoC 'This PoC script is interactive only. Run it from an interactive Windows PowerShell session.'
}

if ($InstallOpenClaw -and $InstallWeChatPlugin) {
    Stop-PoC 'Run -InstallOpenClaw and -InstallWeChatPlugin in separate PowerShell sessions.'
}

if ($Status -and ($InstallOpenClaw -or $InstallWeChatPlugin)) {
    Stop-PoC 'Use -Status by itself. Installation and status checks are separate steps.'
}

if ($InstallOpenClaw) {
    Test-NodeAndNpm
    Confirm-Install 'This runs: npm install -g openclaw@latest --allow-scripts=openclaw.'
    & npm install -g openclaw@latest --allow-scripts=openclaw
    if ($LASTEXITCODE -ne 0) {
        Stop-PoC "OpenClaw installation failed with exit code $LASTEXITCODE."
    }
    Write-Host 'OpenClaw installation completed. Close and reopen PowerShell, then run this script with -Status.'
}

if ($InstallWeChatPlugin) {
    Test-NodeAndNpm
    Get-RequiredCommand -Name 'npx' -Guidance 'Reinstall Node.js manually from https://nodejs.org/en/download, reopen PowerShell, then run this script again.'
    Test-OpenClaw
    Confirm-Install 'This runs: npx -y @tencent-weixin/openclaw-weixin-cli install.'
    & npx -y @tencent-weixin/openclaw-weixin-cli install
    if ($LASTEXITCODE -ne 0) {
        Stop-PoC "WeChat plugin installation failed with exit code $LASTEXITCODE."
    }
}

if ($Status -or (-not $InstallOpenClaw -and -not $InstallWeChatPlugin)) {
    Test-NodeAndNpm
    Test-OpenClaw
}

Write-Host ''
Write-Host 'Preflight complete. This script does not run onboarding, QR login, pairing, status probes, or messaging.'
Write-Host 'Manual next commands:'
Write-Host '  openclaw onboard'
Write-Host '  npx -y @tencent-weixin/openclaw-weixin-cli install'
Write-Host '  openclaw channels login --channel openclaw-weixin'
Write-Host '  openclaw plugins list'
Write-Host '  openclaw channels status --probe'

exit 0
