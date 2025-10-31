import sys, os, shutil, subprocess, tempfile, hashlib
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QFileDialog,
    QVBoxLayout, QHBoxLayout, QSlider, QProgressBar, QMessageBox, QListWidget
)

APP_TITLE = "Video Color Converter (Preview Fixed)"

# ---------- Utilities ----------
def find_tool(name_win):
    """
    Find ffmpeg / ffprobe whether running from source or PyInstaller bundle.
    """
    # 1) _MEIPASS (PyInstaller onefile)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cand = Path(meipass) / name_win
        if cand.exists():
            return str(cand)

    # 2) same dir as exe/py
    base = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    cand = base / name_win
    if cand.exists():
        return str(cand)

    # 3) PATH
    which = shutil.which(name_win)
    if which:
        return which

    return name_win  # let it fail with clear message

def windows_startupinfo():
    # Hide console window of ffmpeg on Windows
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return si
    return None

# ---------- Worker: one file convert ----------
class FFmpegWorker(QThread):
    progress = pyqtSignal(int)       # 0..100
    done = pyqtSignal(str)           # output path
    error = pyqtSignal(str)          # message

    def __init__(self, input_path, output_path, saturation):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.saturation = saturation

    def run(self):
        try:
            ffmpeg = find_tool("ffmpeg.exe")
            ffprobe = find_tool("ffprobe.exe")

            # --- bitrate (original) ---
            p = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=bit_rate",
                 "-of", "default=nokey=1:noprint_wrappers=1", self.input_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                startupinfo=windows_startupinfo()
            )
            bitrate = p.stdout.strip() or "12M"

            # --- duration ---
            d = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nokey=1:noprint_wrappers=1", self.input_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                startupinfo=windows_startupinfo()
            )
            try:
                duration = float(d.stdout.strip())
            except Exception:
                duration = 0.0

            # --- filter ---
            vf = f"eq=saturation={self.saturation}"
            if self.saturation <= 0:
                vf += ",format=yuv420p"

            cmd = [
                ffmpeg, "-y", "-i", self.input_path,
                "-vf", vf,
                "-b:v", bitrate, "-c:a", "copy",
                self.output_path
            ]

            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, startupinfo=windows_startupinfo()
            )

            import re
            t_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
            last = -1
            for line in proc.stderr:
                m = t_re.search(line)
                if m and duration > 0:
                    h, mm, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                    t = h*3600 + mm*60 + s
                    pct = max(0, min(100, int((t/duration)*100)))
                    if pct != last:
                        last = pct
                        self.progress.emit(pct)

            proc.wait()
            if proc.returncode == 0:
                self.progress.emit(100)
                self.done.emit(self.output_path)
            else:
                self.error.emit("FFmpeg failed (exit code {})".format(proc.returncode))

        except Exception as e:
            self.error.emit(str(e))

# ---------- Preview helper (debounced) ----------
class Previewer(QThread):
    ready = pyqtSignal(str)  # jpg path or "" on failure

    def __init__(self, video_path, saturation):
        super().__init__()
        self.video_path = video_path
        self.saturation = saturation

    def run(self):
        try:
            ffmpeg = find_tool("ffmpeg.exe")
            # cache file name by (path + sat)
            key = (Path(self.video_path).resolve().as_posix() + f"|{self.saturation:.3f}").encode("utf-8")
            fname = "preview_" + hashlib.md5(key).hexdigest() + ".jpg"
            outjpg = str(Path(tempfile.gettempdir()) / fname)

            vf = f"eq=saturation={self.saturation}"
            if self.saturation <= 0:
                vf += ",format=yuv420p"

            cmd = [ffmpeg, "-y", "-ss", "00:00:01", "-i", self.video_path,
                   "-frames:v", "1", "-vf", vf, outjpg]

            subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=4, startupinfo=windows_startupinfo()
            )

            if os.path.exists(outjpg) and os.path.getsize(outjpg) > 500:
                self.ready.emit(outjpg)
            else:
                self.ready.emit("")
        except Exception:
            self.ready.emit("")

# ---------- Main App ----------
class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setMinimumWidth(780)
        try:
            self.setWindowIcon(QIcon(str(Path(__file__).with_name("icon.ico"))))
        except Exception:
            pass

        self.files = []
        self.output_dir = ""
        self.workers = []         # keep references
        self.queue = []           # files to process
        self.current_worker = None

        # --- UI ---
        self.preview_label = QLabel("Preview")
        self.preview_label.setFixedHeight(220)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background:#1c1c1c; color:#ddd;")

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self.update_preview_debounced)

        self.btn_add = QPushButton("Add Videos")
        self.btn_add.clicked.connect(self.add_files)

        self.btn_remove = QPushButton("Remove Selected")
        self.btn_remove.clicked.connect(self.remove_selected)

        self.btn_output = QPushButton("Select Output Folder")
        self.btn_output.clicked.connect(self.choose_output)

        self.s_label = QLabel("Saturation: 100%")
        self.s_slider = QSlider(Qt.Horizontal)
        self.s_slider.setRange(0, 150)
        self.s_slider.setValue(100)
        self.s_slider.valueChanged.connect(self.update_preview_debounced)

        self.progress = QProgressBar()
        self.status = QLabel("Status: Ready")

        self.btn_start = QPushButton("Start Convert")
        self.btn_start.clicked.connect(self.start_queue)

        # layout
        top = QVBoxLayout()
        top.addWidget(self.preview_label)
        top.addWidget(self.list)

        row_btn = QHBoxLayout()
        row_btn.addWidget(self.btn_add)
        row_btn.addWidget(self.btn_remove)
        row_btn.addWidget(self.btn_output)
        top.addLayout(row_btn)

        row_sat = QHBoxLayout()
        row_sat.addWidget(self.s_label)
        row_sat.addWidget(self.s_slider)
        top.addLayout(row_sat)

        top.addWidget(self.progress)
        top.addWidget(self.status)
        top.addWidget(self.btn_start)
        self.setLayout(top)

        # drag & drop
        self.setAcceptDrops(True)

        # debounce timer for preview
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self.update_preview_now)

        self._preview_thread = None

    # ----- Drag & Drop -----
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        added = False
        for u in e.mimeData().urls():
            f = u.toLocalFile()
            if f.lower().endswith((".mp4",".mov",".mkv",".avi",".webm")) and f not in self.files:
                self.files.append(f)
                self.list.addItem(f)
                added = True
        if added:
            if self.list.currentRow() < 0:
                self.list.setCurrentRow(0)
            self.update_preview_debounced()

    # ----- Buttons -----
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select Videos", "",
                                                "Videos (*.mp4 *.mov *.mkv *.avi *.webm)")
        if not files:
            return
        for f in files:
            if f not in self.files:
                self.files.append(f)
                self.list.addItem(f)
        if self.list.currentRow() < 0 and self.files:
            self.list.setCurrentRow(0)
        self.update_preview_debounced()

    def remove_selected(self):
        for item in self.list.selectedItems():
            txt = item.text()
            if txt in self.files:
                self.files.remove(txt)
            self.list.takeItem(self.list.row(item))
        self.update_preview_debounced()

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_dir = folder
            self.status.setText(f"Output: {folder}")

    # ----- Preview (debounced) -----
    def update_preview_debounced(self):
        self.s_label.setText(f"Saturation: {self.s_slider.value()}%")
        self._debounce.start(200)

    def update_preview_now(self):
        current = self.list.currentItem()
        if not current:
            self.preview_label.setText("Select a file to preview")
            self.preview_label.setPixmap(QPixmap())
            return

        video = current.text()
        sat = self.s_slider.value() / 100.0

        # kill previous preview thread if still running
        if self._preview_thread and self._preview_thread.isRunning():
            self._preview_thread.terminate()
            self._preview_thread.wait()

        self.preview_label.setText("Generating preview…")
        self.preview_label.setPixmap(QPixmap())

        self._preview_thread = Previewer(video, sat)
        self._preview_thread.ready.connect(self._on_preview_ready)
        self._preview_thread.start()

    def _on_preview_ready(self, jpg_path):
        if jpg_path:
            pix = QPixmap(jpg_path)
            if not pix.isNull():
                self.preview_label.setPixmap(
                    pix.scaled(self.preview_label.width(), 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                return
        self.preview_label.setText("Preview unavailable")

    # ----- Queue conversion (one-by-one) -----
    def start_queue(self):
        if not self.files or not self.output_dir:
            QMessageBox.warning(self, "Missing info", "Add files + select output folder")
            return

        self.queue = list(self.files)
        self.progress.setValue(0)
        self.done_count = 0
        self.status.setText("Processing…")
        self.btn_start.setEnabled(False)
        self.btn_add.setEnabled(False)
        self.btn_remove.setEnabled(False)
        self.btn_output.setEnabled(False)

        self._run_next()

    def _run_next(self):
        if not self.queue:
            self.btn_start.setEnabled(True)
            self.btn_add.setEnabled(True)
            self.btn_remove.setEnabled(True)
            self.btn_output.setEnabled(True)
            self.status.setText("Completed")
            QMessageBox.information(self, "Done", "✅ All files converted.")
            return

        f = self.queue.pop(0)
        out = str(Path(self.output_dir) / (Path(f).stem + "_converted.mp4"))
        sat = self.s_slider.value() / 100.0

        worker = FFmpegWorker(f, out, sat)
        self.workers.append(worker)  # keep reference
        self.current_worker = worker

        worker.progress.connect(self.progress.setValue)
        worker.done.connect(self._worker_done)
        worker.error.connect(self._worker_error)
        worker.start()
        self.status.setText(f"Processing: {Path(f).name}")

    def _worker_done(self, _out):
        self.done_count += 1
        self._run_next()

    def _worker_error(self, msg):
        QMessageBox.critical(self, "Error", msg)
        # continue with next file
        self._run_next()

def main():
    app = QApplication(sys.argv)
    w = App()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
