"""Scan staged Git files or an extracted release without printing private matches.

Checks personal host identifiers in bytes and compressed Python archives. This
is a release guard, not a proof that arbitrary files are free of private data.
"""
from __future__ import annotations

import argparse
import getpass
import io
from pathlib import Path
import re
import socket
import subprocess
import sys
import types
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_NAMES = re.compile(r'(^|/)(\.env(?:\..*)?|cookies(?:[^/]*\.(?:txt|json|sqlite|db))?|[^/]*cookies\.txt|\.(?:audioporter|bilisong)-[^/]*|\.DS_Store|.*\.(?:pem|key|part|ytdl))$', re.I)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, help='Scan an extracted release tree')
    args = parser.parse_args()
    # Values are read only in memory; never persist them in a report or command.
    identifiers = [str(Path.home()), getpass.getuser(), socket.gethostname()]
    identifiers = [v for v in identifiers if len(v) >= 4 and v.lower() not in {'runner', 'admin', 'user', 'localhost'}]
    needles = [v.encode().lower() for v in identifiers]
    failures = set()

    def check(data, label):
        folded = data.lower()
        if any(needle in folded for needle in needles):
            failures.add(label + ' (host identifier)')
        if re.search(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=]{48,})', data):
            failures.add(label + ' (credential pattern)')

    def check_zip(data, label):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if name.endswith('/'):
                    continue
                body = archive.read(name)
                check(body, label + ':' + name)
                if body.startswith(b'PK\x03\x04'):
                    check_zip(body, label + ':' + name)

    if args.tree:
        base = args.tree.resolve()
        paths = [p for p in base.rglob('*') if p.is_file() and not p.is_symlink()]
    else:
        base = ROOT
        names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
        paths = [base / name for name in names if name]
    for path in paths:
        label = path.relative_to(base).as_posix()
        data = path.read_bytes()
        public_ca_bundle = (path.name == 'cacert.pem' and path.parent.name == 'certifi'
                            and b'-----BEGIN CERTIFICATE-----' in data and b'PRIVATE KEY' not in data)
        if PRIVATE_NAMES.search(label) and not public_ca_bundle:
            failures.add(label + ' (private filename)')
        check(data, label)
        if data.startswith(b'PK\x03\x04'):
            check_zip(data, label)
        if path.name in {'AudioPorter', 'AudioPorter.exe'}:
            from PyInstaller.archive.readers import CArchiveReader
            archive = CArchiveReader(str(path))
            for name, entry in archive.toc.items():
                if entry[-1] == 'z':
                    pyz = archive.open_embedded_archive(name)
                    for module in pyz.toc:
                        code = pyz.extract(module)
                        if isinstance(code, types.CodeType):
                            import marshal
                            check(marshal.dumps(code), label + ':' + module)
                elif entry[-1] not in {'o', 'd'}:
                    check(archive.extract(name), label + ':' + name)
    if failures:
        print('Privacy audit FAILED. Review these files locally:')
        print('\n'.join(sorted(failures)))
        return 1
    print(f'Privacy audit passed: {len(paths)} files; no detected host identifiers or credential patterns.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
