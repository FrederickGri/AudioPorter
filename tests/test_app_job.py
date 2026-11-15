"""Check the boundary between successful downloads and optional Music imports."""
from PySide6.QtCore import Qt
import threading
from audioraven.app import Job
from audioraven.backend import Settings
import pytest


@pytest.fixture(autouse=True)
def mac_music_platform(monkeypatch):
    monkeypatch.setattr('audioraven.app.PLATFORM', 'darwin')


class Importer:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def import_files(self, files, cancel_event=None):
        self.calls.append(files)
        if self.fail:
            raise RuntimeError("Automation denied")
        return {"imported": len(files), "already_imported": 0}


def job(tmp_path):
    result = Job(Settings("https://www.bilibili.com/list/ml123", str(tmp_path)), add_to_music=True)
    events = []
    result.event.connect(events.append, Qt.ConnectionType.DirectConnection)
    return result, events


def test_imports_completed_and_cached_files_immediately(tmp_path):
    runner, events = job(tmp_path)
    runner.importer = Importer()
    for index, status in enumerate(["completed", "skipped"]):
        runner.on_event({"type": "status", "status": status, "index": index, "files": [f"mp3/{index}.mp3"]})
    runner.on_event({"type": "finished", "completed": 1, "skipped": 1, "failed": 0})
    assert len(runner.importer.calls) == 2
    assert events[-1]["imported"] == 2
    assert events[-1]["import_errors"] == 0


def test_permission_failure_does_not_fail_download_or_repeat_prompts(tmp_path):
    runner, events = job(tmp_path)
    runner.importer = Importer(fail=True)
    for index in range(3):
        runner.on_event({"type": "status", "status": "completed", "index": index, "files": [f"mp3/{index}.mp3"]})
    runner.on_event({"type": "finished", "completed": 3, "failed": 0})
    assert len(runner.importer.calls) == 1
    assert events[-1]["completed"] == 3
    assert events[-1]["failed"] == 0
    assert events[-1]["import_errors"] == 1
    assert any(event["type"] == "music_error" for event in events)


def test_stop_prevents_any_further_music_import(tmp_path):
    runner, _ = job(tmp_path)
    runner.importer = Importer()
    runner.cancel()
    runner.on_event({"type": "status", "status": "completed", "index": 0, "files": ["mp3/song.mp3"]})
    assert runner.importer.calls == []


def test_music_is_serialized_without_blocking_download_completion(tmp_path):
    runner, events = job(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    calls = []

    class BlockingImporter:
        def import_files(self, files, cancel_event=None):
            calls.append(files)
            entered.set()
            assert release.wait(3)
            return {"imported": 1, "already_imported": 0}

    runner.importer = BlockingImporter()
    try:
        runner.on_event({"type": "status", "status": "completed", "index": 0, "files": ["mp3/0.mp3"]})
        assert entered.wait(2)
        runner.on_event({"type": "status", "status": "completed", "index": 1, "files": ["mp3/1.mp3"]})
        assert calls == [["mp3/0.mp3"]]
        assert any(e.get("index") == 1 and e["type"] == "status" for e in events)
    finally:
        release.set()
        runner.on_event({"type": "finished", "completed": 2, "failed": 0})
    assert calls == [["mp3/0.mp3"], ["mp3/1.mp3"]]
    assert events[-1]["imported"] == 2
