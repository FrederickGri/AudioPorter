# Privacy and publication

English | [简体中文](PRIVACY.zh-CN.md)

AudioPorter connects to Bilibili and the media hosts selected by its extractor to
list and download requested content. Optional cookies are sent to the relevant
site as authentication. No analytics, remote configuration, or automatic crash
uploads are implemented. Updating source dependencies through pip contacts the
package registry; it is a development action, not an in-app background update.

## Local records

- Qt settings store the last input URL, destination, format, quality, and UI
  preferences. On Windows this normally uses the current user's registry; on
  macOS it uses the user's preferences store. Cookie file paths may be saved;
  cookie contents and passwords are not stored in Qt settings.
- Destination folders contain `.audioporter-completed.json`, `.audioporter-report.json`,
  `.audioporter-work/`, and, when used, `.audioporter-music.json`. These may reveal video
  titles, links, file paths, and local Music identifiers.
- Temporary copies of cookie files are created for isolated workers and removed
  when the supervising operation finishes. Forced termination of the entire app
  or an OS crash may bypass normal cleanup.
- Local settings and download/Music records from the earlier BiliSong name can
  be reused on this machine. Migration does not upload those records.

## What goes to GitHub

Only reviewed source, tests, icons, documentation, license texts, and workflows
belong in Git. Binaries belong in Releases or Actions artifacts. Exclude cookies,
downloaded media, personal reports, settings, virtual environments, `.DS_Store`,
logs, generated specs, build folders, backups, and personal screenshots.

Packaging copies a fixed list of project components into temporary staging and
rebuilds there. Existing app bundles are not reused. The privacy guard scans
staged source and extracted release files, including embedded compressed Python
modules, for the current host's username, home directory, hostname and common
credential patterns. It prints filenames and finding types, not matched secrets.
This automated scan complements review; it is not a guarantee that every kind
of private information can be recognized.

Use a generic contributor name and non-personal commit address for publication.
GitHub still publicly associates a public repository and uploads with the GitHub
account that owns them. Review logs and screenshots before sharing them; redacted
activity messages do not make every local diagnostic safe to publish.
