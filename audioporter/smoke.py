"""Offline checks of the actual packaged GUI, converter and worker protocol."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from . import __version__


def main(arguments: list[str]) -> int:
    if len(arguments) != 1:
        raise SystemExit('Usage: AudioPorter --smoke-test RESULT.json')
    result_file = Path(arguments[0]).resolve()
    result = {'version': __version__, 'ok': False}
    try:
        import imageio_ffmpeg
        from PySide6.QtCore import QSettings, QTimer
        from PySide6.QtWidgets import QApplication
        from .app import Window, apply_theme
        from .backend import BatchRunner, Settings
        with tempfile.TemporaryDirectory(prefix='audioporter-smoke-') as temporary:
            work = Path(temporary)
            app = QApplication.instance() or QApplication(['AudioPorter smoke test'])
            apply_theme(app)
            window = Window(QSettings(str(work / 'preferences.ini'), QSettings.Format.IniFormat))
            window.show()
            app.processEvents()
            if window.url.text() or window.cookies.text():
                raise RuntimeError('Smoke test did not start with clean preferences')
            if __import__('sys').platform == 'win32':
                assert not window.add_music.isChecked()
                assert not window.add_music.isVisible()
                assert window.browser.findData('safari') == -1
            window.destination.clear()
            window.destination.setPlaceholderText('Choose a download folder')
            app.processEvents()
            assert window.grab().save(str(work / 'window.png'))
            shutil.copyfile(work / 'window.png', result_file.with_suffix('.png'))
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            for codec, suffix in [('libmp3lame', 'mp3'), ('aac', 'm4a')]:
                output = work / ('synthetic.' + suffix)
                subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', 'sine=frequency=440:sample_rate=44100', '-t', '0.2', '-c:a', codec,
                    str(output)], check=True, capture_output=True, timeout=30)
                subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(output),
                    '-f', 'null', '-'], check=True, capture_output=True, timeout=30)
            runner = BatchRunner(Settings('https://www.bilibili.com/video/BVTEST', str(work / '音乐')),
                                 lambda event: None)
            try:
                runner._run_worker('offline-smoke')
            except RuntimeError as exc:
                if 'Unknown worker operation' not in str(exc):
                    raise
            else:
                raise RuntimeError('Worker protocol did not return the expected error')
            window.close()
            QTimer.singleShot(0, app.quit)
            app.exec()
            result.update(ok=True, gui=True, mp3=True, m4a=True, worker=True)
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    result_file.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return 0 if result['ok'] else 1
