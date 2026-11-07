@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ---------------------------------------------------------------------------
REM Find a Python that actually RUNS.
REM Checking that the file exists is NOT enough: a venv created on a different
REM Windows profile leaves Scripts\python.exe sitting there, but launching it
REM fails with "No Python at ..." because it points at an interpreter under the
REM other profile. The old version of this file used `if exist` and silently
REM picked a dead one, so every test appeared to fail.
REM ---------------------------------------------------------------------------
set "PY="
call :try "C:\ClaudeDeps\leadgen-venv\Scripts\python.exe"
call :try "C:\ClaudeDeps\docpipeline-venv\Scripts\python.exe"
call :try "python"
call :try "py"

if not defined PY (
  echo.
  echo Could not find a working Python. Install Python 3.11+ and run this again.
  pause
  exit /b 1
)

echo Running engine evals ^(offline, no keys, no cost^)
echo Python: %PY%
echo.

set FAILED=0
call :run eval_organize
call :run eval_emailgen
call :run eval_verify
call :run eval_cost
call :run eval_gateway
call :run eval_finders
call :run eval_icebreaker
call :run eval_instantly
call :run eval_sheets
call :run eval_schedule
call :run eval_ledger
call :run eval_retry
call :run eval_pipeline
call :run eval_net
REM --- V2: field map, rules, campaigns, dynamic labels, runner ---
call :run eval_fieldmap
call :run eval_rules
call :run eval_campaigns
call :run eval_campaign_admin
call :run eval_labels
call :run eval_runner
REM --- V4: import, per-campaign schedules, login ---
call :run eval_imports
call :run eval_lane_schedules
call :run eval_auth
call :run eval_connections
REM --- V6: the finding recipe ---
call :run eval_recipe

REM --- full stack, session 1: the shared lead record ---
call :run eval_lead_record
call :run eval_research
call :run eval_demo
call :run eval_stack_api

REM --- full stack, session 2: ice breakers, cold email, sending (test mode), replies ---
call :run eval_icebreakers
call :run eval_templates
call :run eval_sending
call :run eval_replies
call :run eval_stack_steps

REM --- full stack, session 3: schedules, health agent, live demo ---
call :run eval_stack_schedule
call :run eval_health
call :run eval_stack_demo

REM --- real-run showcase: Draft-only push, Privacy switch, step cards, template queue ---
call :run eval_showcase

REM --- a 6-step campaign runs on its own page: limits, filters, Run now, schedule, direct push ---
call :run eval_campaign_pipeline

echo.
if %FAILED%==0 (
  echo ALL SUITES PASSED
) else (
  echo %FAILED% SUITE^(S^) FAILED - see above
)
echo.
pause
exit /b %FAILED%

:try
if defined PY goto :eof
%~1 -c "import sys" >nul 2>&1
if errorlevel 1 goto :eof
set "PY=%~1"
goto :eof

:run
"%PY%" %~1.py
if errorlevel 1 set /a FAILED+=1
echo.
goto :eof
