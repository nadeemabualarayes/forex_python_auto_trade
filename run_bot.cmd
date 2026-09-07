@echo off
rem Launcher used by the "ForexScalpTest" scheduled task (see install_task.ps1).
rem Runs the scalp-test bot from this folder and appends console output to logs\console.log
rem so a crash is still visible after the window is gone. Exit code is passed through:
rem a non-zero code makes Task Scheduler restart the task.
rem main.py is launched by full path so this process can be told apart from the evaluation bot.
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
if "%BOT_PYTHON%"=="" set "BOT_PYTHON=python"
echo [%date% %time%] launcher: starting scalp-test bot with %BOT_PYTHON% >> logs\console.log
"%BOT_PYTHON%" "%~dp0main.py" >> logs\console.log 2>&1
set "RC=%ERRORLEVEL%"
echo [%date% %time%] launcher: bot exited with code %RC% >> logs\console.log
exit /b %RC%
