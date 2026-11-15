from pathlib import Path
import hashlib
import struct
import subprocess
import wave

import imageio_ffmpeg
import pytest
from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.ffmpeg import FFmpegExtractAudioPP

from bilisong.worker import download


@pytest.mark.parametrize("audio_format", ["mp3", "m4a"])
def test_bundled_ffmpeg_can_convert_audio_without_system_ffmpeg(tmp_path, audio_format):
    source = tmp_path / "synthetic.wav"
    # A short locally generated silent waveform; no account or media download.
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(struct.pack("<800h", *([0] * 800)))

    with YoutubeDL({"quiet": True, "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe()}) as downloader:
        converter = FFmpegExtractAudioPP(downloader, preferredcodec=audio_format, preferredquality="192")
        _, result = converter.run({"filepath": str(source), "ext": "wav", "vcodec": "none"})

    target = Path(result["filepath"])
    assert target.suffix == "." + audio_format
    assert target.is_file() and target.stat().st_size > 0


def test_retry_rebuilds_interrupted_conversion_and_preserves_saved_m4a(tmp_path, monkeypatch):
    media = tmp_path / "source.m4a"
    subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-t", "0.2", "-c:a", "aac", str(media),
    ], check=True, capture_output=True)

    destination = tmp_path / "music"
    url = "https://www.bilibili.com/video/BVTEST"
    staging = destination / ".bilisong-work" / "mp3" / "best" / hashlib.sha256(url.encode()).hexdigest()[:24]
    staging.mkdir(parents=True)
    (staging / "Synthetic [BVTEST].m4a").write_bytes(media.read_bytes())
    (staging / "Synthetic [BVTEST].mp3").write_bytes(b"truncated audio")
    saved_m4a = destination / "m4a" / "Synthetic [BVTEST].m4a"
    saved_m4a.parent.mkdir()
    saved_m4a.write_bytes(media.read_bytes())
    original_hash = hashlib.sha256(saved_m4a.read_bytes()).digest()

    class LocalMediaDownloader(YoutubeDL):
        def __init__(self, params):
            # Only the extractor/network boundary is replaced. Actual yt-dlp
            # download, conversion, postprocessing, and publication run below.
            super().__init__({**params, "enable_file_urls": True})

        def extract_info(self, requested_url, download=True, *args, **kwargs):
            assert requested_url == url
            return self.process_ie_result({
                "id": "BVTEST", "title": "Synthetic", "url": media.as_uri(),
                "ext": "m4a", "acodec": "aac", "vcodec": "none",
                "webpage_url": url, "extractor": "fixture", "extractor_key": "Fixture",
            }, download=download)

    monkeypatch.setattr("yt_dlp.YoutubeDL", LocalMediaDownloader)
    result = download({
        "destination": str(destination), "audio_format": "mp3", "socket_timeout": 10,
        "track": {"url": url, "id": "BVTEST", "title": "Synthetic"},
    })
    assert result["files"] == ["mp3/best/Synthetic [BVTEST].mp3"]
    output = destination / result["files"][0]
    assert output.read_bytes() != b"truncated audio"
    assert output.stat().st_size > 100
    assert hashlib.sha256(saved_m4a.read_bytes()).digest() == original_hash
    # A real decoder verifies more than nonempty-file checks.
    subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-i", str(output), "-f", "null", "-",
    ], check=True, capture_output=True)


@pytest.mark.parametrize("quality", ["128", "320"])
@pytest.mark.parametrize("source_format", ["m4a", "mp3"])
def test_explicit_output_bitrate_is_applied_even_to_mp3_sources(tmp_path, monkeypatch, quality, source_format):
    media = tmp_path / ("source." + source_format)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
        "sine=frequency=880:sample_rate=44100", "-t", "1", "-ac", "2",
        "-c:a", "aac" if source_format == "m4a" else "libmp3lame", "-b:a", "192k", str(media),
    ], check=True, capture_output=True)

    class LocalMedia(YoutubeDL):
        def __init__(self, params):
            super().__init__({**params, "enable_file_urls": True})

        def extract_info(self, url, download=True, *args, **kwargs):
            return self.process_ie_result({
                "id": "BVTEST", "title": "Synthetic", "url": media.as_uri(), "ext": source_format,
                "acodec": "aac" if source_format == "m4a" else "mp3", "vcodec": "none",
                "webpage_url": url, "extractor": "fixture", "extractor_key": "Fixture",
            }, download=download)

    monkeypatch.setattr("yt_dlp.YoutubeDL", LocalMedia)
    destination = tmp_path / "music"
    result = download({"destination": str(destination), "audio_format": "mp3", "audio_quality": quality,
        "socket_timeout": 10, "track": {"url": "https://www.bilibili.com/video/BVTEST"}})
    assert result["files"] == [f"mp3/{quality}/Synthetic [BVTEST].mp3"]
    decoded = subprocess.run([ffmpeg, "-hide_banner", "-i", str(destination / result["files"][0]),
        "-f", "null", "-"], check=True, capture_output=True, text=True)
    assert f"{quality} kb/s" in decoded.stderr
