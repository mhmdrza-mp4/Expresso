# Expresso launcher:
#  - VPN connected    -> disconnect and exit
#  - VPN disconnected -> open ExpressVPN, wait until its CLI responds, run expresso.py,
#                        then close the script window $CloseAfter seconds after the VPN is connected
$ErrorActionPreference = 'Stop'

$Script        = Join-Path $PSScriptRoot 'expresso.py'
$Timeout       = 60   # seconds to wait for ExpressVPN to become ready
$FallbackAfter = 15   # seconds before trying the Start-menu launch if the direct launch did not help
$CloseAfter    = 5    # seconds to keep the script open after the VPN is connected

$CtlCandidates = @(
    'C:\Program Files\ExpressVPN\expressvpnctl.exe',
    'C:\Program Files (x86)\ExpressVPN\expressvpnctl.exe'
)
$AppCandidates = @(
    'C:\Program Files\ExpressVPN\expressvpn-client.exe',
    'C:\Program Files (x86)\ExpressVPN\expressvpn-client.exe'
)
$Ctl = $CtlCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Ctl) {
    $cmd = Get-Command expressvpnctl -ErrorAction SilentlyContinue
    if ($cmd) { $Ctl = $cmd.Source }
}
if (-not $Ctl) { Write-Host 'expressvpnctl not found.' -ForegroundColor Red; Read-Host 'Enter to exit'; exit 1 }

# Returns the connection state string, or $null when the CLI is not responding.
function Get-VpnState {
    try {
        $out = (& $Ctl get connectionstate 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $out) { return $out }
    } catch { }
    return $null
}

# Slow path: find the app through the Start menu.
function Start-AppViaStartMenu {
    $app = Get-StartApps | Where-Object { $_.Name -like '*ExpressVPN*' } | Select-Object -First 1
    if (-not $app) { Write-Host 'ExpressVPN app not found.' -ForegroundColor Red; Read-Host 'Enter to exit'; exit 1 }
    Start-Process "shell:AppsFolder\$($app.AppID)"
}

$state = Get-VpnState

if ($state -eq 'Connected') {
    Write-Host 'Disconnecting...'
    try { & $Ctl disconnect 2>&1 | Out-Null } catch { }
    exit 0
}

if (-not $state) {
    Write-Host 'Starting ExpressVPN...'
    $appExe = $AppCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    $usedFallback = $false
    if ($appExe) {
        Start-Process $appExe
    } else {
        Start-AppViaStartMenu
        $usedFallback = $true
    }

    $started  = Get-Date
    $deadline = $started.AddSeconds($Timeout)
    $fallbackAt = $started.AddSeconds($FallbackAfter)
    while (-not (Get-VpnState)) {
        $now = Get-Date
        if ($now -gt $deadline) {
            Write-Host "ExpressVPN not ready after $Timeout s." -ForegroundColor Red
            Read-Host 'Enter to exit'; exit 1
        }
        if (-not $usedFallback -and $now -gt $fallbackAt) {
            Start-AppViaStartMenu
            $usedFallback = $true
        }
        Start-Sleep -Milliseconds 250
    }
}

$py   = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
$argv = @("`"$Script`"") + $args
$proc = Start-Process -FilePath $py -ArgumentList $argv -NoNewWindow -PassThru
$null = $proc.Handle   # keep the handle so ExitCode stays readable

$since = $null
while (-not $proc.HasExited) {
    Start-Sleep -Milliseconds 250
    if ((Get-VpnState) -eq 'Connected') {
        if (-not $since) { $since = Get-Date }
        if (((Get-Date) - $since).TotalSeconds -ge $CloseAfter) {
            # Kill python and its children; the VPN stays connected.
            taskkill /PID $proc.Id /T /F 2>&1 | Out-Null
            exit 0
        }
    } else {
        $since = $null
    }
}
exit $proc.ExitCode
