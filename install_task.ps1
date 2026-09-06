<#
.SYNOPSIS
  Registers (or removes) the "ForexBot" Windows scheduled task that keeps the bot running.

.DESCRIPTION
  The task starts run_bot.cmd when you log on and restarts it every minute if it exits
  with a non-zero code (up to 999 times), with no execution time limit. It runs only while
  you are logged on because MetaTrader 5 is a desktop application and cannot be driven from
  a hidden service session.

  Two things this script cannot do for you: set Windows to never sleep, and enable automatic
  logon so the task fires after a reboot. See README.md, section "Running unattended".

.PARAMETER Uninstall
  Remove the task instead of creating it.
.PARAMETER Start
  Start the task right away after registering it.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Start
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$Start
)

$ErrorActionPreference = "Stop"
$TaskName   = "ForexBot"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Launcher   = Join-Path $ProjectDir "run_bot.cmd"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($Uninstall) {
    if ($null -eq $existing) {
        Write-Host "Task '$TaskName' is not registered; nothing to do."
        return
    }
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Task '$TaskName' removed."
    return
}

if (-not (Test-Path $Launcher)) {
    throw "Launcher not found: $Launcher"
}

$user = "$env:USERDOMAIN\$env:USERNAME"

$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Launcher`"" -WorkingDirectory $ProjectDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

if ($null -ne $existing) {
    Write-Host "Task '$TaskName' already exists; replacing it."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Forex MT5 trading bot. Restarts automatically on failure." | Out-Null

Write-Host "Task '$TaskName' registered for user $user."
Write-Host "  starts at logon, restarts every 1 min on failure, no time limit"
Write-Host "  launcher: $Launcher"
Write-Host "  console output: $(Join-Path $ProjectDir 'logs\console.log')"

if ($Start) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Task started."
}
