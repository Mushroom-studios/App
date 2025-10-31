@echo off
echo =========================================
echo   🚀 Building Video Color Converter
echo =========================================

REM Optional: activate your venv first
REM call venv\Scripts\activate

REM Ensure PyInstaller is installed
python -m pip show pyinstaller >NUL 2>&1 || python -m pip install pyinstaller

REM Build (GUI only, single exe, with icon if present)
set ICON_ARG=
if exist icon.ico (
  set ICON_ARG=--icon=icon.ico
)

pyinstaller --noconsole --onefile %ICON_ARG% ^
  --add-binary "ffmpeg.exe;." ^
  --add-binary "ffprobe.exe;." ^
  --name "Video Color Converter" ^
  video_color_converter_windows.py

echo.
echo ✅ Done! EXE is in the dist\ folder
pause
