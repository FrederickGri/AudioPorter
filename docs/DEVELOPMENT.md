# Development

English | [简体中文](DEVELOPMENT.zh-CN.md)

## Run from source

Use Python 3.12–3.14; release CI uses 3.12. Run these commands from the repository root.
Runtime and top-level build dependencies are pinned.

macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/fetch_font.py
.venv/bin/python main.py
```

Windows PowerShell (activation is not required):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/fetch_font.py
.\.venv\Scripts\python.exe main.py
```

The interface uses PySide6, media extraction uses yt-dlp, and audio conversion
uses the FFmpeg binary supplied by imageio-ffmpeg. PyInstaller creates the native
release packages, which include the runtime and converter. Java and BilibiliDown
are not dependencies.

Run `python scripts/fetch_font.py` once before source launches or tests. It fetches
Noto Sans SC from a pinned upstream commit and verifies SHA-256. The font binary
is excluded from Git and included in native app packages; the build script fetches
it automatically when needed. Packaged apps need no font download at runtime.

## Tests and packaging

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python build_app.py --archive
.venv/bin/python scripts/check_package.py
.venv/bin/python scripts/privacy_audit.py
```

On Windows, replace `.venv/bin/python` with `.\.venv\Scripts\python.exe`.
After building, open `dist/AudioRaven.app` on macOS or
`dist/AudioRaven/AudioRaven.exe` on Windows. Keep the Windows executable together
with its `_internal` directory.

Tests cover local queues, retries, timeouts, cancellation, conversion, and input
validation using synthetic media and fake network boundaries.

Run these commands with the virtual environment's Python shown above. The privacy
source check requires the intended upload files to be staged in
Git. To check a binary, use `python scripts/privacy_audit.py --tree dist/AudioRaven.app`
on macOS or `--tree dist/AudioRaven` on Windows. Test the extracted ZIP too.

PyInstaller is not a cross-compiler. Windows builds on Windows, Intel Mac builds
on Intel, and Apple Silicon builds on Apple Silicon. `build_app.py` creates an
isolated source copy, collects dependency notices, writes a temporary spec, and
builds a standalone directory. macOS wraps it in an app bundle. Windows uses a
hidden console bootloader so redirected UTF-8 worker streams remain available.
No installer, administrator access, Python, or separate FFmpeg is needed to run
the extracted release.

`main.py --worker` is the private JSON subprocess protocol. `--smoke-test` opens
a clean GUI, makes synthetic audio, and tests the worker without real account
settings or network activity. The smoke report includes only version/check
results; its screenshot uses empty account fields and a temporary destination.

Qt/PySide6 remain separate shared libraries. To experiment with compatible LGPL
library modifications, replace the corresponding unpacked Qt/PySide library
files, or rebuild from source using modified libraries in your environment.
If changing a Mac bundle invalidates its ad-hoc signature, use the standard
local development signing process before running your modified build. No
proprietary AudioRaven signing key is needed to rebuild it.

Windows Job Objects are attached before a worker receives configuration. If
attaching fails, the app terminates that worker and reports the error instead of
starting an unsupervised converter. This may matter under restrictive managed
desktop policies.

If a Bilibili site change breaks extraction, update the pinned yt-dlp version in
`requirements.txt`, install it, run the native checks, and rebuild. Upstream
reference: [yt-dlp documentation](https://github.com/yt-dlp/yt-dlp#readme).
