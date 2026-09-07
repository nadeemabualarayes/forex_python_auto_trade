<#
.SYNOPSIS
  Registers (or removes) the "ForexScalpTest" Windows scheduled task that keeps the scalp-test
  bot running. It only ever stops python processes launched from THIS folder, so it cannot
  touch the evaluation bot ("ForexBot", in the main checkout) and vice versa.

.DESCRIPTION
  The task starts run_bot.cmd when you log on and restarts it every minute if it exits
  with a non-zero code (up to 999 times), with no execution time limit. It runs only while
  you are logged on because MetaTrader 5 is a desktop application and cannot be driven from
  a hidden service session.

  Two things this script cannot do for you: set Windows to never sleep, and enable automatic
  logon so the task fires after a reboot. See README.md, section "Running unattended".

.PARAMETER Uninstall
  Stop the bot and remove the task.
.PARAMETER Start
  Start the task right away (after registering it if needed).
.PARAMETER Stop
  Stop the task AND the bot's python process. Stopping the task alone only kills the
  launcher shell and leaves the bot running, so always use this switch.
.PARAMETER Restart
  Stop, then start. Use after changing the bot's code.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Start
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Restart
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$Start,
    [switch]$Stop,
    [switch]$Restart
)

$ErrorActionPreference = "Stop"
$TaskName   = "ForexScalpTest"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Launcher   = Join-Path $ProjectDir "run_bot.cmd"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

function Stop-Bot {
    # Stop-ScheduledTask ends cmd.exe but not its python child, so kill the bot explicitly:
    # any python whose command line names main.py inside THIS project folder (run_bot.cmd
    # launches it by full path). The evaluation bot runs "python main.py" from another folder
    # and is never matched.
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $mainPy = [regex]::Escape((Join-Path $ProjectDir "main.py"))
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match $mainPy }
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "  stopped bot process $($p.ProcessId)"
    }
    if (-not $procs) { Write-Host "  no bot process was running" }
}

if ($Uninstall) {
    if ($null -eq $existing) {
        Write-Host "Task '$TaskName' is not registered; nothing to do."
        return
    }
    Stop-Bot
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Task '$TaskName' removed."
    return
}

if ($Stop -or $Restart) {
    if ($null -eq $existing) { throw "Task '$TaskName' is not registered; run this script without switches first." }
    Write-Host "Stopping bot..."
    Stop-Bot
    if (-not $Restart) { return }
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Task '$TaskName' started."
    return
}

if ($Start -and $null -ne $existing) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Task '$TaskName' started."
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
    Stop-Bot
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Forex MT5 scalp-test bot (XAUUSD M1, own terminal + demo account). Restarts automatically on failure." | Out-Null

Write-Host "Task '$TaskName' registered for user $user."
Write-Host "  starts at logon, restarts every 1 min on failure, no time limit"
Write-Host "  launcher: $Launcher"
Write-Host "  console output: $(Join-Path $ProjectDir 'logs\console.log')"

if ($Start) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Task started."
}
