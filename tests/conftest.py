"""Use an isolated, offscreen Qt application for automated UI tests."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest


@pytest.fixture(scope='session')
def qt_app():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(['BiliSong tests'])
    yield app
    QTimer.singleShot(0, app.quit)
    app.exec()
