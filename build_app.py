"""Build on the target OS from an allowlisted, private-data-free staging tree."""
from __future__ import annotations

import argparse
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from bilisong import __version__

SOURCE_FILES = ("main.py", "build_app.py", "requirements.txt", "requirements-dev.txt",
                "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md",
                "CONTRIBUTING.md", "SECURITY.md", ".gitignore")
SOURCE_DIRS = ("bilisong", "assets", "docs", "scripts", "tests", ".github", "licenses")

SPEC = '''# Generated in an isolated staging directory; never commit this file.
import sys
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas, binaries, hiddenimports = [], [], ['bilisong.worker', 'bilisong.music', 'bilisong.smoke']
for package in ('yt_dlp', 'imageio_ffmpeg'):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports
datas += copy_metadata('yt-dlp')
datas += [({notices}, 'notices'), ({licenses}, 'notices/licenses')]
a = Analysis(
    ['main.py'], pathex=['.'], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={{}},
    runtime_hooks=[], excludes=['tkinter', 'pytest'], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='BiliSong',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=(sys.platform == 'win32'), hide_console='hide-early',
    disable_windowed_traceback=False, argv_emulation=False,
    icon={icon}, target_arch=None, codesign_identity=None, entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='BiliSong')
if sys.platform == 'darwin':
    app = BUNDLE(
        coll, name='BiliSong.app', icon={icon},
        bundle_identifier='org.bilisong.desktop',
        info_plist={{
            'CFBundleShortVersionString': {version},
            'NSAppleEventsUsageDescription': 'BiliSong adds downloaded audio to your Music library when you enable automatic import.',
        }},
    )
'''


def stage_source(root: Path, stage: Path) -> None:
    stage.mkdir(parents=True, exist_ok=True)
    for name in SOURCE_FILES:
        shutil.copy2(root / name, stage / name)
    for name in SOURCE_DIRS:
        shutil.copytree(root / name, stage / name, ignore=shutil.ignore_patterns(
            '__pycache__', '*.pyc', '.DS_Store', '*.log'), dirs_exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', action='store_true', help='Create a versioned release ZIP')
    args = parser.parse_args()
    if sys.platform not in {'darwin', 'win32'}:
        parser.error('Build on macOS or Windows. Cross-compiling is not supported.')
    root = Path(__file__).resolve().parent
    dist = root / 'dist'
    with tempfile.TemporaryDirectory(prefix='bilisong-build-') as temporary:
        stage = Path(temporary) / 'source'
        native_dist = Path(temporary) / 'dist'
        stage_source(root, stage)
        subprocess.run([sys.executable, 'scripts/collect_licenses.py'], cwd=stage, check=True)
        icon = 'assets/BiliSong.icns' if sys.platform == 'darwin' else 'assets/BiliSong.ico'
        spec = stage / 'BiliSong.spec'
        spec.write_text(SPEC.format(icon=repr(icon), version=repr(__version__),
                                   notices=repr('THIRD_PARTY_NOTICES.md'),
                                   licenses=repr('licenses')), encoding='utf-8')
        subprocess.run([
            sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
            '--distpath', str(native_dist), '--workpath', str(Path(temporary) / 'build'), str(spec),
        ], cwd=stage, check=True)
        name = 'BiliSong.app' if sys.platform == 'darwin' else 'BiliSong'
        dist.mkdir(exist_ok=True)
        built = native_dist / name
        if (dist / name).exists():
            backup = root / 'app-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup.mkdir(parents=True)
            shutil.move(str(dist / name), backup / name)
        shutil.copytree(built, dist / name, symlinks=True)
        if args.archive:
            release = Path(temporary) / 'release'
            release.mkdir()
            shutil.copytree(built, release / built.name, symlinks=True)
            for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
                shutil.copy2(stage / name, release / name)
            shutil.copytree(stage / 'licenses', release / 'licenses')
            shutil.copytree(stage / 'docs', release / 'docs')
            shutil.copy2(stage / 'CHANGELOG.md', release / 'CHANGELOG.md')
            target = f"BiliSong-{__version__}-{'macOS' if sys.platform == 'darwin' else 'Windows'}-{platform.machine().lower()}"
            archive = dist / (target + '.zip')
            if sys.platform == 'darwin':
                subprocess.run(['/usr/bin/ditto', '-c', '-k', '--keepParent', '--norsrc',
                                str(release), str(archive)], check=True)
            else:
                shutil.make_archive(str(dist / target), 'zip', release)
            print(f'Release archive: {archive.name}')
    print('Built BiliSong for ' + platform.system())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
