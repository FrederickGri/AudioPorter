"""Run offline smoke checks against the native packaged executable."""
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
executable = root / 'dist' / ('AudioRaven.app/Contents/MacOS/AudioRaven' if sys.platform == 'darwin'
                            else 'AudioRaven/AudioRaven.exe')
report = root / 'dist' / 'smoke-result.json'
result = subprocess.run([str(executable), '--smoke-test', str(report)], timeout=120)
if result.returncode or not report.is_file() or not json.loads(report.read_text(encoding='utf-8')).get('ok'):
    raise SystemExit('Packaged app smoke checks failed; do not publish this build.')
print('Packaged GUI, FFmpeg MP3/M4A, and frozen worker protocol passed.')
