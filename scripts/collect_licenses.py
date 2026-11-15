"""Collect exact installed dependency notices without host filesystem paths."""
from importlib import metadata
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

import imageio_ffmpeg


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / 'licenses' / 'dependencies'
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    versions = []
    for package in ('PySide6-Essentials', 'shiboken6', 'yt-dlp', 'imageio-ffmpeg',
                    'pyinstaller', 'altgraph', 'packaging', 'setuptools',
                    'certifi', 'brotli', 'mutagen', 'pycryptodomex', 'requests', 'urllib3',
                    'charset-normalizer', 'idna', 'websockets'):
        try:
            dist = metadata.distribution(package)
        except metadata.PackageNotFoundError:
            continue
        versions.append(f'{package}=={dist.version}')
        for file in dist.files or []:
            if not any(word in str(file).lower() for word in ('license', 'copying', 'copyright')):
                continue
            source = Path(dist.locate_file(file))
            if not source.is_file() or source.suffix.lower() in {'.py', '.pyc', '.pyo', '.so', '.dll', '.dylib'}:
                continue
            # Relative, neutral names; no wheel RECORD or installation paths.
            target = output / package / str(file)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        python_license = Path(sys.base_prefix) / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('Python license text not found; release packaging stopped')
    shutil.copyfile(python_license, output / 'Python-LICENSE.txt')
    shutil.copyfile(root / 'assets/fonts/OFL.txt', output / 'NotoSansSC-OFL.txt')
    (output / 'VERSIONS.txt').write_text('\n'.join(versions) + '\n', encoding='utf-8')
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    records = []
    for option in ('-version', '-L'):
        completed = subprocess.run([ffmpeg, option], capture_output=True, text=True,
                                   encoding='utf-8', errors='replace', check=True, timeout=30)
        records.append(completed.stdout + completed.stderr)
    records.append('SHA-256: ' + hashlib.sha256(Path(ffmpeg).read_bytes()).hexdigest())
    (root / 'licenses' / 'FFmpeg-build.txt').write_text('\n'.join(records), encoding='utf-8')
    print('Collected dependency licenses and converter provenance.')


if __name__ == '__main__':
    main()
