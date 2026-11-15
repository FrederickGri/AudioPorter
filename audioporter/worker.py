"""One isolated yt-dlp operation. JSON input/output only; no GUI imports."""
from __future__ import annotations

from dataclasses import asdict
import errno
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from .backend import Settings, normalize_url, safe_message


def send(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


class Logger:
    def debug(self, message):
        if not message.startswith("[debug]"):
            send({"type": "log", "message": safe_message(message)})

    def warning(self, message):
        send({"type": "log", "message": "Warning: " + safe_message(message)})

    def error(self, message):
        send({"type": "log", "message": safe_message(message)})


def base_options(config: dict) -> dict:
    options = {
        "logger": Logger(), "quiet": True, "no_warnings": False, "noprogress": True,
        "socket_timeout": config["socket_timeout"],
        # The supervisor retries whole operations, so attempts never multiply invisibly.
        "retries": 0, "fragment_retries": 0, "extractor_retries": 0, "file_access_retries": 0,
        "skip_unavailable_fragments": False, "ignoreerrors": False,
        "noplaylist": False, "cachedir": False,
        "allowed_extractors": ["bilibili.*"],
        "http_headers": {"Referer": "https://www.bilibili.com/"},
    }
    if config.get("cookie_file"):
        options["cookiefile"] = config["cookie_file"]
    elif config.get("browser"):
        options["cookiesfrombrowser"] = (config["browser"],)
    return options


def flatten_entries(info: dict):
    """Exhaust lazy playlist pages; never silently truncate after the first page."""
    if not info:
        raise RuntimeError("Bilibili returned an unavailable collection entry.")
    if info.get("_type") in {"playlist", "multi_video"} or "entries" in info:
        for entry in info.get("entries") or []:
            yield from flatten_entries(entry)
    else:
        yield info


def promote_file(source: Path, output_dir: Path) -> Path:
    """Publish a completed staged file atomically without replacing user files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = None
    for suffix in range(10000):
        target = output_dir / (source.name if not suffix else f"{source.stem} ({suffix + 1}){source.suffix}")
        try:
            # Both paths live in the destination filesystem; link creation is
            # atomic and fails if a competing batch already created the name.
            os.link(source, target)
        except FileExistsError:
            if not target.is_file() or target.stat().st_size != source.stat().st_size:
                continue
            if digest is None:
                with source.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").digest()
            with target.open("rb") as stream:
                existing_digest = hashlib.file_digest(stream, "sha256").digest()
            if existing_digest != digest:
                continue
        except OSError as exc:
            if exc.errno not in {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.ENOSYS}:
                raise
            # FAT/exFAT do not support hard links. Exclusively reserve the name,
            # then atomically rename the complete source over our empty file.
            try:
                handle = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                continue
            os.close(handle)
            try:
                os.replace(source, target)
            except OSError:
                target.unlink(missing_ok=True)
                raise
            return target
        source.unlink()
        return target
    raise RuntimeError("Too many files with the same name in the destination.")


def resolve_url(downloader, value: str) -> str:
    url = normalize_url(value)
    if url.startswith("https://b23.tv/"):
        with downloader.urlopen(url) as response:
            url = normalize_url(response.url)
        if url.startswith("https://b23.tv/"):
            raise RuntimeError("This short link did not resolve to a Bilibili collection or video.")
    return url


def scan(config: dict) -> dict:
    from yt_dlp import YoutubeDL
    options = base_options(config)
    options.update({"extract_flat": "in_playlist", "skip_download": True, "lazy_playlist": True})
    tracks = []
    seen = set()
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(resolve_url(downloader, config["url"]), download=False)
        for entry in flatten_entries(info):
            identifier = str(entry.get("id") or "")
            # Flat entries carry a page URL; fully extracted entries carry a signed media URL.
            url = entry.get("webpage_url") or entry.get("original_url")
            if not url and entry.get("_type") in {"url", "url_transparent"}:
                url = entry.get("url")
            if not url and identifier.startswith("BV"):
                url = f"https://www.bilibili.com/video/{identifier}"
            if not url:
                raise RuntimeError(f"Could not determine the Bilibili link for entry {identifier or len(tracks) + 1}.")
            url = normalize_url(url)
            if url in seen:
                continue
            seen.add(url)
            tracks.append({"id": identifier or url.rsplit("/", 1)[-1],
                           "title": str(entry.get("title") or identifier or "Untitled video"),
                           "url": url, "duration": entry.get("duration")})
            if len(tracks) % 50 == 0:
                send({"type": "log", "message": f"Read {len(tracks)} entries…"})
    return {"type": "result", "tracks": tracks, "title": (info or {}).get("title", "Collection")}


def encoding_options(config: dict) -> dict:
    quality = config.get("audio_quality", "best")
    # AAC can be copied to M4A without re-encoding. Non-AAC sources use 320 kbps.
    preferred = ("0" if quality == "best" else quality) if config["audio_format"] == "mp3" else "320"
    return {"format": "bestaudio/best", "postprocessors": [{
        "key": "FFmpegExtractAudio", "preferredcodec": config["audio_format"],
        "preferredquality": preferred, "nopostoverwrites": False,
    }]}


def download(config: dict) -> dict:
    import imageio_ffmpeg
    from yt_dlp import YoutubeDL
    from yt_dlp.postprocessor.common import PostProcessor
    from yt_dlp.postprocessor.ffmpeg import FFmpegExtractAudioPP

    destination = Path(config["destination"]).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    track_key = hashlib.sha256(config["track"]["url"].encode()).hexdigest()[:24]
    profile = config.get("audio_quality", "best") if config["audio_format"] == "mp3" else "source"
    output_dir = destination / config["audio_format"] / profile
    staging = destination / ".audioporter-work" / config["audio_format"] / profile / track_key
    staging.mkdir(parents=True, exist_ok=True)
    # A killed converter may leave a plausible-looking but incomplete output.
    # Only files promoted out of staging are trusted. Keep .part downloads for
    # resuming; discard unverified target-format files before yt-dlp inspects them.
    for unfinished in staging.glob("*." + config["audio_format"]):
        if unfinished.is_file():
            unfinished.unlink()
    output_files: list[str] = []
    last_progress = [0.0]
    known_title = [""]
    known_sources = set()

    def progress(event):
        info = event.get("info_dict") or {}
        source_key = (info.get("id"), info.get("format_id"))
        if source_key not in known_sources and info.get("acodec"):
            known_sources.add(source_key)
            codec = str(info["acodec"])
            bitrate = info.get("abr") or (info.get("tbr") if info.get("vcodec") == "none" else None)
            rate = f" · about {bitrate:.0f} kbps" if isinstance(bitrate, (int, float)) else ""
            send({"type": "log", "message": f"Source audio: {codec}{rate}. Output: {config['audio_format'].upper()} / {profile}."})
        title = info.get("playlist_title") or info.get("title")
        if title and title != known_title[0]:
            known_title[0] = title
            send({"type": "title", "title": title})
        now = time.monotonic()
        if event.get("status") == "downloading" and now - last_progress[0] < 0.2:
            return
        last_progress[0] = now
        size = event.get("total_bytes") or event.get("total_bytes_estimate")
        percent = min(100.0, event.get("downloaded_bytes", 0) * 100 / size) if size else None
        send({"type": "progress", "percent": percent, "speed": event.get("speed"), "eta": event.get("eta")})
        if event.get("status") == "finished":
            send({"type": "status", "status": "converting", "message": "Converting audio…"})

    class RecordFile(PostProcessor):
        def run(self, info):
            path = Path(info["filepath"]).resolve()
            if not path.is_relative_to(staging) or not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError("The audio output is missing or empty.")
            if path.suffix.lower() != "." + config["audio_format"]:
                raise RuntimeError("The audio output was not converted to the selected format.")
            path = promote_file(path, output_dir)
            info["filepath"] = str(path)
            relative = path.relative_to(destination).as_posix()
            if relative not in output_files:
                output_files.append(relative)
            return [], info

    class SelectedAudioQuality(FFmpegExtractAudioPP):
        def run(self, info):
            # yt-dlp normally copies an already-MP3 input regardless of the
            # requested bitrate. Honor explicit bitrate choices in that case.
            if config["audio_format"] == "mp3" and profile != "best" and info.get("ext") == "mp3":
                source = Path(info["filepath"])
                temporary = source.with_name(source.stem + ".encoding.mp3")
                self.run_ffmpeg(str(source), str(temporary), "libmp3lame", ["-b:a", profile + "k"])
                os.replace(temporary, source)
                return [], info
            return super().run(info)

    options = base_options(config)
    options.update(encoding_options(config))
    options.update({
        # All unverified conversion output stays hidden until the postprocessor
        # succeeds. Retrying can safely replace only these staged files.
        "paths": {"home": str(staging)},
        "outtmpl": {"default": "%(title).150B [%(id)s].%(ext)s"},
        "restrictfilenames": False, "windowsfilenames": True,
        "overwrites": False, "continuedl": True, "nopart": False,
        "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
        "progress_hooks": [progress],
    })
    converter_options = dict(options.pop("postprocessors")[0])
    converter_options.pop("key")
    with YoutubeDL(options) as downloader:
        downloader.add_post_processor(SelectedAudioQuality(downloader, **converter_options))
        downloader.add_post_processor(RecordFile(downloader), when="after_move")
        info = downloader.extract_info(resolve_url(downloader, config["track"]["url"]), download=True)
        if info is None or not output_files:
            raise RuntimeError("Bilibili returned no downloadable audio for this entry.")
    return {"type": "result", "status": "completed", "files": output_files}


def main() -> int:
    try:
        config = json.loads(sys.stdin.readline())
        settings = Settings(**{name: config[name] for name in Settings.__dataclass_fields__ if name in config})
        settings.validate()
        config.update(asdict(settings))
        action = config.get("action")
        if action == "scan":
            result = scan(config)
        elif action == "download":
            result = download(config)
        else:
            raise ValueError("Unknown worker operation.")
        send(result)
        return 0
    except Exception as exc:
        send({"type": "error", "message": safe_message(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
