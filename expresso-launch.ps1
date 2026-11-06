# Expresso launcher:
#  - VPN connected    -> disconnect and exit
#  - VPN disconnected -> open ExpressVPN, wait until its CLI responds, run expresso.py,
#                        then close the script window $CloseAfter seconds after the VPN is connected
$ErrorActionPreference = 'Stop'

$Script     = Join-Path $PSScriptRoot 'expresso.py'
$Timeout    = 60   # seconds to wait for ExpressVPN to become ready
$CloseAfter = 5    # seconds to keep the script open after the VPN is connected

$CtlCandidates = @(
    'C:\Program Files\ExpressVPN\expressvpnctl.exe',
    'C:\Program Files (x86)\ExpressVPN\expressvpnctl.exe'
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

$state = Get-VpnState

if ($state -eq 'Connected') {
    Write-Host 'Disconnecting...'
    try { & $Ctl disconnect 2>&1 | Out-Null } catch { }
    Start-Sleep -Seconds 2
    exit 0
}

if (-not $state) {
    $app = Get-StartApps | Where-Object { $_.Name -like '*ExpressVPN*' } | Select-Object -First 1
    if (-not $app) { Write-Host 'ExpressVPN app not found in Start menu.' -ForegroundColor Red; Read-Host 'Enter to exit'; exit 1 }
    Write-Host 'Starting ExpressVPN...'
    Start-Process "shell:AppsFolder\$($app.AppID)"

    $deadline = (Get-Date).AddSeconds($Timeout)
    while (-not (Get-VpnState)) {
        if ((Get-Date) -gt $deadline) {
            Write-Host "ExpressVPN not ready after $Timeout s." -ForegroundColor Red
            Read-Host 'Enter to exit'; exit 1
        }
        Start-Sleep -Seconds 1
    }
}

$py   = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
$argv = @("`"$Script`"") + $args
$proc = Start-Process -FilePath $py -ArgumentList $argv -NoNewWindow -PassThru
$null = $proc.Handle   # keep the handle so ExitCode stays readable

$since = $null
while (-not $proc.HasExited) {
    Start-Sleep -Milliseconds 500
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
