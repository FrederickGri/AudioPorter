import hashlib
import json
import os
import sys
import threading
import time

import pytest
from yt_dlp import YoutubeDL

from audioraven.backend import BatchRunner, Settings, Track
from audioraven.worker import encoding_options
from test_backend import assert_process_exited


def make_tracks(count=7):
    return [Track(str(i), f"Song {i}", f"https://www.bilibili.com/video/BVtest{i}") for i in range(count)]


def test_parallel_workers_overlap_with_bounded_slots_and_safe_history(tmp_path, monkeypatch):
    runner = BatchRunner(Settings("https://www.bilibili.com/list/ml123", str(tmp_path), parallel_downloads=3), lambda event: None)
    first_three = threading.Barrier(3, timeout=3)
    lock = threading.Lock()
    active = peak = 0
    attempts = {}
    monkeypatch.setattr(runner._cancel, "wait", lambda delay: False)

    def worker(action, track, index):
        nonlocal active, peak
        with lock:
            attempts[index] = attempts.get(index, 0) + 1
            attempt = attempts[index]
            active += 1
            peak = max(peak, active)
        try:
            if index < 3 and attempt == 1:
                first_three.wait()
            if index == 0 and attempt == 1:
                raise TimeoutError("retry this item independently")
            time.sleep(0.015 * (3 - index % 3))
            name = f"{index}.mp3"
            (tmp_path / name).write_bytes(b"test output")
            return {"files": [name]}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(runner, "_run_worker", worker)
    runner.download(make_tracks())
    assert peak == 3
    assert attempts == {0: 2, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1}
    history = json.loads((tmp_path / ".audioraven-completed.json").read_text())
    report = json.loads((tmp_path / ".audioraven-report.json").read_text())
    assert len(history) == report["completed"] == 7
    assert report["failed"] == 0
    assert [r["id"] for r in report["entries"]] == [str(i) for i in range(7)]
    assert all(r["status"] == "completed" for r in report["entries"])


def test_cancel_kills_every_parallel_process_and_never_starts_pending_items(tmp_path, monkeypatch):
    events = []
    runner = BatchRunner(Settings("https://www.bilibili.com/list/ml123", str(tmp_path), parallel_downloads=3), events.append)
    script = "import os,sys,json,time; from pathlib import Path; c=json.loads(sys.stdin.readline()); Path(sys.argv[1],c['track']['id']+'.pid').write_text(str(os.getpid())); time.sleep(30)"
    monkeypatch.setattr(runner, "_worker_command", lambda: [sys.executable, "-c", script, str(tmp_path)])
    errors = []

    def run():
        try:
            runner.download(make_tracks())
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        deadline = time.monotonic() + 4
        while len(list(tmp_path.glob("*.pid"))) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(list(tmp_path.glob("*.pid"))) == 3
    finally:
        runner.cancel()
        thread.join(timeout=4)
    assert not thread.is_alive() and not errors and not runner._processes
    assert len(list(tmp_path.glob("*.pid"))) == 3
    for file in tmp_path.glob("*.pid"):
        assert_process_exited(int(file.read_text()))
    report = json.loads((tmp_path / ".audioraven-report.json").read_text())
    assert [r["status"] for r in report["entries"]] == ["cancelled"] * 3 + ["pending"] * 4
    assert events[-1]["cancelled"] is True


def test_quality_upgrade_does_not_reuse_lower_quality_or_legacy_files(tmp_path, monkeypatch):
    runner = BatchRunner(Settings("https://www.bilibili.com/list/ml123", str(tmp_path), audio_quality="192"), lambda event: None)
    track = make_tracks(1)[0]
    (tmp_path / "legacy.mp3").write_bytes(b"old audio")
    legacy = hashlib.sha256((track.url + "\0mp3").encode()).hexdigest()
    (tmp_path / ".audioraven-completed.json").write_text(json.dumps({legacy: {"files": ["legacy.mp3"]}}))
    calls = []

    def worker(*args):
        quality = runner.settings.audio_quality
        calls.append(quality)
        (tmp_path / f"{quality}.mp3").write_bytes(quality.encode())
        return {"files": [f"{quality}.mp3"]}

    monkeypatch.setattr(runner, "_run_worker", worker)
    runner.download([track])
    runner.settings.audio_quality = "320"
    runner.download([track])
    runner.download([track])
    runner.settings.audio_quality = "192"
    runner.download([track])
    assert calls == ["192", "320"]
    assert (tmp_path / "legacy.mp3").read_bytes() == b"old audio"
    assert (tmp_path / "192.mp3").is_file()


@pytest.mark.parametrize("quality,expected", [("best", "0"), ("320", "320"), ("256", "256"), ("192", "192"), ("128", "128")])
def test_encoding_settings_and_best_source_selection(quality, expected):
    options = encoding_options({"audio_format": "mp3", "audio_quality": quality})
    assert options["postprocessors"][0]["preferredquality"] == expected
    with YoutubeDL({"quiet": True, **options}) as ydl:
        info = ydl.process_ie_result({
            "id": "fixture", "title": "Synthetic format list",
            "formats": [
                {"format_id": "aac", "url": "https://example.com/low.m4a", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 192},
                {"format_id": "lossless", "url": "https://example.com/high.flac", "ext": "flac", "vcodec": "none", "acodec": "flac", "abr": 900},
            ],
        }, download=False)
    assert info["format_id"] == "lossless"


@pytest.mark.parametrize("kwargs", [{"parallel_downloads": 0}, {"parallel_downloads": 7}, {"audio_quality": "999"}])
def test_invalid_parallelism_and_quality_rejected(tmp_path, kwargs):
    with pytest.raises(ValueError):
        Settings("https://www.bilibili.com/list/ml123", str(tmp_path), **kwargs).validate()
