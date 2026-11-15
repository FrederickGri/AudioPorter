# Compatibility and troubleshooting

## What is verified

The workflow runs the test suite separately on Windows Server 2022 (x64), macOS
15 (Apple Silicon), and macOS 15 Intel. Windows Server CI is useful evidence for
Windows desktop compatibility, but is not an interactive Windows 11 acceptance
test. Windows 11 x64 is the intended desktop target. CI also builds each native
package and runs the packaged executable to verify the GUI, both audio codecs,
and the frozen subprocess protocol. Tests use synthetic media and fake network
boundaries; they do not prove a real account's folder is accessible.

No app can guarantee every machine or every future Bilibili response. Release
only when native checks pass, and record any remaining manual checks in the
release notes. Windows Stop/timeout uses a kill-on-close Job Object to terminate
the worker and its FFmpeg descendants. macOS uses a process group.

## Common problems

| Symptom | What to check |
| --- | --- |
| Windows app will not start | Extract the entire ZIP to a writable local directory. Keep `_internal` next to the EXE. Confirm 64-bit Intel/AMD Windows. Review the publisher warning without disabling system protection. |
| Mac app will not start | Select the correct Intel or Apple Silicon package. This release targets macOS 15+. The build is not notarized; consult macOS Privacy & Security for the system's explanation. |
| Cannot read browser cookies | Close the browser and retry, or choose a Netscape-format cookies file from your own account. Browser encryption and enterprise policies can prevent direct access. |
| Folder scan fails | Use a specific folder URL including `fid=`, check your network, and authenticate if the folder requires it. |
| Some items fail | Removed/private/region-restricted media may be unavailable. Retry only after addressing the reported cause. |
| Long path or permission error on Windows | Choose a short writable destination, such as a folder within your Music directory. Deeply nested folders and old filesystem limits can still fail. |
| Apple Music import fails | macOS only: allow Automation access to Music, then retry. Downloaded files remain available. Windows has no automatic import. |
| Site behavior changes | Update the pinned yt-dlp version, run tests on every target, then rebuild. |

## Desktop acceptance checks

Before describing a release as tested on Windows 11, open the extracted ZIP on
an actual Windows 11 x64 desktop; preview an authorized public folder; save MP3
and M4A into a path containing spaces and Chinese characters; stop an active
conversion; retry a failed entry; restart the app; and open the destination.
Test browser-cookie access separately because it depends on each browser.
