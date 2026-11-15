# Third-party notices

English | [简体中文](THIRD_PARTY_NOTICES.zh-CN.md)

AudioRaven's original source is MIT licensed. Dependencies retain their own terms;
the MIT license does not relicense Python, Qt, FFmpeg, or any other dependency.

| Component | Use | License / upstream source |
| --- | --- | --- |
| CPython | Bundled interpreter | PSF and incorporated notices; https://www.python.org/downloads/source/ |
| PySide6 Essentials / Shiboken6 / Qt | Dynamically loaded desktop UI | LGPL v3 / GPL alternatives; https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://download.qt.io/archive/qt/ |
| yt-dlp | Bilibili extraction and download | Unlicense, with separately licensed bundled code; https://github.com/yt-dlp/yt-dlp |
| imageio-ffmpeg | Locate bundled converter | BSD-2-Clause; https://github.com/imageio/imageio-ffmpeg |
| FFmpeg and enabled libraries | Separate converter executable | Build-specific LGPL/GPL terms; https://ffmpeg.org/legal.html |
| PyInstaller bootloader | Application launcher | GPL with the PyInstaller bootloader exception; https://github.com/pyinstaller/pyinstaller |

Exact installed versions and license texts are collected into `licenses/` during
packaging, including metadata notices from transitive dependencies. Qt remains
dynamically loaded. Users may replace compatible Qt/PySide libraries in the
unpacked application and may reverse engineer the LGPL components to debug their
modifications. Rebuild instructions are in [Development](docs/DEVELOPMENT.md).

FFmpeg is invoked as a separate executable; it is not linked into AudioRaven's own
code. imageio-ffmpeg 0.8.1 pins each platform binary, download URL and checksum in
its [binary manifest](https://github.com/imageio/imageio-ffmpeg/blob/v0.8.1/tools/ffmpeg-sources.json).
Build scripts and source availability are provided by the manifest's upstream
build projects. The release staging license collector records the actual binary
version, build configuration, license output, and checksum in `licenses/FFmpeg-build.txt`.
The binary's applicable license, including GPL when enabled, must be preserved.

Release maintainers must retain access to the matching corresponding FFmpeg and
enabled-library sources and build scripts when redistributing the converter.
See the release checklist before publishing binaries. An upstream link alone
must not be treated as a substitute for required corresponding-source access.
