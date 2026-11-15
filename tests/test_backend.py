import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from audioraven.backend import BatchRunner, CancelledError, Settings, Track, normalize_url, safe_message


def assert_process_exited(pid):
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if handle:
            try:
                assert kernel.WaitForSingleObject(handle, 2000) == 0
            finally:
                kernel.CloseHandle(handle)
    else:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def make_runner(tmp_path, **kwargs):
    events = []
    kwargs.setdefault("parallel_downloads", 1)
    runner = BatchRunner(Settings(
        url="https://space.bilibili.com/123/favlist?fid=456",
        destination=str(tmp_path), **kwargs), events.append)
    return runner, events


def tracks():
    return [Track(str(i), f"Song {i}", f"https://www.bilibili.com/video/BVtest{i}") for i in range(3)]


@pytest.mark.parametrize("url", [
    "https://space.bilibili.com/123/favlist?ftype=create&fid=456",
    "space.bilibili.com/123/favlist?fid=456#anchor",
    "https://www.bilibili.com/list/ml456?oid=123",
    "https://www.bilibili.com/medialist/play/ml456",
])
def test_favorites_links_normalize_independent_of_query_order(url):
    assert normalize_url(url) == "https://www.bilibili.com/medialist/detail/ml456"


@pytest.mark.parametrize("url", [
    "", "https://example.com/123", "https://bilibili.com.evil.test/favlist?fid=456",
    "file:///tmp/a", "https://user:password@bilibili.com/video/BV1",
    "https://www.bilibili.com:8080/video/BV1", "https://space.bilibili.com/123/favlist",
    "https://space.bilibili.com/123", "https://www.bilibili.com/",
])
def test_invalid_links_fail_before_network(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_all_discovered_entries_are_retained(tmp_path, monkeypatch):
    runner, events = make_runner(tmp_path)
    items = [dict(id=str(i), title=f"Song {i}", url=f"https://www.bilibili.com/video/BV{i}") for i in range(137)]
    monkeypatch.setattr(runner, "_run_worker", lambda *args: {"type": "result", "tracks": items})
    found = runner.scan()
    assert len(found) == 137
    assert found[-1].id == "136"


def test_exhausted_entry_does_not_stop_remaining_batch(tmp_path, monkeypatch):
    runner, events = make_runner(tmp_path, retries=2)
    attempts = []
    delays = []
    monkeypatch.setattr(runner._cancel, "wait", lambda delay: delays.append(delay) or False)

    def worker(action, track, index):
        attempts.append(index)
        if index == 0:
            raise TimeoutError("timed out")
        filename = f"song-{index}.mp3"
        (tmp_path / filename).write_bytes(b"test audio")
        return {"type": "result", "files": [filename]}

    monkeypatch.setattr(runner, "_run_worker", worker)
    runner.download(tracks())
    assert attempts == [0, 0, 0, 1, 2]
    assert delays == [2, 4]
    result = events[-1]
    assert result["failed"] == 1 and result["completed"] == 2
    report = json.loads((tmp_path / ".audioraven-report.json").read_text())
    assert [entry["status"] for entry in report["entries"]] == ["failed", "completed", "completed"]


def test_retry_success_and_cache_rechecks_deleted_output(tmp_path, monkeypatch):
    runner, events = make_runner(tmp_path, retries=1)
    monkeypatch.setattr(runner._cancel, "wait", lambda delay: False)
    attempts = []

    def worker(action, track, index):
        attempts.append(index)
        if len(attempts) == 1:
            raise RuntimeError("Temporary failure")
        (tmp_path / "song.mp3").write_bytes(b"audio")
        return {"type": "result", "files": ["song.mp3"]}

    monkeypatch.setattr(runner, "_run_worker", worker)
    runner.download(tracks()[:1])
    assert len(attempts) == 2
    runner.download(tracks()[:1])
    assert len(attempts) == 2 and events[-1]["skipped"] == 1
    (tmp_path / "song.mp3").unlink()
    runner.download(tracks()[:1])
    assert len(attempts) == 3 and events[-1]["completed"] == 1


def test_format_change_does_not_skip_other_format(tmp_path, monkeypatch):
    runner, _ = make_runner(tmp_path)
    seen = []

    def worker(action, track, index):
        fmt = runner.settings.audio_format
        seen.append(fmt)
        filename = f"song.{fmt}"
        (tmp_path / filename).write_bytes(b"audio")
        return {"type": "result", "files": [filename]}

    monkeypatch.setattr(runner, "_run_worker", worker)
    runner.download(tracks()[:1])
    runner.settings.audio_format = "m4a"
    runner.download(tracks()[:1])
    assert seen == ["mp3", "m4a"]


def test_cancel_during_backoff_does_not_start_next_entry(tmp_path, monkeypatch):
    runner, events = make_runner(tmp_path, retries=3)
    attempts = []

    def worker(action, track, index):
        attempts.append(index)
        raise RuntimeError("offline")

    def cancel_wait(delay):
        runner.cancel()
        return True

    monkeypatch.setattr(runner, "_run_worker", worker)
    monkeypatch.setattr(runner._cancel, "wait", cancel_wait)
    runner.download(tracks())
    assert attempts == [0]
    assert events[-1]["cancelled"] is True
    report = json.loads((tmp_path / ".audioraven-report.json").read_text())
    assert [entry["status"] for entry in report["entries"]] == ["cancelled", "pending", "pending"]


def test_worker_deadline_really_terminates_process(tmp_path, monkeypatch):
    runner, _ = make_runner(tmp_path, item_timeout=1)
    pid_path = tmp_path / "worker.pid"
    script = "import os,sys,time; from pathlib import Path; sys.stdin.readline(); Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    monkeypatch.setattr(runner, "_worker_command", lambda: [sys.executable, "-c", script, str(pid_path)])
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="exceeded 1 seconds"):
        runner._run_worker("download", tracks()[0], 0)
    assert time.monotonic() - started < 5
    assert not runner._processes
    assert_process_exited(int(pid_path.read_text()))


def test_cancel_really_terminates_active_process(tmp_path, monkeypatch):
    runner, _ = make_runner(tmp_path, item_timeout=30)
    pid_path = tmp_path / "worker.pid"
    script = "import os,sys,time; from pathlib import Path; sys.stdin.readline(); Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    monkeypatch.setattr(runner, "_worker_command", lambda: [sys.executable, "-c", script, str(pid_path)])
    caught = []

    def run():
        try:
            runner._run_worker("download", tracks()[0], 0)
        except BaseException as exc:
            caught.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 3
    while not pid_path.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert pid_path.exists()
    runner.cancel()
    thread.join(timeout=4)
    assert not thread.is_alive()
    assert len(caught) == 1 and isinstance(caught[0], CancelledError)
    assert not runner._processes
    assert_process_exited(int(pid_path.read_text()))


def test_cookie_snapshot_is_private_temporary_and_original_unchanged(tmp_path, monkeypatch):
    cookie_file = tmp_path / "my-account.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n")
    runner, _ = make_runner(tmp_path, cookie_file=str(cookie_file))
    script = "import json,sys,os; from pathlib import Path; c=json.loads(sys.stdin.readline()); p=Path(c['cookie_file']); mode=p.stat().st_mode & 0o777; p.write_text('changed'); print(json.dumps({'type':'result','path':str(p),'mode':mode}))"
    monkeypatch.setattr(runner, "_worker_command", lambda: [sys.executable, "-c", script])
    result = runner._run_worker("scan")
    if os.name == 'posix':
        assert result["mode"] == 0o600
    assert result["path"] != str(cookie_file)
    assert not Path(result["path"]).exists()
    assert cookie_file.read_text() == "# Netscape HTTP Cookie File\n"


def test_log_redacts_signed_urls_and_cookie_secrets():
    message = safe_message("SESSDATA=secret-value Cookie: session-value https://cdn.test/audio?token=secret ")
    assert "secret" not in message and "session-value" not in message


def test_frozen_worker_command_reuses_bundle_executable(tmp_path, monkeypatch):
    runner, _ = make_runner(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert runner._worker_command() == [sys.executable, "--worker"]


def test_rename_reuses_legacy_completed_history(tmp_path, monkeypatch):
    runner, events = make_runner(tmp_path)
    song = tracks()[0]
    (tmp_path / 'saved.mp3').write_bytes(b'completed audio')
    (tmp_path / '.bilisong-completed.json').write_text(json.dumps({
        runner._cache_key(song): {'files': ['saved.mp3'], 'title': 'Saved song'}
    }), encoding='utf-8')
    monkeypatch.setattr(runner, '_run_worker', lambda *args: pytest.fail('Must reuse existing output'))
    runner.download([song])
    assert events[-1]['skipped'] == 1
    assert song.title == 'Saved song'
