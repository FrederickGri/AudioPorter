"""Fetch the build-time UI font from its pinned, checksum-verified source."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.request import urlopen


def main():
    root = Path(__file__).resolve().parents[1]
    directory = root / 'assets' / 'fonts'
    manifest = json.loads((directory / 'font.json').read_text(encoding='utf-8'))
    target = directory / 'NotoSansSC.ttf'
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == manifest['sha256']:
        print('Interface font verified.')
        return
    with urlopen(manifest['url'], timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != manifest['sha256']:
        raise RuntimeError('Interface font checksum does not match the pinned source.')
    descriptor, temporary = tempfile.mkstemp(prefix='font-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('Downloaded and verified the interface font.')


if __name__ == '__main__':
    main()
