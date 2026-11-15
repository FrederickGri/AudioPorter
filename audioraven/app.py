"""Small native desktop interface for downloading a complete Bilibili folder."""
from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListView, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTableWidget,
    QStyledItemDelegate, QTableWidgetItem, QVBoxLayout, QWidget,
)

from audioraven.backend import BatchRunner, Settings, Track
from audioraven import DISPLAY_NAME, __version__

PLATFORM = sys.platform

STYLE = """
QMainWindow, QWidget#root { background: #f4f6fa; color: #172b45; }
QWidget { font-size: 13px; color: #172b45; }
QLabel#eyebrow { color: #087f85; font-weight: 700; font-size: 11px; }
QLabel#title { font-size: 28px; font-weight: 700; }
QLabel#subtitle, QLabel#muted { color: #52657c; }
QFrame#card { background: white; border: 1px solid #dfe5ee; border-radius: 12px; }
QLabel#field { font-weight: 600; }
QLineEdit, QComboBox, QSpinBox { background: white; border: 1px solid #bbc8d8; border-radius: 6px; padding: 8px; selection-background-color: #c4eeef; selection-color: #172b45; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid #087f85; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { background: #f1f3f7; color: #7b899b; }
QComboBox QAbstractItemView { background: #ffffff; color: #172b45; border: 1px solid #9baec3; selection-background-color: #087f85; selection-color: #ffffff; outline: 0; padding: 4px; }
QComboBox QAbstractItemView::item { min-height: 30px; padding: 5px 10px; color: #172b45; background: #ffffff; }
QComboBox QAbstractItemView::item:selected { background: #087f85; color: #ffffff; }
QToolTip { background: #ffffff; color: #172b45; border: 1px solid #9baec3; padding: 6px; }
QPushButton { background: white; border: 1px solid #b8c6d6; border-radius: 6px; padding: 9px 15px; font-weight: 600; }
QPushButton:hover { background: #eef6f7; border-color: #087f85; }
QPushButton:pressed { background: #deeff0; }
QPushButton#primary { background: #087f85; color: white; border: 1px solid #087f85; }
QPushButton#primary:hover { background: #06696e; }
QPushButton#primary:disabled { color: #8090a3; background: #edf0f5; border-color: #d9e0ea; }
QPushButton:disabled { color: #8090a3; background: #edf0f5; border-color: #d9e0ea; }
QPushButton#link { border: none; background: transparent; color: #086e76; padding: 4px 0px; text-align: left; }
QLabel#statValue { font-size: 24px; font-weight: 700; }
QLabel#statLabel { font-size: 12px; color: #52657c; }
QTableWidget { background: white; alternate-background-color: #f8fafc; border: 1px solid #dfe5ee; border-radius: 8px; gridline-color: #edf0f5; selection-background-color: #dceff0; selection-color: #172b45; }
QHeaderView::section { background: #edf2f7; color: #42566e; border: none; border-bottom: 1px solid #dfe5ee; padding: 10px 8px; font-weight: 600; }
QProgressBar { background: #e3e9f1; border: none; border-radius: 4px; min-height: 8px; max-height: 8px; }
QProgressBar::chunk { background: #087f85; border-radius: 4px; }
QPlainTextEdit { background: #f8fafc; border: 1px solid #dfe5ee; border-radius: 6px; font-size: 12px; padding: 6px; }
"""


def apply_theme(app):
    """Keep popup, checkbox, and disabled colors consistent in macOS dark mode."""
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#f4f6fa", QPalette.ColorRole.WindowText: "#172b45",
        QPalette.ColorRole.Base: "#ffffff", QPalette.ColorRole.AlternateBase: "#f8fafc",
        QPalette.ColorRole.Text: "#172b45", QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: "#172b45", QPalette.ColorRole.Highlight: "#087f85",
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.PlaceholderText: "#65788f",
        QPalette.ColorRole.ToolTipBase: "#ffffff", QPalette.ColorRole.ToolTipText: "#172b45",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#718198"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Segoe UI" if PLATFORM == "win32" else "Helvetica Neue", 13))


def readable_combo():
    combo = QComboBox()
    # Use the styled list delegate rather than a native menu delegate whose
    # colors can come from a different system appearance than the main window.
    combo.setView(QListView(combo))
    combo.setItemDelegate(QStyledItemDelegate(combo))
    return combo


class Job(QThread):
    event = Signal(dict)
    loaded = Signal(object)
    problem = Signal(str)

    def __init__(self, settings: Settings, tracks=None, preview=False, add_to_music=False):
        super().__init__()
        self.runner = BatchRunner(settings, self.on_event)
        self.settings = settings
        self.tracks = tracks
        self.preview = preview
        self.add_to_music = add_to_music and PLATFORM == "darwin"
        self.music_cancel = threading.Event()
        self.importer = None
        self.imported = 0
        self.import_errors = 0
        self.music_paused = False
        self._music_pool = None
        self._music_pool_lock = threading.Lock()

    def cancel(self):
        self.music_cancel.set()
        self.runner.cancel()

    def on_event(self, event):
        if event.get("type") == "finished":
            self.wait_for_music()
            event = {**event, "music_enabled": self.add_to_music, "imported": self.imported, "import_errors": self.import_errors}
        self.event.emit(event)
        if (self.add_to_music and not self.music_cancel.is_set()
                and event.get("type") == "status"
                and event.get("status") in ("completed", "skipped") and event.get("files")):
            # Music imports share one manifest and one app. Serialize them on a
            # dedicated thread without occupying any parallel download slots.
            with self._music_pool_lock:
                if self._music_pool is None:
                    self._music_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="AudioRaven-Music")
                self._music_pool.submit(self.import_to_music, dict(event))

    def wait_for_music(self):
        with self._music_pool_lock:
            pool, self._music_pool = self._music_pool, None
        if pool is not None:
            self.event.emit({"type": "log", "message": "Downloads finished; waiting for queued Apple Music imports…"})
            pool.shutdown(wait=True)

    def import_to_music(self, event):
        if self.music_paused or self.music_cancel.is_set():
            return
        try:
            if self.importer is None:
                from audioraven.music import MusicImporter
                self.importer = MusicImporter(self.settings.destination)
            self.event.emit({"type": "log", "message": "Adding completed audio to Apple Music…"})
            result = self.importer.import_files(event["files"], cancel_event=self.music_cancel)
            count = result.get("imported", 0) + result.get("already_imported", 0)
            self.imported += count
            self.event.emit({"type": "music", "index": event["index"], "message": f"{count} audio file(s) available in the AudioRaven playlist."})
        except Exception as exc:
            self.import_errors += 1
            self.music_paused = True
            self.event.emit({"type": "music_error", "index": event["index"], "message": f"Audio saved; Apple Music import failed: {exc}. Import is paused for this batch; downloads will continue."})

    def run(self):
        try:
            tracks = self.tracks
            if tracks is None:
                tracks = self.runner.scan()
                self.loaded.emit(tracks)
            if not self.preview:
                self.runner.download(tracks)
        except Exception as exc:
            self.problem.emit(str(exc))
        finally:
            self.wait_for_music()


class Window(QMainWindow):
    def __init__(self, preferences=None):
        super().__init__()
        self.setWindowTitle(f"{DISPLAY_NAME} {__version__} — Collection audio downloader")
        self.resize(1060, 880)
        self.setMinimumSize(920, 760)
        self.prefs = preferences if preferences is not None else QSettings("AudioRaven", "AudioRaven")
        if preferences is None and not self.prefs.allKeys():
            previous = QSettings('BiliSong', 'BiliSong')
            for key in previous.allKeys():
                self.prefs.setValue(key, previous.value(key))
        self.tracks: list[Track] = []
        self.row_map: list[int] = []
        self.statuses: dict[int, str] = {}
        self.loaded_url = ""
        self.job = None
        self.stopping = False
        self.editables = []
        root = QWidget(objectName="root")
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(14)

        top = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(5)
        heading.addWidget(QLabel("YOUR COLLECTION, READY TO LISTEN", objectName="eyebrow"))
        heading.addWidget(QLabel(DISPLAY_NAME, objectName="title"))
        heading.addWidget(QLabel("Paste a Bilibili folder link. Save every available song in one batch.", objectName="subtitle"))
        top.addLayout(heading)
        top.addStretch()
        self.open_folder = QPushButton("Open destination ↗")
        self.open_folder.clicked.connect(self.reveal_destination)
        top.addWidget(self.open_folder, alignment=Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(top)

        card = QFrame(objectName="card")
        form = QVBoxLayout(card)
        form.setContentsMargins(18, 16, 18, 14)
        form.setSpacing(9)
        form.addWidget(QLabel("Bilibili favorites or collection link", objectName="field"))
        self.url = QLineEdit(str(self.prefs.value("url", "")))
        self.url.setPlaceholderText("https://space.bilibili.com/…/favlist?fid=…")
        self.url.setClearButtonEnabled(True)
        self.url.setAccessibleName("Collection URL")
        self.url.textChanged.connect(self.url_changed)
        form.addWidget(self.url)

        labels = QHBoxLayout()
        labels.addWidget(QLabel("Save audio to", objectName="field"))
        labels.addStretch()
        labels.addWidget(QLabel("Audio format", objectName="field"))
        form.addLayout(labels)
        destination_row = QHBoxLayout()
        music_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)
        self.destination = QLineEdit(str(self.prefs.value("destination", str(Path(music_dir or Path.home()) / "AudioRaven"))))
        self.destination.setAccessibleName("Destination folder")
        self.browse = QPushButton("Choose folder…")
        self.browse.clicked.connect(self.choose_destination)
        self.format = readable_combo()
        self.format.addItems(["MP3 · compatible", "M4A · AAC audio"])
        self.format.setCurrentIndex(1 if self.prefs.value("audio_format") == "m4a" else 0)
        self.format.setMinimumWidth(190)
        self.format.setAccessibleName("Audio format")
        destination_row.addWidget(self.destination, 1)
        destination_row.addWidget(self.browse)
        destination_row.addWidget(self.format)
        form.addLayout(destination_row)

        quality_row = QHBoxLayout()
        quality_row.addWidget(QLabel("Output quality", objectName="field"))
        self.quality = readable_combo()
        self.quality.setAccessibleName("Output audio quality")
        self._mp3_quality = str(self.prefs.value("audio_quality", "best"))
        quality_row.addWidget(self.quality, 1)
        quality_row.addSpacing(14)
        quality_row.addWidget(QLabel("Parallel downloads", objectName="field"))
        self.parallel = self.spin(1, 6, int(self.prefs.value("parallel_downloads", 3)))
        self.parallel.setAccessibleName("Parallel downloads")
        self.parallel.setMinimumWidth(90)
        self.parallel.setToolTip("Number of songs downloaded at once. Each has its own retry and timeout limits.")
        quality_row.addWidget(self.parallel)
        form.addLayout(quality_row)
        self.quality_note = QLabel(objectName="muted")
        self.quality_note.setWordWrap(True)
        form.addWidget(self.quality_note)
        self.format.currentIndexChanged.connect(self.update_quality_options)
        self.update_quality_options()

        self.add_music = QCheckBox("Add completed songs to Apple Music → AudioRaven playlist")
        self.add_music.setChecked(PLATFORM == "darwin" and str(self.prefs.value("add_to_music", "true")).lower() == "true")
        self.add_music.setVisible(PLATFORM == "darwin")
        self.add_music.setToolTip("Imports each saved audio file immediately. macOS may ask to allow control of Music. Does not require an Apple Music subscription.")
        form.addWidget(self.add_music)

        self.options_button = QPushButton("▸  Account access && retry settings", objectName="link")
        self.options_button.setCheckable(True)
        self.options_button.toggled.connect(self.toggle_options)
        form.addWidget(self.options_button)
        self.options = QWidget()
        option_layout = QGridLayout(self.options)
        option_layout.setContentsMargins(0, 6, 0, 0)
        option_layout.setHorizontalSpacing(14)
        self.browser = readable_combo()
        for label, value in [("Public folder · no login", ""), ("Chrome login", "chrome"), ("Safari login", "safari"), ("Firefox login", "firefox"), ("Edge login", "edge"), ("Cookies file…", "file")]:
            if value == "safari" and PLATFORM != "darwin":
                continue
            self.browser.addItem(label, value)
        self.browser.setCurrentIndex(max(0, self.browser.findData(self.prefs.value("browser", ""))))
        self.browser.currentIndexChanged.connect(self.cookie_controls)
        self.retries = self.spin(0, 10, int(self.prefs.value("retries", 3)))
        self.timeout = self.spin(5, 180, int(self.prefs.value("socket_timeout", 30)), " s")
        self.deadline = self.spin(1, 240, int(self.prefs.value("item_minutes", 15)), " min")
        for col, (name, widget) in enumerate([("Account access", self.browser), ("Retries per item", self.retries), ("Network timeout", self.timeout), ("Time limit per item", self.deadline)]):
            option_layout.addWidget(QLabel(name, objectName="field"), 0, col)
            option_layout.addWidget(widget, 1, col)
        self.cookies = QLineEdit(str(self.prefs.value("cookie_file", "")))
        self.cookies.setPlaceholderText("Netscape cookies.txt file")
        self.cookies.setAccessibleName("Cookies file path")
        self.cookie_browse = QPushButton("Choose cookies…")
        self.cookie_browse.clicked.connect(self.choose_cookies)
        option_layout.addWidget(self.cookies, 2, 0, 1, 3)
        option_layout.addWidget(self.cookie_browse, 2, 3)
        note = QLabel("For private folders, choose a browser where you’re signed in to Bilibili, or a cookies.txt file.\nIf browser cookies are locked or cannot be decrypted, use an exported cookies file. No password is stored in this app.", objectName="muted")
        note.setWordWrap(True)
        option_layout.addWidget(note, 3, 0, 1, 4)
        self.options.setVisible(False)
        form.addWidget(self.options)
        self.cookie_controls()
        layout.addWidget(card)
        self.editables = [self.url, self.destination, self.browse, self.format, self.quality, self.parallel, self.browser, self.retries, self.timeout, self.deadline, self.cookies, self.cookie_browse, self.add_music]

        stats = QHBoxLayout()
        self.total_value = self.stat(stats, "FOLDER ITEMS", "—")
        self.done_value = self.stat(stats, "COMPLETED", "0")
        self.failed_value = self.stat(stats, "NEED RETRY", "0")
        layout.addLayout(stats)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Download queue", objectName="field"))
        toolbar.addStretch()
        self.preview = QPushButton("Preview folder")
        self.preview.clicked.connect(lambda: self.start(preview=True))
        self.retry = QPushButton("Retry failed")
        self.retry.setEnabled(False)
        self.retry.clicked.connect(self.retry_failed)
        self.start_button = QPushButton("Download entire folder", objectName="primary")
        self.start_button.clicked.connect(self.start)
        self.cancel = QPushButton("Stop")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.stop)
        for button in [self.preview, self.retry, self.start_button, self.cancel]:
            toolbar.addWidget(button)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "Song / video", "Status", "Progress"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(37)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 48)
        self.table.setColumnWidth(2, 145)
        self.table.setColumnWidth(3, 120)
        self.table.setMinimumHeight(150)
        layout.addWidget(self.table, 1)
        self.state = QLabel("Ready — choose a folder link and a destination.", objectName="muted")
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.log_toggle = QPushButton("▸  Activity log", objectName="link")
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self.toggle_log)
        layout.addWidget(self.log_toggle)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setFixedHeight(110)
        self.log.hide()
        layout.addWidget(self.log)
        self.url_changed()

    @staticmethod
    def spin(low, high, value, suffix=""):
        widget = QSpinBox()
        widget.setRange(low, high)
        widget.setValue(value)
        widget.setSuffix(suffix)
        return widget

    @staticmethod
    def stat(parent, label, value):
        card = QFrame(objectName="card")
        box = QHBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        number = QLabel(value, objectName="statValue")
        box.addWidget(number)
        box.addWidget(QLabel(label, objectName="statLabel"))
        box.addStretch()
        parent.addWidget(card)
        return number

    def toggle_options(self, checked):
        self.options.setVisible(checked)
        self.options_button.setText(("▾" if checked else "▸") + "  Account access && retry settings")
        if checked and self.height() < 960:
            self.resize(self.width(), min(960, self.screen().availableGeometry().height() - 40))

    def toggle_log(self, checked):
        self.log.setVisible(checked)
        self.log_toggle.setText(("▾" if checked else "▸") + "  Activity log")

    def cookie_controls(self):
        visible = self.browser.currentData() == "file"
        self.cookies.setVisible(visible)
        self.cookie_browse.setVisible(visible)

    def update_quality_options(self):
        if self.quality.currentData() in {"best", "320", "256", "192", "128"}:
            self._mp3_quality = self.quality.currentData()
        self.quality.clear()
        if self.format.currentIndex() == 0:
            for label, value in [("Best quality · VBR V0", "best"), ("320 kbps", "320"), ("256 kbps", "256"), ("192 kbps", "192"), ("128 kbps · smaller files", "128")]:
                self.quality.addItem(label, value)
            self.quality.setCurrentIndex(max(0, self.quality.findData(self._mp3_quality)))
            self.quality_note.setText("Uses the best source available to your account. Higher output bitrate cannot restore missing detail.")
        else:
            self.quality.addItem("Source AAC / 320 kbps fallback", "source")
            self.quality_note.setText("Uses the best available source. AAC is copied without re-encoding; other codecs convert to AAC at 320 kbps.")
        self.quality.setEnabled(self.format.currentIndex() == 0 and self.job is None)

    def choose_destination(self):
        path = QFileDialog.getExistingDirectory(self, "Choose download folder", self.destination.text())
        if path:
            self.destination.setText(path)

    def choose_cookies(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose Netscape cookies file", str(Path.home()), "Text files (*.txt);;All files (*)")
        if path:
            self.cookies.setText(path)

    def reveal_destination(self):
        path = Path(self.destination.text()).expanduser()
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self.state.setText("The destination folder will be created when you start a download.")

    def settings(self):
        if not self.destination.text().strip():
            raise ValueError("Choose a destination folder first.")
        browser = self.browser.currentData()
        if browser == "file" and not Path(self.cookies.text()).expanduser().is_file():
            raise ValueError("Choose an existing cookies.txt file, or select another account-access option.")
        settings = Settings(
            url=self.url.text().strip(), destination=str(Path(self.destination.text()).expanduser()),
            audio_format="mp3" if self.format.currentIndex() == 0 else "m4a",
            retries=self.retries.value(), socket_timeout=self.timeout.value(),
            item_timeout=self.deadline.value() * 60,
            cookie_file=str(Path(self.cookies.text()).expanduser()) if browser == "file" else "",
            browser=browser if browser != "file" else "",
            parallel_downloads=self.parallel.value(),
            audio_quality=self.quality.currentData() if self.format.currentIndex() == 0 else self._mp3_quality,
        )
        for key, value in vars(settings).items():
            if key not in ("browser", "cookie_file"):
                self.prefs.setValue(key, value)
        self.prefs.setValue("browser", browser)
        self.prefs.setValue("cookie_file", self.cookies.text())
        self.prefs.setValue("item_minutes", self.deadline.value())
        self.prefs.setValue("add_to_music", self.add_music.isChecked())
        return settings

    def url_changed(self):
        if not hasattr(self, "start_button") or self.job:
            return
        ready = bool(self.url.text().strip())
        self.start_button.setEnabled(ready)
        self.preview.setEnabled(ready)
        self.retry.setEnabled(ready and self.loaded_url == self.url.text().strip() and any(s == "failed" for s in self.statuses.values()))

    def start(self, checked=False, preview=False, retry_rows=None):
        if self.job:
            return
        try:
            settings = self.settings()
        except (ValueError, RuntimeError) as exc:
            self.show_problem(str(exc))
            return
        self.stopping = False
        self.log.clear()
        if retry_rows is not None:
            self.row_map = retry_rows
            tracks = [self.tracks[row] for row in retry_rows]
        else:
            self.tracks = []
            self.statuses = {}
            self.table.setRowCount(0)
            self.row_map = []
            tracks = None
            self.update_stats()
        for row in self.row_map:
            self.set_status(row, "queued")
            self.table.item(row, 3).setText("—")
        self.job = Job(settings, tracks, preview, self.add_music.isChecked())
        self.job.loaded.connect(self.load_tracks)
        self.job.event.connect(self.handle_event)
        self.job.problem.connect(self.show_problem)
        self.job.finished.connect(self.job_finished)
        self.busy(True)
        self.state.setText("Reading every item in the folder…" if tracks is None else "Starting audio downloads…")
        self.progress.setRange(0, 0)
        self.job.start()

    def busy(self, active):
        for widget in self.editables:
            widget.setEnabled(not active)
        for button in [self.start_button, self.preview, self.retry]:
            button.setEnabled(not active)
        self.cancel.setEnabled(active)
        if not active:
            self.quality.setEnabled(self.format.currentIndex() == 0)
            self.url_changed()

    def load_tracks(self, tracks):
        self.tracks = tracks
        self.loaded_url = self.url.text().strip()
        self.row_map = list(range(len(tracks)))
        self.table.setRowCount(len(tracks))
        for row, track in enumerate(tracks):
            for col, value in enumerate([str(row + 1), track.title, "Queued", "—"]):
                item = QTableWidgetItem(value)
                if col == 1:
                    item.setToolTip(track.title)
                self.table.setItem(row, col, item)
            self.statuses[row] = "queued"
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.state.setText(f"Found {len(tracks)} folder items. Multi-part videos may produce more than one audio file.")
        self.update_stats()

    def set_status(self, row, status, message=""):
        self.statuses[row] = status
        item = self.table.item(row, 2)
        if item is None:
            return
        labels = {"queued": "Queued", "downloading": "Downloading", "retrying": "Retrying…", "completed": "Completed", "failed": "Failed", "cancelled": "Stopped", "skipped": "Already saved", "converting": "Converting"}
        colors = {"completed": "#08756a", "skipped": "#08756a", "failed": "#b33e29", "retrying": "#855900"}
        item.setText(labels.get(status, status.replace("_", " ").capitalize()))
        item.setForeground(QColor(colors.get(status, "#42566e")))
        item.setToolTip(message)
        self.update_stats()

    def update_stats(self):
        if not hasattr(self, "total_value"):
            return
        self.total_value.setText(str(len(self.tracks)) if self.tracks else "—")
        self.done_value.setText(str(sum(s in ("completed", "skipped") for s in self.statuses.values())))
        self.failed_value.setText(str(sum(s == "failed" for s in self.statuses.values())))

    def handle_event(self, event):
        kind = event.get("type")
        message = str(event.get("message", ""))
        if kind == "log":
            self.log.appendPlainText(message)
        elif kind in ("title", "music", "music_error"):
            index = event.get("index", -1)
            if not isinstance(index, int) or not 0 <= index < len(self.row_map):
                return
            row = self.row_map[index]
            if kind == "title":
                title = str(event.get("title", self.tracks[row].title))
                self.tracks[row].title = title
                self.table.item(row, 1).setText(title)
                self.table.item(row, 1).setToolTip(title)
            elif kind == "music":
                self.table.item(row, 2).setText("Saved + Music")
                self.table.item(row, 2).setToolTip(message)
            else:
                self.table.item(row, 2).setText("Saved · import failed")
                self.table.item(row, 2).setToolTip(message)
                self.log.appendPlainText(message)
                self.log_toggle.setChecked(True)
        elif kind in ("status", "progress"):
            index = event.get("index", -1)
            if not isinstance(index, int) or not 0 <= index < len(self.row_map):
                return
            row = self.row_map[index]
            if kind == "status":
                status = event.get("status", "queued")
                self.set_status(row, status, message)
                if status in ("completed", "skipped"):
                    self.table.item(row, 3).setText("100%")
                if message:
                    self.log.appendPlainText(f"{self.tracks[row].title}: {message}")
                active = sum(self.statuses.get(r) in ("downloading", "converting", "retrying") for r in self.row_map)
                finished_count = sum(self.statuses.get(r) in ("completed", "skipped", "failed", "cancelled") for r in self.row_map)
                self.state.setText(f"{active} active · {finished_count} of {len(self.row_map)} finished · {self.tracks[row].title[:70]}")
            else:
                percent = event.get("percent")
                if percent is not None:
                    self.table.item(row, 3).setText(f"{float(percent):.0f}%")
            finished = sum(self.statuses.get(r) in ("completed", "skipped", "failed", "cancelled") for r in self.row_map)
            self.progress.setRange(0, len(self.row_map))
            self.progress.setValue(finished)
        elif kind == "finished":
            count = event.get("completed", 0)
            failed = event.get("failed", 0)
            skipped = event.get("skipped", 0)
            if event.get("cancelled"):
                self.state.setText(f"Stopped. {count} completed, {skipped} already saved, {failed} failed. Start again to resume.")
            else:
                summary = f"Batch finished · {count} completed · {skipped} already saved · {failed} failed."
                if failed:
                    summary += " Use Retry failed to try those items again."
                if event.get("music_enabled"):
                    summary += f" {event.get('imported', 0)} audio files in Apple Music."
                    if event.get("import_errors"):
                        summary += " Some imports failed; see the activity log. Download again to retry imports."
                self.state.setText(summary)

    def show_problem(self, message):
        if self.stopping:
            self.state.setText("Stopped. You can start again to resume.")
            return
        self.state.setText("Could not finish: " + message[:220])
        self.log.appendPlainText(message)
        self.log_toggle.setChecked(True)

    def job_finished(self):
        old_job = self.job
        self.job = None
        if old_job:
            old_job.deleteLater()
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        self.busy(False)

    def retry_failed(self):
        rows = [row for row, status in self.statuses.items() if status == "failed"]
        if rows:
            self.start(retry_rows=rows)

    def stop(self):
        if self.job:
            self.stopping = True
            self.cancel.setEnabled(False)
            self.state.setText("Stopping all active downloads…")
            self.job.cancel()

    def closeEvent(self, event):
        if self.job and self.job.isRunning():
            self.stop()
            self.state.setText("Stopping safely… Close the window again once the download has stopped.")
            event.ignore()
            return
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AudioRaven")
    app.setApplicationDisplayName(DISPLAY_NAME)
    apply_theme(app)
    window = Window()
    window.show()
    sys.exit(app.exec())
