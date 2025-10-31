    #!/bin/bash
    set -e
    APP_NAME="VideoColorConverter"
    SCRIPT_NAME="video_color_converter_bundled_final.py"
    ICON_FILE="icon.icns"
    echo "1) Cleaning..."
    rm -rf build dist "${APP_NAME}.spec"
    # ensure pyinstaller present in current environment or venv
    PYINSTALLER="$(which pyinstaller || true)"
    if [ -z "$PYINSTALLER" ]; then
      echo "pyinstaller not found in PATH. Try creating venv and installing PyInstaller."
      echo "Run: python3 -m venv venv; source venv/bin/activate; pip install pyinstaller PyQt5"
      exit 1
    fi
    echo "2) Building with $PYINSTALLER ..."
    "$PYINSTALLER" --noconfirm --windowed --onedir --name "$APP_NAME" --icon "$ICON_FILE"       --add-binary "ffmpeg:." --add-binary "ffprobe:."       --add-data "$(python3 - <<'PY'
import PyQt5, os
p=os.path.join(PyQt5.__path__[0],'Qt5','plugins')
print(p)
PY
):PyQt5/Qt5/plugins"       "$SCRIPT_NAME"
    echo "3) Post-processing bundle..."
    APP_PATH="dist/${APP_NAME}.app/Contents/MacOS"
    # copy ffmpeg if not present
    if [ -f "./ffmpeg" ]; then cp ./ffmpeg "$APP_PATH/" || true; chmod +x "$APP_PATH/ffmpeg" || true; fi
    if [ -f "./ffprobe" ]; then cp ./ffprobe "$APP_PATH/" || true; chmod +x "$APP_PATH/ffprobe" || true; fi
    # ensure Qt plugins exist - copy from site-packages if pyinstaller missed any
    PYQT_PLUGINS="$(python3 - <<'PY'
import PyQt5, os
p=os.path.join(PyQt5.__path__[0],'Qt5','plugins')
print(p)
PY
)"
    if [ -d "$PYQT_PLUGINS" ]; then
      mkdir -p "dist/${APP_NAME}.app/Contents/Resources/PyQt5/Qt5/plugins"
      cp -R "$PYQT_PLUGINS"/* "dist/${APP_NAME}.app/Contents/Resources/PyQt5/Qt5/plugins/" || true
    fi
    # remove quarantine
    if [ -d "dist/${APP_NAME}.app" ]; then xattr -dr com.apple.quarantine "dist/${APP_NAME}.app" || true; fi
    echo "Build finished: dist/${APP_NAME}.app"
    echo "Log (app) will be at: dist/${APP_NAME}.app/Contents/MacOS/app_log.txt"
