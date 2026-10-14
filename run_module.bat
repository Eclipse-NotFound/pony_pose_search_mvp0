@echo off
cd /d "%~dp0"

if "%~1"=="" (
    echo Usage: run_module.bat M01 [args...]
    echo.
    echo Modules:
    echo   M01 - extract frames from video
    echo   M02 - select candidate frames ^(GUI^)
    echo   M03 - annotate bounding boxes ^(GUI^)
    echo   M04 - crop characters from frames
    echo   M05 - annotate keypoints on crops ^(GUI^)
    echo   M06 - generate pose vectors
    echo   M07 - annotate query pose ^(GUI^)
    echo   M08 - search similar poses
    echo   M09 - generate results HTML
    echo.
    echo Examples:
    echo   run_module.bat M06 --episode-id s01e15
    echo   run_module.bat M08 --all-episodes --top-n 10 --pose-vector-version v2
    pause
    exit /b 0
)

set MODULE=%~1
shift

if /i "%MODULE%"=="M01" set "SCRIPT=scripts\m01\extract_frames.py"
if /i "%MODULE%"=="M02" set "SCRIPT=scripts\m02\select_candidates.py"
if /i "%MODULE%"=="M03" set "SCRIPT=scripts\m03nnotate_bboxes.py"
if /i "%MODULE%"=="M04" set "SCRIPT=scripts\m04\crop_characters.py"
if /i "%MODULE%"=="M05" set "SCRIPT=scripts\m05nnotate_keypoints.py"
if /i "%MODULE%"=="M06" set "SCRIPT=scripts\m06\generate_pose_vectors.py"
if /i "%MODULE%"=="M07" set "SCRIPT=scripts\m07nnotate_query_pose.py"
if /i "%MODULE%"=="M08" set "SCRIPT=scripts\m08\search_similar_poses.py"
if /i "%MODULE%"=="M09" set "SCRIPT=scripts\m09\generate_results_html.py"

if "%SCRIPT%"=="" (
    echo Unknown module: %MODULE%
    pause
    exit /b 1
)

python --version >nul 2>&1 && goto :ok
python3 --version >nul 2>&1 && set "PY=python3" && goto :okpy
py --version >nul 2>&1 && set "PY=py" && goto :okpy
echo Python not found. Install from https://www.python.org/downloads/
pause
exit /b 1

:ok
set PY=python
:okpy
%PY% %SCRIPT% %*
if errorlevel 1 pause
