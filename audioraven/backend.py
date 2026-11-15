"""UI-independent batch orchestration with killable download workers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .processes import WindowsJob


class CancelledError(RuntimeError):
    """The user cancelled the active operation."""


def normalize_url(value: str) -> str:
    """Validate Bilibili input and normalize collection links for yt-dlp."""
    value = value.strip()
    if not value:
        raise ValueError("Paste a Bilibili favorites folder or collection link.")
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
        value = "https://" + value
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("This link is not a valid URL.") from exc
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password or port:
        raise ValueError("Use a standard https:// Bilibili link.")
    if host not in {"bilibili.com", "www.bilibili.com", "space.bilibili.com", "m.bilibili.com", "b23.tv"}:
        raise ValueError("Only bilibili.com and b23.tv links are supported.")
    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)
    if re.match(r"/audio/am\d+", path):
        raise ValueError("Audio-station albums are not supported yet. Use a favorites folder or video collection.")
    fid = query.get("fid", [""])[0]
    fav_match = re.fullmatch(r"/(?:list|medialist/(?:play|detail))/ml(\d+)", path)
    if ("favlist" in path or "/fav/" in path) and fid.isdigit() and int(fid) > 0:
        return f"https://www.bilibili.com/medialist/detail/ml{fid}"
    if fav_match:
        return f"https://www.bilibili.com/medialist/detail/ml{fav_match[1]}"
    if "favlist" in path:
        raise ValueError("Open one favorites folder and copy its link, including fid= and the folder number.")
    supported_path = (
        host == "b23.tv" and bool(path)
        or host == "space.bilibili.com" and re.fullmatch(r"/\d+/(?:lists/\d+|channel/(?:collectiondetail|seriesdetail))", path)
        or host != "space.bilibili.com" and re.fullmatch(r"/(?:video/(?:BV[0-9A-Za-z]+|av\d+)|audio/au\d+|bangumi/play/ep\d+|(?:list|medialist/play)/\d+)", path)
    )
    if not supported_path:
        raise ValueError("Use a specific favorites folder, collection, or video link, rather than a profile or home page.")
    # Normalize query order for older collection/series extractors.
    if "/channel/" in path and query.get("sid", [""])[0].isdigit():
        query = {"sid": query["sid"], **{k: v for k, v in query.items() if k != "sid"}}
    if host == "m.bilibili.com":
        host = "www.bilibili.com"
    return urlunsplit(("https", host, path or "/", urlencode(query, doseq=True), ""))


def safe_message(value: object) -> str:
    """Keep signed media URLs, cookie values and terminal escapes out of logs."""
    message = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", str(value))
    message = re.sub(r"https?://[^\s<>]+", "[Bilibili URL]", message)
    message = re.sub(r"(?i)(SESSDATA|bili_jct|DedeUserID|cookie|authorization)(\s*[:=]\s*)[^\s;,]+", r"\1\2[redacted]", message)
    return message[:2000]


@dataclass
class Settings:
    url: str
    destination: str
    audio_format: str = "mp3"
    retries: int = 3
    socket_timeout: int = 30
    item_timeout: int = 600
    cookie_file: str = ""
    browser: str = ""
    parallel_downloads: int = 3
    audio_quality: str = "best"

    @property
    def quality_profile(self) -> str:
        return self.audio_quality if self.audio_format == "mp3" else "source"

    def validate(self) -> None:
        self.url = normalize_url(self.url)
        if not self.destination.strip():
            raise ValueError("Choose a folder for the downloaded music.")
        if self.audio_format not in {"mp3", "m4a"}:
            raise ValueError("Choose MP3 or M4A output.")
        if not 1 <= self.parallel_downloads <= 6:
            raise ValueError("Choose between 1 and 6 simultaneous downloads.")
        if self.audio_quality not in {"best", "320", "256", "192", "128"}:
            raise ValueError("Choose Best quality, 320, 256, 192, or 128 kbps.")
        if not 0 <= self.retries <= 10:
            raise ValueError("Retries must be between 0 and 10.")
        if not 1 <= self.socket_timeout <= 300:
            raise ValueError("Network timeout must be between 1 and 300 seconds.")
        if not 1 <= self.item_timeout <= 86400:
            raise ValueError("Item timeout must be between 1 second and 24 hours.")
        if self.cookie_file and not Path(self.cookie_file).expanduser().is_file():
            raise ValueError("The selected cookies file does not exist.")
        if self.browser not in {"", "chrome", "chromium", "firefox", "safari", "edge", "brave", "opera", "vivaldi"}:
            raise ValueError("Choose a supported browser for account access.")
        if self.browser and self.cookie_file:
            raise ValueError("Choose either browser login or a cookies file, not both.")


@dataclass
class Track:
    id: str
    title: str
    url: str
    duration: float | None = None


class BatchRunner:
    def __init__(self, settings: Settings, emit: Callable[[dict], None]):
        self.settings = settings
        self.emit = emit
        self._cancel = threading.Event()
        self._process_lock = threading.Lock()
        self._processes: dict[subprocess.Popen, WindowsJob | None] = {}
        self._cache: dict = {}

    def cancel(self) -> None:
        self._cancel.set()
        with self._process_lock:
            processes = list(self._processes)
        for process in processes:
            self._stop_process(process)

    def _stop_process(self, process: subprocess.Popen) -> None:
        # POSIX sessions and Windows jobs own the entire converter tree.
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            with self._process_lock:
                job = self._processes.get(process)
            if job is not None:
                job.close()
            elif process.poll() is None:
                process.kill()

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise CancelledError("Cancelled.")

    def _worker_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--worker"]
        return [sys.executable, "-m", "audioraven.worker"]

    def _run_worker(self, action: str, track: Track | None = None, index: int | None = None) -> dict:
        self._check_cancel()
        config = asdict(self.settings)
        config["action"] = action
        if track is not None:
            config["track"] = asdict(track)
        messages: queue.Queue = queue.Queue()
        result = None
        error = None
        # The parent owns cookie snapshots so forced termination never leaves
        # session credentials behind in a worker-created temporary directory.
        with tempfile.TemporaryDirectory(prefix="audioraven-session-") as private_dir:
            if self.settings.cookie_file:
                snapshot = Path(private_dir) / "cookies.txt"
                shutil.copyfile(Path(self.settings.cookie_file).expanduser(), snapshot)
                snapshot.chmod(0o600)
                config["cookie_file"] = str(snapshot)
            process = subprocess.Popen(
                self._worker_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                bufsize=1, start_new_session=(os.name == "posix"),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                cwd=str(Path(__file__).resolve().parent.parent) if not getattr(sys, "frozen", False) else None,
            )
            try:
                job = WindowsJob(process.pid) if sys.platform == "win32" else None
            except BaseException:
                process.kill()
                process.wait(timeout=3)
                process.stdin.close()
                process.stdout.close()
                raise
            with self._process_lock:
                self._processes[process] = job
            def read_output():
                try:
                    for line in process.stdout:
                        messages.put(line)
                finally:
                    messages.put(None)
            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            started = time.monotonic()
            # Folder discovery has a deadline too; this setting can be raised for very large folders.
            deadline = self.settings.item_timeout
            try:
                self._check_cancel()
                process.stdin.write(json.dumps(config, ensure_ascii=False) + "\n")
                process.stdin.close()
                eof = False
                while not eof:
                    self._check_cancel()
                    if time.monotonic() - started > deadline:
                        raise TimeoutError(f"{'Folder scan' if action == 'scan' else 'Download'} exceeded {deadline} seconds. Increase the item timeout and retry.")
                    try:
                        line = messages.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if line is None:
                        eof = True
                        continue
                    try:
                        event = json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        self.emit({"type": "log", "message": safe_message(line.strip())})
                        continue
                    if not isinstance(event, dict):
                        continue
                    kind = event.get("type")
                    if kind == "result":
                        result = event
                    elif kind == "error":
                        error = safe_message(event.get("message", "Download failed."))
                    else:
                        if kind == "title" and track is not None and isinstance(event.get("title"), str):
                            track.title = event["title"]
                        if index is not None:
                            event["index"] = index
                        if "message" in event:
                            event["message"] = safe_message(event["message"])
                        self.emit(event)
                try:
                    code = process.wait(timeout=2)
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError("Download worker did not exit cleanly.") from exc
                self._check_cancel()
                if code or result is None:
                    raise RuntimeError(error or "Download worker stopped unexpectedly. Retry the operation.")
                return result
            finally:
                self._stop_process(process)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
                reader.join(timeout=2)
                for pipe in (process.stdin, process.stdout):
                    if pipe is not None:
                        pipe.close()
                with self._process_lock:
                    self._processes.pop(process, None)

    def _with_retries(self, action: str, track: Track | None = None, index: int | None = None) -> dict:
        for attempt in range(self.settings.retries + 1):
            self._check_cancel()
            try:
                return self._run_worker(action, track, index)
            except CancelledError:
                raise
            except (RuntimeError, OSError, ValueError) as exc:
                self._check_cancel()
                if attempt >= self.settings.retries:
                    raise RuntimeError(safe_message(exc)) from exc
                delay = min(2 ** (attempt + 1), 30)
                message = f"Retry {attempt + 1}/{self.settings.retries} in {delay}s: {safe_message(exc)}"
                self.emit({"type": "status", "index": index, "status": "retrying", "message": message} if index is not None else {"type": "log", "message": message})
                if self._cancel.wait(delay):
                    raise CancelledError("Cancelled.")
        raise RuntimeError("No download attempt was made.")

    def scan(self) -> list[Track]:
        self.settings.validate()
        self._check_cancel()
        self.emit({"type": "log", "message": "Reading the entire collection…"})
        result = self._with_retries("scan")
        tracks = [Track(**item) for item in result.get("tracks", [])]
        self.emit({"type": "log", "message": f"Found {len(tracks)} video entries. Multi-part videos download all parts."})
        return tracks

    @staticmethod
    def _atomic_json(path: Path, data: dict) -> None:
        handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _cache_key(self, track: Track) -> str:
        # Include quality and source-selection policy: an old 192 kbps download
        # must never satisfy a request for a higher-quality encoding.
        return hashlib.sha256("\0".join((track.url, self.settings.audio_format,
            self.settings.quality_profile, "best-source-v2")).encode()).hexdigest()

    def _cached_files(self, track: Track, destination: Path) -> list[str]:
        record = self._cache.get(self._cache_key(track), {})
        files = record.get("files", []) if isinstance(record, dict) else []
        if not isinstance(files, list) or not files:
            return []
        for name in files:
            if not isinstance(name, str):
                return []
            file = (destination / name).resolve()
            if not file.is_relative_to(destination) or not file.is_file() or file.stat().st_size == 0:
                return []
        return files

    def download(self, tracks: list[Track]) -> None:
        self.settings.validate()
        destination = Path(self.settings.destination).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        cache_path = destination / ".audioraven-completed.json"
        previous_cache = destination / '.bilisong-completed.json'
        try:
            self._cache = json.loads((cache_path if cache_path.exists() else previous_cache).read_text(encoding="utf-8"))
            if not isinstance(self._cache, dict):
                self._cache = {}
        except (OSError, ValueError):
            self._cache = {}
        records = [{"id": t.id, "title": t.title, "status": "pending", "message": "", "files": []} for t in tracks]
        report_path = destination / ".audioraven-report.json"
        completed = failed = skipped = 0
        def save_report():
            self._atomic_json(report_path, {
                "updated_at": datetime.now(timezone.utc).isoformat(), "format": self.settings.audio_format,
                "quality": self.settings.quality_profile, "parallel_downloads": self.settings.parallel_downloads,
                "completed": completed, "failed": failed, "skipped": skipped,
                "cancelled": self._cancel.is_set(), "entries": records,
            })
        # Prove destination writability before any network downloads.
        save_report()
        def run_one(index):
            self._check_cancel()
            track = tracks[index]
            normalize_url(track.url)
            files = self._cached_files(track, destination)
            if files:
                cached_title = self._cache.get(self._cache_key(track), {}).get("title")
                if isinstance(cached_title, str) and cached_title:
                    track.title = cached_title
                    self.emit({"type": "title", "index": index, "title": cached_title})
                return "skipped", files
            self.emit({"type": "status", "index": index, "status": "downloading", "message": "Downloading audio…"})
            result = self._with_retries("download", track, index)
            return "completed", result.get("files", [])

        # Only the coordinator writes manifests/reports. Each pool slot supervises
        # one independent process group, including its own retries and converter.
        pool = ThreadPoolExecutor(max_workers=self.settings.parallel_downloads, thread_name_prefix="AudioRaven")
        pending = {}
        next_index = 0
        try:
            while pending or (next_index < len(tracks) and not self._cancel.is_set()):
                while len(pending) < self.settings.parallel_downloads and next_index < len(tracks) and not self._cancel.is_set():
                    pending[pool.submit(run_one, next_index)] = next_index
                    next_index += 1
                if not pending:
                    break
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    index = pending.pop(future)
                    track = tracks[index]
                    files = []
                    try:
                        status, files = future.result()
                        if status == "skipped":
                            skipped += 1
                            message = "Already downloaded at this quality; all output files are present."
                        else:
                            completed += 1
                            message = "Audio saved."
                            if files:
                                self._cache[self._cache_key(track)] = {"files": files, "title": track.title}
                                try:
                                    self._atomic_json(cache_path, self._cache)
                                except OSError as exc:
                                    self.emit({"type": "log", "message": "Audio saved, but download history could not be written: " + safe_message(exc)})
                    except CancelledError:
                        status, message = "cancelled", "Cancelled; partial files can resume next time."
                    except Exception as exc:
                        failed += 1
                        status, message = "failed", safe_message(exc)
                    records[index].update(title=track.title, status=status, message=message, files=files)
                    save_report()
                    self.emit({"type": "status", "index": index, "status": status, "message": message, "files": files})
        except BaseException:
            self.cancel()
            raise
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
        save_report()
        self.emit({"type": "finished", "completed": completed, "failed": failed, "skipped": skipped,
                   "cancelled": self._cancel.is_set(), "report": str(report_path)})
