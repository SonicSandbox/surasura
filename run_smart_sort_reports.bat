@echo off
chcp 65001 > NUL
cls
:menu
echo ========================================================
echo           SURASURA SMART-SORT REPORT LAUNCHER
echo ========================================================
echo.
echo Select a report to generate:
echo.
echo   1. Detailed Logic Trace (explain_smart_sort.py)
echo      - Shows every calculation step for every file. Verbose.
echo.
echo   2. Concise Logic Trace (explain_smart_sort_concise.py)
echo      - Detailed first round, then summaries. balanced.
echo.
echo   3. Management Executive Summary (explain_smart_sort_management.py)
echo      - High-level strategy, milestones, and results only.
echo.
echo   4. Phase 1: World Build (explain_phase_1.py)
echo      - Shows Indexing and Gold Value (GV) calculation logic.
echo.
echo   Q. Quit
echo.
set /p choice="Enter selection (1-4 or Q): "

if "%choice%"=="1" goto run_detailed
if "%choice%"=="2" goto run_concise
if "%choice%"=="3" goto run_mgmt
if "%choice%"=="4" goto run_phase1
if /i "%choice%"=="Q" goto end

echo Invalid choice.
goto menu

:run_detailed
cls
echo Running Detailed Report...
python debug/explain_smart_sort.py
pause
goto menu

:run_concise
cls
echo Running Concise Report...
python debug/explain_smart_sort_concise.py
pause
goto menu

:run_mgmt
cls
echo Running Executive Summary...
python debug/explain_smart_sort_management.py
pause
goto menu

:run_phase1
cls
echo Running Phase 1 (World Build) Analysis...
python debug/explain_phase_1.py
pause
goto menu

:end
exit
