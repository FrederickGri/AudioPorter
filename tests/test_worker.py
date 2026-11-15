import errno

import pytest

from audioporter.worker import base_options, flatten_entries, promote_file, scan


def test_flatten_exhausts_nested_lazy_pages():
    visited = []

    def pages():
        for page in range(4):
            visited.append(page)
            yield {"_type": "playlist", "entries": (
                {"id": str(page * 30 + i)} for i in range(30)
            )}

    entries = list(flatten_entries({"_type": "playlist", "entries": pages()}))
    assert visited == [0, 1, 2, 3]
    assert len(entries) == 120 and entries[-1]["id"] == "119"


def test_unavailable_entry_is_not_silently_dropped():
    with pytest.raises(RuntimeError, match="unavailable"):
        list(flatten_entries({"entries": [{"id": "one"}, None, {"id": "three"}]}))


def test_scan_consumes_lazy_pages_and_deduplicates_links(monkeypatch):
    observed = []
    options = []

    class FakeDownloader:
        def __init__(self, opts):
            options.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            assert url == "https://www.bilibili.com/medialist/detail/ml123"
            assert download is False

            def entries():
                for i in range(95):
                    observed.append(i)
                    yield {"_type": "url", "id": f"BV{i}", "url": f"https://www.bilibili.com/video/BV{i}"}
                yield {"_type": "url", "id": "BV0", "url": "https://www.bilibili.com/video/BV0"}

            return {"_type": "playlist", "title": "Folder", "entries": entries()}

    monkeypatch.setattr("yt_dlp.YoutubeDL", FakeDownloader)
    result = scan({"url": "https://space.bilibili.com/1/favlist?fid=123", "socket_timeout": 30})
    assert observed == list(range(95))
    assert len(result["tracks"]) == 95
    assert result["tracks"][-1]["id"] == "BV94"
    assert options[0]["extract_flat"] == "in_playlist"
    assert options[0].get("playlistend") is None


def test_request_options_do_not_multiply_supervisor_retry_budget():
    options = base_options({"socket_timeout": 17, "browser": "chrome"})
    assert options["socket_timeout"] == 17
    assert options["cookiesfrombrowser"] == ("chrome",)
    assert options["skip_unavailable_fragments"] is False
    assert options["ignoreerrors"] is False
    assert options["retries"] == options["fragment_retries"] == options["extractor_retries"] == 0


def test_publishing_preserves_existing_file_with_same_name(tmp_path):
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    staging.mkdir()
    output.mkdir()
    source = staging / "song.mp3"
    source.write_bytes(b"new song")
    existing = output / "song.mp3"
    existing.write_bytes(b"old song")
    published = promote_file(source, output)
    assert published.name == "song (2).mp3"
    assert published.read_bytes() == b"new song"
    assert existing.read_bytes() == b"old song"


def test_publishing_reuses_identical_existing_output(tmp_path):
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    staging.mkdir()
    output.mkdir()
    source = staging / "song.mp3"
    source.write_bytes(b"same song")
    existing = output / "song.mp3"
    existing.write_bytes(b"same song")
    assert promote_file(source, output) == existing
    assert not source.exists()
    assert list(output.iterdir()) == [existing]


def test_publishing_works_on_filesystem_without_hardlinks(tmp_path, monkeypatch):
    source = tmp_path / "song.mp3"
    source.write_bytes(b"completed audio")

    def unsupported(*args):
        raise OSError(errno.EOPNOTSUPP, "not supported")

    monkeypatch.setattr("audioporter.worker.os.link", unsupported)
    target = promote_file(source, tmp_path / "output")
    assert target.read_bytes() == b"completed audio"
    assert not source.exists()
