"""Platform boundaries and actual worker/converter-tree termination."""
import sys
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings

from audioporter.app import Job, Window, apply_theme
from audioporter.backend import BatchRunner, CancelledError, Settings, Track


def test_windows_ui_hides_mac_features_and_survives_busy_cycle(tmp_path, monkeypatch, qt_app):
    monkeypatch.setattr('audioporter.app.PLATFORM', 'win32')
    app = qt_app
    apply_theme(app)
    prefs = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    prefs.setValue('add_to_music', 'true')
    prefs.setValue('browser', 'safari')
    window = Window(prefs)
    try:
        window.show()
        app.processEvents()
        assert not window.add_music.isChecked()
        assert not window.add_music.isVisible()
        assert window.browser.findData('safari') == -1
        assert not Job(Settings('https://www.bilibili.com/video/BVTEST', str(tmp_path)),
                       add_to_music=True).add_to_music
        window.busy(True)
        window.busy(False)
        assert not window.add_music.isChecked()
        assert not window.add_music.isVisible()
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.skipif(sys.platform != 'win32', reason='Exercises real Windows Job Objects')
@pytest.mark.parametrize('cancel', [False, True])
def test_windows_timeout_and_stop_kill_converter_descendants(tmp_path, monkeypatch, cancel):
    from test_backend import assert_process_exited
    child_pid = tmp_path / 'converter.pid'
    child_script = "import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"
    worker_script = "import subprocess,sys,time; sys.stdin.readline(); subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); time.sleep(60)"
    runner = BatchRunner(Settings('https://www.bilibili.com/video/BVTEST', str(tmp_path),
                                  item_timeout=30 if cancel else 2), lambda e: None)
    monkeypatch.setattr(runner, '_worker_command', lambda: [sys.executable, '-c', worker_script, child_script, str(child_pid)])
    errors = []
    def run():
        try:
            runner._run_worker('download', Track('BVTEST', 'Synthetic', 'https://www.bilibili.com/video/BVTEST'))
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not child_pid.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert child_pid.exists()
        if cancel:
            runner.cancel()
        thread.join(timeout=8)
        assert not thread.is_alive()
        assert len(errors) == 1
        assert isinstance(errors[0], CancelledError if cancel else TimeoutError)
        assert_process_exited(int(child_pid.read_text()))
        assert not runner._processes
    finally:
        runner.cancel()
        thread.join(timeout=5)
