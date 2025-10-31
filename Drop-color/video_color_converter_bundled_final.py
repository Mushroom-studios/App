#!/usr/bin/env python3
"""Video Color Converter (bitrate = original or 12 Mbit/s fallback)
- Keeps original video bitrate for best quality
- Compatible with macOS 14.5 (Sonoma)
- Keeps QThread references to prevent crash
- Logs activity to app_log.txt
"""
import os, sys, traceback, shutil, re
from pathlib import Path
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QFileDialog,
    QVBoxLayout, QHBoxLayout, QSlider, QProgressBar, QMessageBox, QListWidget
)

# ────────────────────────────────
# Logging
# ────────────────────────────────
def init_logging():
    try:
        base = Path(__file__).resolve().parent
        log_path = base / "app_log.txt"
        return open(log_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        return None

LOG = init_logging()
def log(msg):
    try:
        if LOG:
            LOG.write(msg + "\n")
    except Exception:
        pass

# ────────────────────────────────
# Qt setup for macOS bundle
# ────────────────────────────────
try:
    import PyQt5
    if sys.platform == "darwin":
        os.environ.setdefault("QT_QPA_PLATFORM", "cocoa")
        try:
            site_plugins = Path(PyQt5.__path__[0]) / "Qt5" / "plugins"
            if site_plugins.exists():
                os.environ.setdefault("QT_PLUGIN_PATH", str(site_plugins))
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                mp = Path(meipass) / "PyQt5" / "Qt5" / "plugins"
                if mp.exists():
                    os.environ["QT_PLUGIN_PATH"] = str(mp)
        except Exception as e:
            log("plugin path detect error: " + str(e))
except Exception as e:
    print("PyQt5 import failed:", e)
    raise

# ────────────────────────────────
# FFmpeg Worker
# ────────────────────────────────
class FFmpegWorker(QThread):
    progress_changed = pyqtSignal(int)
    status_changed = pyqtSignal(str)
    finished_ok = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, input_path, output_path, saturation_value):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.saturation_value = saturation_value

    def run(self):
        try:
            import subprocess
            ffmpeg = shutil.which("ffmpeg") or str(Path(__file__).parent / "ffmpeg")
            ffprobe = shutil.which("ffprobe") or str(Path(__file__).parent / "ffprobe")
            if not ffmpeg or not ffprobe:
                self.error_occurred.emit("ffmpeg/ffprobe not found")
                return

            # ─── Probe duration ───────────────────────────
            p = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", self.input_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            duration = float(p.stdout.strip()) if p.stdout.strip() else 0.0

            # ─── Probe original bitrate ───────────────────
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=bit_rate",
                 "-of", "default=noprint_wrappers=1:nokey=1", self.input_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            orig_bitrate = probe.stdout.strip()
            if not orig_bitrate or not orig_bitrate.isdigit():
                orig_bitrate = None

            # ─── Build filter & command ───────────────────
            vf = f"eq=saturation={self.saturation_value}"
            if self.saturation_value <= 0:
                vf += ",format=yuv420p"

            cmd = [ffmpeg, "-y", "-i", self.input_path, "-vf", vf, "-c:v", "libx264"]
            if orig_bitrate:
                cmd += ["-b:v", orig_bitrate]
            else:
                cmd += ["-b:v", "12M"]
            cmd += ["-maxrate", "12M", "-bufsize", "24M", "-c:a", "copy", self.output_path]

            log("Running: " + " ".join(cmd))

            proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True)
            time_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
            last = -1
            for L in proc.stderr:
                m = time_re.search(L)
                if m and duration > 0:
                    h, mm, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                    t = h * 3600 + mm * 60 + s
                    pct = int(min(100, (t / duration) * 100))
                    if pct != last:
                        last = pct
                        self.progress_changed.emit(pct)
            proc.wait()
            if proc.returncode == 0:
                self.finished_ok.emit()
            else:
                self.error_occurred.emit(f"ffmpeg rc={proc.returncode}")
        except Exception as e:
            self.error_occurred.emit(str(e))

# ────────────────────────────────
# Main UI
# ────────────────────────────────
class VideoColorConverterApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Color Converter")
        self.setMinimumWidth(700)
        self.input_files = []
        self.output_folder = ""
        self.workers = []  # keep references

        # UI setup
        self.list_widget = QListWidget()
        self.btn_add = QPushButton("Add videos (max 20)")
        self.btn_add.clicked.connect(self.add_files)
        self.btn_remove = QPushButton("Remove selected")
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_output = QPushButton("Select output folder")
        self.btn_output.clicked.connect(self.select_output)
        self.sat_label = QLabel("Saturation: 100%")
        self.sat_slider = QSlider(Qt.Horizontal)
        self.sat_slider.setRange(0, 150)
        self.sat_slider.setValue(100)
        self.sat_slider.valueChanged.connect(
            lambda v: self.sat_label.setText(f"Saturation: {v}%")
        )
        self.progress = QProgressBar()
        self.status_label = QLabel("Status: Ready")
        self.btn_start = QPushButton("Start")
        self.btn_start.clicked.connect(self.start_conversion)

        # Layout
        v = QVBoxLayout()
        v.addWidget(self.list_widget)
        h = QHBoxLayout()
        h.addWidget(self.btn_add)
        h.addWidget(self.btn_remove)
        h.addWidget(self.btn_output)
        v.addLayout(h)
        v2 = QHBoxLayout()
        v2.addWidget(self.sat_label)
        v2.addWidget(self.sat_slider)
        v.addLayout(v2)
        v.addWidget(self.progress)
        v.addWidget(self.status_label)
        v.addWidget(self.btn_start)
        self.setLayout(v)
        self.setAcceptDrops(True)

    # ───────────── File ops ─────────────
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select video files", "", "Video Files (*.mp4 *.mov *.mkv *.avi *.webm)"
        )
        if not files:
            return
        for f in files:
            if len(self.input_files) >= 20:
                QMessageBox.information(self, "Limit", "You can only add up to 20 files.")
                break
            if f not in self.input_files:
                self.input_files.append(f)
                self.list_widget.addItem(f)

    def remove_selected(self):
        for it in self.list_widget.selectedItems():
            txt = it.text()
            if txt in self.input_files:
                self.input_files.remove(txt)
            self.list_widget.takeItem(self.list_widget.row(it))

    def select_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select output folder")
        if folder:
            self.output_folder = folder
            self.status_label.setText(f"Output: {folder}")

    # ───────────── Conversion ─────────────
    def start_conversion(self):
        if not self.input_files or not self.output_folder:
            QMessageBox.warning(self, "Missing info", "Add files and select output folder")
            return
        for f in list(self.input_files):
            out = str(Path(self.output_folder) / (Path(f).stem + "_converted.mp4"))
            worker = FFmpegWorker(f, out, self.sat_slider.value() / 100.0)
            worker.progress_changed.connect(self.progress.setValue)
            worker.finished_ok.connect(lambda: self._on_worker_finished(worker))
            worker.error_occurred.connect(lambda e: self._on_worker_error(worker, e))
            self.workers.append(worker)
            worker.start()
        self.status_label.setText("Status: Processing...")

    def _on_worker_finished(self, worker):
        log(f"Finished {getattr(worker, 'input_path', '')}")
        self.workers = [w for w in self.workers if w.isRunning()]
        if not self.workers:
            self.status_label.setText("Status: All done")
            QMessageBox.information(self, "Done", "All conversions finished")

    def _on_worker_error(self, worker, err):
        log("Worker error: " + str(err))
        QMessageBox.critical(self, "Error", str(err))
        self.workers = [w for w in self.workers if w.isRunning()]

    # ───────────── Drag & Drop ─────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    def dropEvent(self, event):
        for u in event.mimeData().urls():
            f = u.toLocalFile()
            if f.lower().endswith((".mp4", ".mov", ".mkv", ".avi", ".webm")) and f not in self.input_files:
                if len(self.input_files) < 20:
                    self.input_files.append(f)
                    self.list_widget.addItem(f)

    def closeEvent(self, ev):
        for w in list(self.workers):
            try:
                w.wait(30000)
            except Exception:
                pass
        return super().closeEvent(ev)

# ────────────────────────────────
# App entry
# ────────────────────────────────
def main():
    try:
        app = QApplication(sys.argv)
        w = VideoColorConverterApp()
        w.show()
        log("App started")
        rv = app.exec_()
        log("App exited with " + str(rv))
        return rv
    except Exception as e:
        tb = traceback.format_exc()
        log("Fatal: " + str(e)); log(tb)
        try:
            QMessageBox.critical(None, "Fatal", f"Fatal error: {e}\nSee app_log.txt for details.")
        except Exception:
            print("Fatal and cannot show QMessageBox:", e)
        return 1

if __name__ == "__main__":
    sys.exit(main())
