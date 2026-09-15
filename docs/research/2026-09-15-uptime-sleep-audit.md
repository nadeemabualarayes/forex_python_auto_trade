# Uptime / sleep audit for the scalp-test bot

Date: 2026-09-15 · Worktree: `scalp-test` (`C:\Develompent\forex_scalp_test`) · Task: `ForexScalpTest` · Machine: `NADEEM`

Sections 1–8 are the read-only audit as delivered: at that point nothing had been changed (no Windows setting, no
scheduled task, no repository code, no restart). Section 9 lists the external changes; **A and C were approved and
applied at 18:56 (section 10)**, B, D and E remain open. Section 11 records an incident caused by one of the audit's
own read-only checks: the bot's MT5 terminal exited at 18:39:54 and the bot has been running without quotes since.

## 1. Findings in one place

1. **The AC power plan is not the cause.** On AC *and* on battery the sleep timer, hibernate timer and display
   timer are already **Never**. The README's step "set Screen and Sleep to Never" has been done.
2. **The 32.5 h of lost market time have three causes, none of them idle sleep:**

   | cause | market time lost | share |
   | --- | --- | --- |
   | laptop unplugged with the **lid closed**: lid action = Sleep → Modern Standby (bot and MT5 frozen), then, on battery, Windows' standby budget and the critical-battery level (2%) put the machine into **hibernation** | 26.1 h | 80% |
   | **Windows Update restart at 00:30 on 09-09** with nobody logged on afterwards until 06:58; the task only starts the bot at logon | 6.0 h | 19% |
   | manual stops (09-09 14:12, 09-14 09:31) | 0.3 h | 1% |

3. **The bot and the scheduled task behave correctly.** The bot never crashed; after every sleep it resumed where
   it was, and after every reboot it was restarted by the task as soon as the user logged on. The task has no
   execution time limit, restarts on failure, and is allowed to start and keep running on battery.
4. **This is a Modern Standby laptop** (Lenovo 21MA001PGR; S0 Low Power Idle; the firmware has no S3). On such a
   machine the screen turning off *is* the entry into standby, and standby freezes desktop programs (the bot and
   `terminal64.exe`) within moments. The event log shows the lid closing first raises a "Screen Off Request"
   standby entry and only then the lid action. So "lid closed, do nothing" is not proven to keep the bot alive
   without an external display; it must be tested (procedure in 6.2).
5. **The bot cannot prevent any of this itself.** A power request from `main.py` (`SetThreadExecutionState`)
   only blocks idle-timer sleep, which is already off. It cannot block a lid or power-button sleep, a
   critical-battery hibernation or a reboot, and an "execution required" request would exempt only the Python
   process, not MetaTrader. **No repository change is necessary** (section 7).
6. **Four trades were open while the bot was frozen.** All were protected by their server-side stops (three hit a
   stop, one was closed by hand); no trade was left unprotected. Trailing and breakeven management did not run
   during those windows.
7. **Windows Update downloaded new updates today (11:24–12:07).** A restart request may already be pending. If
   Windows restarts the machine unattended (it chose ~00:30 both times so far), the bot stays down until the next
   logon, exactly as on 09-09.

Recommended, in order of value: keep the laptop plugged in with the lid open during market hours (no change
needed, immediately effective); set lid close and power button on AC to "Do nothing" and run the 5-minute lid
test; stop Windows from restarting on its own during the validation window; decide how the bot should come back
after a reboot.

## 2. What was inspected (all read-only)

* Repository: `run_bot.cmd`, `install_task.ps1`, `README.md` ("Running unattended"), `main.py` (`run()` loop and
  reconnect), `execution.py` (`init_mt5`, `mt5_init_args`), `logs/bot.log`, `logs/console.log`.
* Scheduled task: `Export-ScheduledTask ForexScalpTest` (XML), `Get-ScheduledTaskInfo`, Task Scheduler
  operational log state.
* Power: `powercfg /a`, `/getactivescheme`, `/list`, `/q` for the Sleep, Display, Buttons and Battery subgroups;
  the hidden lid/button/unattended-sleep values read from the power registry; battery and AC state (WMI).
* Windows event logs since 2026-09-07: Kernel-Power 41/42/107/109/506/507, EventLog 6005/6006/6008, User32 1074,
  Power-Troubleshooter (sleep/wake times), Kernel-General time changes (real sleep durations),
  TerminalServices-LocalSessionManager 21–25 and User Profile Service 1–4 (logon/logoff times),
  WindowsUpdateClient operational log, `Get-HotFix`.
* Windows Update and logon configuration: `HKLM\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings`, the (absent)
  `HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate` keys, `UpdatePolicy\PolicyState`, Winlogon
  `AutoAdminLogon`, ARSO opt-out key, `quser`.
* Broker deal history (MT5, read-only) to find trades open during each silence.

## 3. Current behaviour

### 3.1 Machine and power plan

| item | value | note |
| --- | --- | --- |
| machine | Lenovo 21MA001PGR, notebook (chassis 10), battery present | on AC and 100% at audit time; Windows 11 Pro 10.0.26200 |
| sleep states | Standby (S0 Low Power Idle) Network Connected, Hibernate, Fast Startup | S1/S2/S3 "not supported by the system firmware": **Modern Standby only** |
| active scheme | Balanced `381b4222-f694-41f0-9685-ff5bb260df2e` (the only scheme) | |
| Sleep after | AC 0 (Never) / DC 0 (Never) | correct already |
| Hibernate after | AC 0 (Never) / DC 2147483647 s (effectively never) | correct already |
| Turn off display after | AC 0 (Never) / DC 0 (Never) | correct already |
| **Lid close action** | **AC 1 = Sleep / DC 1 = Sleep** (explicit scheme values) | **the trigger of every standby period** |
| **Power button** | AC 1 = Sleep / DC 1 = Sleep | a press sleeps the machine |
| Sleep button | AC 1 / DC 1 = Sleep | |
| Lid open | wake (default) | |
| System unattended sleep timeout (hidden) | 120 s (default) | only matters after an unattended wake; no change proposed |
| Low battery | 6%, action Do nothing | |
| Critical battery | 2%, action **Hibernate** | reached on 09-08 21:41, 09-13 22:24, 09-14 19:38 ("Sleep Reason: Battery") |
| Wake timers | AC enabled / DC disabled | irrelevant |

### 3.2 Scheduled task `ForexScalpTest` (as registered)

| setting | value | assessment |
| --- | --- | --- |
| trigger | at logon of `NADEEM\SS` | correct for a desktop app (MT5 needs the interactive session); implies the bot only returns after a logon |
| principal | interactive token, least privilege | correct |
| action | `cmd.exe /c C:\Develompent\forex_scalp_test\run_bot.cmd`, working dir = project | the launcher appends to `logs/console.log` and passes the exit code through |
| ExecutionTimeLimit | `PT0S` (no limit) | correct; `[TimeSpan]::Zero` in the script did register as unlimited |
| restart on failure | 999 times, every 1 min | correct; exit code 1 (MT5 unusable at start-up) is retried |
| DisallowStartIfOnBatteries / StopIfGoingOnBatteries | false / false | correct: unplugging never stops the task |
| StartWhenAvailable | true | correct |
| MultipleInstances | IgnoreNew | correct: no second bot |
| idle conditions | none (`RunOnlyIfIdle` absent) | the `StopOnIdleEnd=true` in the XML is inert |
| Task Scheduler operational log | disabled (Windows default) | task start/stop history is not recorded; optional to enable (9.E) |
| last result | 0x41301 (running), no missed runs | |

`run_bot.cmd` history (`logs/console.log`): exit code `1073807364` (0x40010004, process terminated by a shutdown)
at 09-09 00:30:05 and 09-15 00:36:05 = the two Windows Update restarts; `-1` = the script's own
`Stop-Process` during requested restarts; three stops with no exit line at all (09-09 14:12, 09-13 12:03,
09-14 09:31 `^C`) = the console window or process tree was ended by hand.

### 3.3 What the bot does across a sleep or a reboot

* **Sleep / Modern Standby.** The process is frozen with everything else on the desktop; nothing is logged; on
  wake the loop simply continues (no error, no reconnect needed: 09-07 21:53, 09-08 21:58, 09-09 08:18, 09-14
  17:01, 18:39, 23:14 all show the next `history: synced` line within a minute of the wake). The tick-path
  recorder resumes and back-fills the missing ticks from the terminal's history. Analytics are deal-derived, so
  trades that closed during the freeze appear on the next sync.
* **Positions during a freeze.** Stops and targets live on the broker's server, so an open trade stays
  protected; the bot's breakeven/trailing logic does not run until wake. Four trades were open during a silence:

  | trade | open | closed while frozen | how |
  | --- | --- | --- | --- |
  | #58333856498 SHORT | 09-07 16:06 | 16:31 | initial stop 4405.66 hit (−$3.97) |
  | #58358295585 LONG | 09-08 21:31 | 21:44 | stop already trailed to 4383.43 hit (+$0.06) |
  | #58363017122 SHORT | 09-09 07:24 | 07:27 | initial stop 4378.79 hit (−$2.55) |
  | #58379348247 LONG | 09-09 22:02 | 22:20 | closed by hand at 4402.42 (+$2.51) |

* **Reboot.** The process is terminated by the shutdown (exit 0x40010004). The task starts it again **at the next
  interactive logon**, not at boot: 09-09 boot 00:34 → logon 06:58:12 → bot 06:58:29 (6.4 h down); 09-14 boot
  00:14:18 → logon 00:14:42 → bot 00:15:23; 09-15 boot 00:37:57 → logon 00:38:39 → bot 00:39:12. Automatic
  logon is off (`AutoAdminLogon = 0`). Windows' "finish setting up after an update" sign-in (ARSO) is not opted
  out, but it did not sign the user in after the 09-09 update restart, so it cannot be relied on. When the
  terminal is not running, `mt5.initialize(path=…)` launches the portable terminal itself.

## 4. Why the 32.5 h gap occurred: timeline with evidence

Bot silences over 5 minutes that overlap market hours (Mon–Thu 01:00–24:00, Fri 01:00–23:00 server = local),
matched to the Windows System log. "Austerity" = Kernel-Power 507/506 "Austerity Battery Drain Budget Exceeded",
which only happens in standby on battery.

| silence (local) | market h | Windows evidence | cause |
| --- | --- | --- | --- |
| 09-07 16:12 → 16:41 | 0.5 | 16:12:30 standby "Screen Off Request", 16:12:47 wake "Input Mouse", **16:13:02 standby "Lid"** | lid closed |
| 09-07 16:41 → 21:53 | 5.2 | 16:41:18 austerity (on battery) | lid closed, unplugged |
| 09-07 21:53 → 09-08 08:24 | 9.5 | 21:53:25 "Hibernate from Sleep - Standby Battery Budget Exceeded"; 08:24:42 wake "Lid" (Power-Troubleshooter: asleep 18:53Z → 05:24Z) | hibernated overnight, unplugged |
| 09-08 15:52 → 17:11 | 1.3 | 15:52:34 standby "Lid" → 17:11:57 wake "Lid" | lid closed |
| 09-08 21:41 → 21:58 | 0.3 | 21:41:27 "entering sleep. Sleep Reason: Battery" → 21:58:44 "Resume from Hibernate" | battery reached 2% |
| 09-09 00:29 → 06:58 | 6.0 | 00:30:05 bot terminated by shutdown; 00:30:47 and 00:33:50 reboots, 1074 "TrustedInstaller … Operating System: Upgrade (Planned)" (KB5124007 / KB5126052 installed 09-08); **first logon 06:58:12** | Windows Update restart, nobody logged on |
| 09-09 07:24 → 08:18 | 0.9 | 07:24:22 standby "Lid" → 08:18:00 wake "Lid" | lid closed |
| 09-09 14:12 → 14:23 | 0.2 | launcher restarted 14:23:44, no exit code logged | manual restart |
| 09-09 15:59 → 16:57 | 1.0 | 16:00:24 standby "Lid"; 16:21:51 austerity; 16:57:25 wake "Lid" | lid closed, unplugged |
| 09-09 22:15 → 10 00:02 | 1.7 | 22:16:00 standby "Lid"; 23:11:12 austerity; 00:02:27 wake "Lid" | lid closed, unplugged |
| 09-11 22:55 → 09-13 08:40 | 0.1 | 22:55:34 "Screen Off Request", 22:55:36 "Lid"; 09-12 00:09 austerity; 04:29 hibernate (budget); 09-13 08:40 wake "Lid" | weekend, market closed |
| 09-13 12:03 → 13:19 | 0 | process tree ended by hand, no exit code; restarted on request 13:19 | manual stop (Sunday) |
| 09-13 22:24 → 09-14 00:15 | 0 | 22:24:01 "Sleep Reason: Battery"; 23:08 resume from hibernate; Kernel-Power 41 (BugcheckCode 0: power loss or forced power-off, not a crash dump); boot 00:14 | unexpected shutdown (Sunday) |
| 09-14 09:31 → 09:38 | 0.1 | `^C` in the console; restarted on request | manual stop |
| 09-14 16:33 → 18:39 | 2.1 | **16:34:21 standby "Lid"**; 17:01:22 austerity; 18:39:59 wake "Lid" | lid closed, unplugged |
| 09-14 19:38 → 23:14 | 3.6 | 19:38:35 "Sleep Reason: Battery" → hibernate; 23:13:58 "Resume from Hibernate" (asleep 16:38Z → 20:13Z) | battery reached 2% |
| 09-15 00:35 → 00:39 | 0.1 | 00:36:05 1074 "MoUsoCoreWorker … Service pack (Planned)", 00:37:19 "TrustedInstaller … Upgrade (Planned)" (KB5129195 installed 09-14); logon 00:38:39 | Windows Update restart, user present |

Totals: lid closed / unplugged 26.1 h; update restart without logon 6.0 h; manual 0.3 h; sum 32.4 h (32.5 h in the
report, which summed unrounded minutes). Not one minute came from an idle timer.

**Why the lid matters more on this laptop than on a desktop.** Modern Standby has no light sleep state: "sleep"
means the screen goes off and the system enters S0 low-power idle, where the Desktop Activity Moderator suspends
desktop programs, network or not. Two details from the log show how tightly screen-off and standby are coupled
here: on 09-11 22:55:34 the machine entered standby with reason "Screen Off Request" and two seconds later
re-entered with reason "Lid" (the panel switching off preceded the lid action), and on 09-07 16:12:30 a plain
screen-off request entered standby on its own. Once in standby on battery, Windows' standby budget escalated to
"austerity" after 20–60 minutes and to hibernation after some hours; on AC the machine would have stayed in
standby but the bot would still have been frozen.

## 5. Can the bot itself prevent Windows from sleeping?

Technically a Windows process can hold a power request:

* `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` (one `ctypes` call at start-up in `main.py`,
  outside `Bot.tick()`, so it would not touch trading logic). It resets the idle timer and thereby prevents
  **idle-timer** sleep and screen-off. Both timers are already Never on this machine, so it would change nothing.
  It does not block a lid or power-button sleep, a critical-battery action, or a reboot: 100% of the observed
  losses.
* `PowerCreateRequest` + `PowerSetRequest(PowerRequestExecutionRequired)` exempts the calling process from being
  suspended in Modern Standby. It would exempt `python.exe` only; `terminal64.exe` (MetaTrader) would still be
  frozen, so there would be no quotes, no order execution and no stop management. Useless for this bot, and it
  would also keep the laptop awake on battery until it hibernates.

Conclusion: not necessary and not effective. Keep the bot free of Windows-specific power code; solve this at the
machine level (section 6).

## 6. Recommendations

### 6.1 Power settings on AC (external change, needs approval; see 9.A)

Only the lid and button actions need changing. Run from an elevated PowerShell ("Run as administrator"):

```powershell
# current values: lid close = 1 (Sleep) on AC and DC, power button = 1 (Sleep) on AC and DC
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0       # lid close on AC: do nothing
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS PBUTTONACTION 0   # power button on AC: do nothing (optional; a press then does nothing, hold 10 s still forces off)
powercfg /setactive SCHEME_CURRENT                                     # apply
```

Leave the DC (battery) values alone: on battery the machine should still sleep when closed, and the bot should not
be run on battery anyway. The sleep, hibernate and display timers need no change.

Rollback:

```powershell
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 1
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS PBUTTONACTION 1
powercfg /setactive SCHEME_CURRENT
```

Verification (the lid setting is hidden from `powercfg /q`; read the registry or look in Control Panel → Power
Options → "Choose what closing the lid does", column "Plugged in"):

```powershell
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes\381b4222-f694-41f0-9685-ff5bb260df2e\4f971e89-eebd-4455-a8de-9e59040e7347\5ca83367-6e45-459f-a27b-476b1d01c936' | Select-Object ACSettingIndex, DCSettingIndex
# expected after the change: ACSettingIndex 0, DCSettingIndex 1
```

### 6.2 Operating rule for the validation window, and the lid test

* **Plugged in, lid open, during market hours (Mon 01:00 → Fri 23:00 server).** This is the only configuration
  this audit can prove keeps the bot running on this laptop, and it needs no change at all. All 26.1 h of
  standby/hibernation losses started with the lid closing or the battery draining.
* **After 6.1 is applied, test whether a closed lid is acceptable on AC** (5 minutes, when no position is open):
  1. bot running, laptop plugged in; note the last `history: synced` line in `logs/bot.log`;
  2. close the lid for 5 minutes, then open it;
  3. pass = the once-a-minute `history: synced` lines continued through the closed period and the System log has
     no Kernel-Power 506 ("entering Modern Standby") during it; fail = a gap in the log and/or a 506 event.
  If it fails, lid-closed running needs an external display (or an HDMI dummy plug) so that a screen stays on, or
  the invasive option in 6.5. Do not assume; test.
* Do not run the bot on battery: the machine hibernates at 2% and enters "austerity" standby long before that.

### 6.3 Scheduled task

No change needed to the task itself; the registration is correct for an interactive desktop app. Two facts to
keep in mind:

* The bot returns after a reboot **only when someone logs on**. Windows' after-update auto sign-in (ARSO) did not
  do that on 09-09. The README's auto-logon (`netplwiz`) would fix it for every reboot, but on a laptop it means
  anyone who powers the machine on lands on the desktop and in the MT5 terminals; that is a security trade-off for
  you to decide (9.D), not something to apply silently. If you do not enable it, the practical rule is: prevent
  unattended restarts (6.4) and, after any planned restart, log on.
* Optional (9.E): enable the Task Scheduler operational log so future task starts/stops are recorded:
  `wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true` (elevated). Reversible with `/e:false`.

### 6.4 Windows Update: stop unattended restarts during the validation window (needs approval; see 9.B, 9.C)

Facts: Windows 11 Pro, no update policies configured, active hours "automatic" (no manual range), "Get the latest
updates as soon as they're available" is **ON** (`IsContinuousInnovationOptedIn = 1`), no pause active. Both
restarts (09-09 00:30 and 09-15 00:36) installed monthly security updates and happened around 00:30, i.e. inside
the 00–07 trading session. Updates were downloaded again today between 11:24 and 12:07.

Options, safest first; none disables Windows security features:

1. **Policy: download automatically, install only when you choose** (Pro supports this; updates keep arriving,
   nothing installs or restarts until you click *Install* in Settings, e.g. on a Saturday). Elevated prompt:

   ```cmd
   reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" /v NoAutoUpdate /t REG_DWORD /d 0 /f
   reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" /v AUOptions   /t REG_DWORD /d 3 /f
   ```
   Effect is visible in Settings → Windows Update as "Some settings are managed by your organization".
   Rollback: `reg delete "HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" /f`.
   Trade-off: security updates wait for you; install them on a weekend and restart deliberately.

2. **Settings only, no registry: Pause updates** (Settings → Windows Update → Pause updates → up to 5 weeks,
   i.e. to about 2026-10-20). Fully reversible with "Resume updates". Trade-off: all updates, including security
   fixes, are deferred for the pause; check Windows Security → "Protection updates" still refreshes.

3. **Turn off "Get the latest updates as soon as they're available"** (Settings → Windows Update). This stops
   optional, non-security feature updates from arriving early; it does not affect security updates. Low value on
   its own, no downside.

4. **Active hours** cannot cover a 24-hour bot (18 h maximum) and are therefore not sufficient. If you set them
   by hand, 06:00–24:00 pushes restarts into 00:00–06:00, the least-traded hours, but a restart there still
   costs the rest of that session unless someone logs on (see 6.3).

5. The Group Policy "No auto-restart with logged on users for scheduled automatic updates installations"
   (`…\AU\NoAutoRebootWithLoggedOnUsers = 1`) is documented to apply only when "Configure Automatic Updates" is
   set to scheduled installs (option 4). Because its effect under the default configuration is not guaranteed,
   option 1 is preferred.

Whatever is chosen: check Settings → Windows Update **now** for a pending restart from today's downloads, and if
there is one, restart at a chosen moment (market closed, or between trades) and log on afterwards.

### 6.5 Not recommended (kept for completeness)

* **Disable Modern Standby** (`HKLM\SYSTEM\CurrentControlSet\Control\Power\PlatformAoAcOverride = 0`, reboot).
  Machine-wide platform change; since the firmware has no S3, the laptop would be left with hibernate as its only
  sleep. Only worth considering if lid-closed operation is essential and the lid test in 6.2 fails.
* **Automatic logon** (`netplwiz`): see 6.3.
* **Power request in the bot**: see section 5.

## 7. Is a repository change necessary?

**No.** `install_task.ps1`, `run_bot.cmd` and `main.py` already do what they should; the losses come from lid,
battery and update restarts, which no code in the bot can prevent. Optional documentation nit only: README
"Running unattended" step 2 could mention the lid and power-button actions for laptops. Not done in this audit.

## 8. Validation

* Repository: this note is the only file added by this audit (`git status` on `scalp-test`: new untracked
  `docs/research/2026-09-15-uptime-sleep-audit.md`; the earlier, already-reported uncommitted items
  `docs/research/2026-09-13-tick-path-logging.md` (modified) and `docs/research/forward_validation_2026-09-15.txt`
  (untracked) are unchanged by this task). No `.py`, `.cmd`, `.ps1` or config file was edited, so the test suite
  was not run.
* `main` (`C:\Develompent\forex_python_auto_trade`): untouched, clean at `6490a64`.
* Strategy / config / risk: `config.py`, `strategy.py`, `execution.py`, `risk.py`, `position_manager.py`,
  `engines.py`, `main.py`, `install_task.ps1`, `run_bot.cmd` are identical to `HEAD` (`011dae8`).
* Nothing was committed, pushed, deployed or restarted; `ForexScalpTest` is still running the process started at
  18:26:19; `ForexBot` was not touched. (Written before section 11 was discovered: that process has been without a
  terminal link since 18:39:54 and needs a restart.)

## 9. Changes that need your approval (none applied)

| id | change | where | reversible | status |
| --- | --- | --- | --- | --- |
| A | lid close on AC → Do nothing; power button on AC → Do nothing (6.1) | `powercfg` | yes, commands given | **applied 2026-09-15 18:56** (section 10) |
| B | Windows Update: auto-download, install only on demand (`AUOptions = 3`) (6.4 option 1) **or** Pause updates for the validation window (6.4 option 2) | registry policy / Settings | yes | open |
| C | turn off "Get the latest updates as soon as they're available" (6.4 option 3) | Settings / its registry value | yes | **applied 2026-09-15 18:56** (section 10) |
| D | automatic logon so the bot returns after any reboot without you (6.3) | `netplwiz` | yes; security trade-off on a laptop | open |
| E | enable the Task Scheduler operational log (6.3) | `wevtutil`, elevated | yes | open |

Immediately effective without any change: keep the laptop plugged in with the lid open while the market is open,
and restart Windows only at moments you choose, logging on afterwards.

## 10. Applied on 2026-09-15 (A and C, approved "A+C")

Both went through from the signed-in user's session without elevation (the scheme's user settings and the Windows
Update UX key accept the user's own writes; no UAC prompt was needed). Values read back from the registry at
18:58:17; the active scheme is still Balanced and the sleep/hibernate/display timers are unchanged (Never).

| id | command / value | before | after |
| --- | --- | --- | --- |
| A | `powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0` | lid close AC 1 (Sleep) / DC 1 | **AC 0 (Do nothing)** / DC 1 |
| A | `powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS PBUTTONACTION 0` | power button AC 1 (Sleep) / DC 1 | **AC 0 (Do nothing)** / DC 1 |
| A | `powercfg /setactive SCHEME_CURRENT` | | applied |
| C | `HKLM\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings\IsContinuousInnovationOptedIn` (the value behind the Settings toggle "Get the latest updates as soon as they're available") | 1 (on) | **0 (off)** |

Rollback: section 6.1 for A; for C set the value back to `1` or switch the toggle on in Settings → Windows Update.
Still to do: the 5-minute lid test (6.2) before relying on a closed lid; B, D, E await a decision.

## 11. Incident during the audit: the bot's terminal exited at 18:39:54

**What happened.** The scalp terminal (`C:\Develompent\mt5_scalp\terminal64.exe`, launched by the bot at 00:39:09)
logged "connection to MetaQuotes-Demo lost" at 18:39:04 and then a clean exit at 18:39:54 ("exit with code 0",
"stopped with 0", "shutdown with 0"; no crash record in the Application log, no system shutdown). The bot's log
shows `[XAUUSD] idle: no live quote` in the same second and nothing after it: the once-a-minute `history: synced`
line stopped, because `sync_deals` gets `None` from a dead link and the line is only written when rows were
synced. A new terminal instance started at 18:46:16 (PID 7712, parent: a Python process that has since exited) and
authorised on the account at 18:46:17 with 0 positions and 0 orders.

**Cause.** Two of the audit's "read-only" checks attached to the terminal with
`mt5.initialize(path=…, login=…, password=…, server=…, portable=True)` and ended with `mt5.shutdown()`. The
second one (the four-trades lookup) ran at 18:46 and, finding no terminal, launched the one now running. The first
one (positions open during silences) ran in the minute the terminal exited; its `shutdown()` is the only event
that coincides with the exit. Identical scripts earlier the same day (08:16, 18:25) and the replay audit on 09-13
did not close the terminal; the difference this time is that the terminal was in its "connection lost" state when
the script attached. The exact mechanism inside the MetaTrader5 package (5.0.6180) is not established; the
correlation is.

**Impact.** The bot process (PID 20464) is alive and its loop runs, but it is detached from MetaTrader: the
dashboard shows `account: {}` and `state: "no live quote"`. It cannot see quotes, open or manage trades, or record
tick paths. No position was open (the terminal synchronised 0 positions at 18:46:18, last deal 15:40:48), so no
money was at risk; market time was lost from 18:39:54 to 19:06:46 (27 minutes). The restart was not done inside
the audit, whose rule was "do not restart anything"; it was approved ("RESTART") and run at 19:06:45
(`install_task.ps1 -Restart`): the new process (PID 27640) attached to the running terminal (PID 7712, no second
terminal launched), synced 76 deals, sent its heartbeat, and the dashboard shows the account (balance 2967.20),
`market_open: true`, trader state `watching`, no positions.

**Two follow-ups, neither done here:**

1. Research scripts must not attach to a live bot's terminal with `initialize(path, login, …)` + `shutdown()`.
   Use the bot's own `status.json`, `logs/history.db` or a terminal that no bot is using. The offending pattern is
   in `docs/research/forward_report.py`, `mae_mfe_analysis.py`, `path_recorder_replay_audit.py` and the ad-hoc
   checks used today.
2. The bot does not notice a lost terminal link: `Bot.tick()` treats every `None` from MT5 as "no data", nothing
   raises, so `run()`'s reconnect path (`terminal_info() is None` → `init_mt5`) is never reached, and the Telegram
   heartbeat keeps going. A watchdog in `main.py` (for example: if the terminal is unreachable, or there has been
   no live quote for N minutes while the market is open, re-initialise and alert) would turn this silent failure
   into a self-healing one. It is connection handling, not trading logic, but it is a code change and would need
   approval and tests. Not started.
