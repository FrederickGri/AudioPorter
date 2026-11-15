"""No test imports media or changes the real Music library."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from audioporter.backend import CancelledError
from audioporter.music import IMPORT_SCRIPT, MusicImporter


@pytest.fixture
def importer(tmp_path, monkeypatch):
    monkeypatch.setattr("audioporter.music.sys.platform", "darwin")
    return MusicImporter(str(tmp_path))


def audio(importer, name="test.mp3", content=b"synthetic test bytes"):
    path = importer.destination / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_manifest_uses_music_id_after_music_copies_file(importer, monkeypatch):
    source = audio(importer, '音乐/song unicode.mp3' if os.name == 'nt' else '音乐 / song "quotes"; $(untouched).mp3')
    calls = []

    def music_boundary(path, known_id, cancel_event):
        calls.append((path, known_id))
        return ("already_imported" if known_id else "imported", "0123456789ABCDEF")

    monkeypatch.setattr(importer, "_import_one", music_boundary)
    relative = str(source.relative_to(importer.destination))
    assert importer.import_files([relative]) == {"imported": 1, "already_imported": 0}
    assert importer.import_files([relative]) == {"imported": 0, "already_imported": 1}
    assert calls == [(source, ""), (source, "0123456789ABCDEF")]
    records = json.loads(importer.manifest_path.read_text())["files"]
    assert next(iter(records.values()))["persistent_id"] == "0123456789ABCDEF"
    assert source.read_bytes() == b"synthetic test bytes"


def test_deleted_music_track_is_reimported_and_id_replaced(importer, monkeypatch):
    audio(importer)
    seen = []
    results = iter([("imported", "0000000000000001"), ("imported", "0000000000000002")])

    def boundary(path, known_id, cancel_event):
        seen.append(known_id)
        return next(results)

    monkeypatch.setattr(importer, "_import_one", boundary)
    importer.import_files(["test.mp3"])
    assert importer.import_files(["test.mp3"])["imported"] == 1
    assert seen == ["", "0000000000000001"]
    assert next(iter(json.loads(importer.manifest_path.read_text())["files"].values()))["persistent_id"] == "0000000000000002"


def test_changed_file_is_not_skipped_and_duplicate_arguments_are_deduplicated(importer, monkeypatch):
    source = audio(importer)
    seen = []

    def boundary(path, known_id, cancel_event):
        seen.append(known_id)
        return "imported", "0000000000000001"

    monkeypatch.setattr(importer, "_import_one", boundary)
    assert importer.import_files(["test.mp3", "test.mp3"])["imported"] == 1
    source.write_bytes(b"replacement, deliberately different size")
    assert importer.import_files(["test.mp3"])["imported"] == 1
    assert seen == ["", ""]


def test_rename_preserves_legacy_music_ids(importer, monkeypatch):
    audio(importer)
    signature = importer._file('test.mp3')[1]
    previous = importer.destination / '.bilisong-music.json'
    previous.write_text(json.dumps({'version': 1, 'files': {
        signature: {'persistent_id': '0123456789ABCDEF'}
    }}), encoding='utf-8')
    observed = []
    def boundary(path, known_id, cancel_event):
        observed.append(known_id)
        return 'already_imported', known_id
    monkeypatch.setattr(importer, '_import_one', boundary)
    assert importer.import_files(['test.mp3'])['already_imported'] == 1
    assert observed == ['0123456789ABCDEF']
    assert previous.is_file() and importer.manifest_path.is_file()


def test_successful_import_record_survives_later_failure(importer, monkeypatch):
    audio(importer, "one.mp3")
    audio(importer, "two.m4a")

    def boundary(path, known_id, cancel_event):
        if path.name == "two.m4a":
            raise RuntimeError("Music import failed")
        return "imported", "0000000000000001"

    monkeypatch.setattr(importer, "_import_one", boundary)
    with pytest.raises(RuntimeError, match="Music import failed"):
        importer.import_files(["one.mp3", "two.m4a"])
    records = json.loads(importer.manifest_path.read_text())["files"]
    assert len(records) == 1
    assert Path(next(iter(records.values()))["path"]).name == "one.mp3"
    assert (importer.destination / "two.m4a").is_file()


@pytest.mark.parametrize("name", ["../outside.mp3", "/tmp/absolute.mp3", "missing.mp3", "", "empty.mp3", "wrong.txt"])
def test_invalid_audio_never_reaches_music(importer, monkeypatch, name):
    audio(importer, "empty.mp3", b"")
    audio(importer, "wrong.txt")
    monkeypatch.setattr(importer, "_import_one", lambda *args: pytest.fail("Must not invoke Music"))
    with pytest.raises(RuntimeError):
        importer.import_files([name])


def test_symlink_outside_destination_never_reaches_music(importer, tmp_path, monkeypatch):
    outside = tmp_path.parent / (tmp_path.name + "-outside.mp3")
    outside.write_bytes(b"test")
    try:
        try:
            (tmp_path / "link.mp3").symlink_to(outside)
        except OSError:
            pytest.skip('Creating symlinks requires Windows Developer Mode or elevated privileges')
        monkeypatch.setattr(importer, "_import_one", lambda *args: pytest.fail("Must not invoke Music"))
        with pytest.raises(RuntimeError, match="outside"):
            importer.import_files(["link.mp3"])
    finally:
        outside.unlink()


def test_corrupt_manifest_does_not_silently_reimport(importer, monkeypatch):
    audio(importer)
    importer.manifest_path.write_text("broken JSON")
    monkeypatch.setattr(importer, "_import_one", lambda *args: pytest.fail("Must not invoke Music"))
    with pytest.raises(RuntimeError, match="record could not be read"):
        importer.import_files(["test.mp3"])


def test_manifest_write_failure_stops_before_import(importer, monkeypatch):
    audio(importer)
    monkeypatch.setattr(importer, "_import_one", lambda *args: pytest.fail("Must not invoke Music"))

    def cannot_replace(*args):
        raise PermissionError("Destination is not writable")

    monkeypatch.setattr("audioporter.music.os.replace", cannot_replace)
    with pytest.raises(RuntimeError, match="destination is writable"):
        importer.import_files(["test.mp3"])
    assert not list(importer.destination.glob(".audioporter-music-*.tmp"))
    assert (importer.destination / "test.mp3").is_file()


class CompletedProcess:
    def __init__(self, output="imported\t0123456789ABCDEF\n", error="", returncode=0):
        self.returncode = returncode
        self.output = output
        self.error = error

    def communicate(self, timeout=None):
        return self.output, self.error

    def poll(self):
        return self.returncode


def test_script_paths_are_passed_only_as_arguments(importer, monkeypatch):
    source = audio(importer, '中文 unicode.mp3' if os.name == 'nt' else '中文 "quotes"\n;$(touch NO).mp3')
    captured = []

    def spawn(args, **kwargs):
        captured.append((args, kwargs))
        return CompletedProcess()

    monkeypatch.setattr("audioporter.music.subprocess.Popen", spawn)
    assert importer._import_one(source, "", None) == ("imported", "0123456789ABCDEF")
    args, kwargs = captured[0]
    assert args == ["/usr/bin/osascript", "-e", IMPORT_SCRIPT, str(source), ""]
    assert str(source) not in IMPORT_SCRIPT
    assert "shell" not in kwargs
    assert kwargs["start_new_session"] is True


def test_automation_denial_explains_fix_and_preserves_audio(importer, monkeypatch):
    source = audio(importer)
    monkeypatch.setattr("audioporter.music.subprocess.Popen", lambda *a, **k: CompletedProcess(error="Not authorized to send Apple events to Music. (-1743)", returncode=1))
    with pytest.raises(RuntimeError, match="Privacy & Security → Automation"):
        importer.import_files(["test.mp3"])
    assert source.read_bytes() == b"synthetic test bytes"
    assert json.loads(importer.manifest_path.read_text())["files"] == {}


@pytest.mark.parametrize("reply", ["", "imported\tbad-id", "unexpected\t0123456789ABCDEF"])
def test_unconfirmed_import_is_not_recorded(importer, monkeypatch, reply):
    audio(importer)
    monkeypatch.setattr("audioporter.music.subprocess.Popen", lambda *a, **k: CompletedProcess(output=reply))
    with pytest.raises(RuntimeError, match="did not confirm"):
        importer.import_files(["test.mp3"])
    assert json.loads(importer.manifest_path.read_text())["files"] == {}


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.skipif(sys.platform != 'darwin', reason='Music subprocess supervision is macOS-only')
def test_timeout_or_cancellation_kills_supervised_process(importer, monkeypatch, cancel):
    source = audio(importer)
    actual_popen = subprocess.Popen
    children = []

    def fake_music(args, **kwargs):
        # This is a Python sleeper, never osascript or Music.
        process = actual_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr("audioporter.music.subprocess.Popen", fake_music)
    event = threading.Event()
    if cancel:
        timer = threading.Timer(0.15, event.set)
        timer.start()
    else:
        monkeypatch.setattr(importer, "TIMEOUT", 0.15)
    started = time.monotonic()
    try:
        with pytest.raises(CancelledError if cancel else RuntimeError, match="stopped" if cancel else "timed out"):
            importer._import_one(source, "", event)
    finally:
        if cancel:
            timer.join()
    assert time.monotonic() - started < 3
    assert len(children) == 1 and children[0].poll() is not None
    assert source.is_file()


def test_cancelled_before_start_never_invokes_music(importer, monkeypatch):
    event = threading.Event()
    event.set()
    monkeypatch.setattr("audioporter.music.subprocess.Popen", lambda *a, **k: pytest.fail("Must not invoke Music"))
    with pytest.raises(CancelledError):
        importer.import_files([], event)


@pytest.mark.skipif(sys.platform != "darwin", reason="AppleScript compiler requires macOS")
def test_applescript_compiles_without_running_or_importing(tmp_path):
    result = subprocess.run(
        ["/usr/bin/osacompile", "-o", str(tmp_path / "import.scpt"), "-e", IMPORT_SCRIPT],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
