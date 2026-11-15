"""Import verified audio into Music without putting file paths into AppleScript."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time

from .backend import CancelledError


# Terminology comes from Music.app/Contents/Resources/com.apple.Music.sdef.
# The script is constant. Both the path and previous persistent ID are argv data.
IMPORT_SCRIPT = r'''
on run argv
    set sourceFile to (POSIX file (item 1 of argv)) as alias
    set knownID to item 2 of argv
    with timeout of 25 seconds
        tell application id "com.apple.Music"
            set existingTrack to missing value
            if knownID is not "" then
                set matchingTracks to (every file track of library playlist 1 whose persistent ID is knownID)
                if (count of matchingTracks) > 0 then set existingTrack to item 1 of matchingTracks
            end if
            set matchingPlaylists to (every user playlist whose name is "BiliSong" and smart is false)
            if (count of matchingPlaylists) is 0 then
                set targetPlaylist to make new user playlist with properties {name:"BiliSong"}
            else
                set targetPlaylist to item 1 of matchingPlaylists
            end if
            if existingTrack is missing value then
                set importedTrack to add sourceFile to targetPlaylist
                if class of importedTrack is list then set importedTrack to item 1 of importedTrack
                set trackID to persistent ID of importedTrack
                return "imported" & tab & trackID
            else
                set trackID to persistent ID of existingTrack
                if not (exists (some track of targetPlaylist whose persistent ID is trackID)) then
                    duplicate existingTrack to targetPlaylist
                end if
                return "already_imported" & tab & trackID
            end if
        end tell
    end timeout
end run
'''


class MusicImporter:
    """Import each output once, tracking Music IDs even when Music copies files.

    The manifest belongs to the download destination. Each successful file is
    committed immediately, so a later error does not lose earlier import IDs.
    Cancellation and import errors never remove or change downloaded media.
    """

    TIMEOUT = 30.0

    def __init__(self, destination: str):
        self.destination = Path(destination).expanduser().resolve()
        self.manifest_path = self.destination / ".bilisong-music.json"

    @staticmethod
    def _check_cancel(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("Music import stopped; downloaded audio is preserved.")

    def _read_manifest(self) -> dict:
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 1, "files": {}}
        except (OSError, ValueError) as exc:
            # Silently discarding an unreadable manifest could duplicate a library.
            raise RuntimeError("The Music import record could not be read. Downloaded audio is preserved; restore .bilisong-music.json before importing again.") from exc
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("files"), dict):
            raise RuntimeError("The Music import record has an unsupported format. Downloaded audio is preserved.")
        return data

    def _save_manifest(self, manifest: dict) -> None:
        descriptor, name = tempfile.mkstemp(prefix=".bilisong-music-", suffix=".tmp", dir=self.destination)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(manifest, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, self.manifest_path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _file(self, name: str) -> tuple[Path, str]:
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            raise RuntimeError("Music import expects an audio filename inside the download destination.")
        path = (self.destination / name).resolve()
        if not path.is_relative_to(self.destination) or not path.is_file():
            raise RuntimeError("An audio file is missing or outside the download destination; Music import was skipped.")
        metadata = path.stat()
        if path.suffix.lower() not in {".mp3", ".m4a"} or metadata.st_size == 0:
            raise RuntimeError("Only completed MP3 or M4A files can be imported into Music.")
        signature = hashlib.sha256(json.dumps(
            [str(path), metadata.st_size, metadata.st_mtime_ns], ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
        return path, signature

    @staticmethod
    def _stop(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        finally:
            process.communicate(timeout=2)

    def _import_one(self, path: Path, known_id: str, cancel_event: threading.Event | None) -> tuple[str, str]:
        self._check_cancel(cancel_event)
        try:
            process = subprocess.Popen(
                ["/usr/bin/osascript", "-e", IMPORT_SCRIPT, str(path), known_id],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", start_new_session=True,
            )
        except OSError as exc:
            raise RuntimeError("Could not start Apple Music import. Downloaded audio is preserved.") from exc
        started = time.monotonic()
        try:
            while True:
                self._check_cancel(cancel_event)
                remaining = self.TIMEOUT - (time.monotonic() - started)
                if remaining <= 0:
                    raise RuntimeError("Apple Music import timed out after 30 seconds. Open Music, finish any setup or permission prompts, then retry. Downloaded audio is preserved.")
                try:
                    output, error = process.communicate(timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                if "-1743" in error or "not authorized" in error.lower() or "not permitted" in error.lower():
                    raise RuntimeError("Apple Music automation permission was denied. Allow BiliSong to control Music in System Settings → Privacy & Security → Automation, then retry. Downloaded audio is preserved.")
                if "-1712" in error:
                    raise RuntimeError("Apple Music did not respond in time. Open Music and finish any setup prompts, then retry. Downloaded audio is preserved.")
                raise RuntimeError("Apple Music could not import this audio. Open Music, finish any setup prompts, and retry. Downloaded audio is preserved.")
            fields = output.strip().split("\t")
            if len(fields) != 2 or fields[0] not in {"imported", "already_imported"} or not re.fullmatch(r"[0-9A-Fa-f]{16}", fields[1]):
                raise RuntimeError("Apple Music did not confirm the imported track ID. Downloaded audio is preserved.")
            return fields[0], fields[1].upper()
        finally:
            self._stop(process)

    def import_files(self, files: list[str], cancel_event: threading.Event | None = None) -> dict:
        self._check_cancel(cancel_event)
        summary = {"imported": 0, "already_imported": 0}
        if not files:
            return summary
        if sys.platform != "darwin":
            raise RuntimeError("Automatic Apple Music import is available on macOS. Downloaded audio is preserved.")
        # Validate every path and manifest before asking Music to change anything.
        items = [self._file(name) for name in files]
        manifest = self._read_manifest()
        try:
            self._save_manifest(manifest)  # Prove we can persist IDs before any import.
        except OSError as exc:
            raise RuntimeError("The Music import record cannot be saved. Check that the download destination is writable, then retry. Downloaded audio is preserved.") from exc
        seen = set()
        for path, signature in items:
            self._check_cancel(cancel_event)
            if signature in seen:
                continue
            seen.add(signature)
            record = manifest["files"].get(signature, {})
            known_id = record.get("persistent_id", "") if isinstance(record, dict) else ""
            if not isinstance(known_id, str) or not re.fullmatch(r"[0-9A-Fa-f]{16}", known_id):
                known_id = ""
            status, persistent_id = self._import_one(path, known_id, cancel_event)
            manifest["files"][signature] = {"path": str(path), "persistent_id": persistent_id}
            try:
                self._save_manifest(manifest)
            except OSError as exc:
                raise RuntimeError("Music imported the audio, but its import record could not be saved. Check destination permissions before retrying to avoid duplicate library entries. Downloaded audio is preserved.") from exc
            summary[status] += 1
        return summary
