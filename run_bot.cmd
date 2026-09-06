@echo off
rem Launcher used by the "ForexBot" scheduled task (see install_task.ps1).
rem Runs the bot from the project folder and appends console output to logs\console.log
rem so a crash is still visible after the window is gone. Exit code is passed through:
rem a non-zero code makes Task Scheduler restart the task.
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
if "%BOT_PYTHON%"=="" set "BOT_PYTHON=python"
echo [%date% %time%] launcher: starting bot with %BOT_PYTHON% >> logs\console.log
"%BOT_PYTHON%" main.py >> logs\console.log 2>&1
set "RC=%ERRORLEVEL%"
echo [%date% %time%] launcher: bot exited with code %RC% >> logs\console.log
exit /b %RC%
