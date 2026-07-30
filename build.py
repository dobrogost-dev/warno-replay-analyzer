"""Build dist/WARNO Replay Analyzer.exe (one file, no installer, no runtime deps).

    pip install pyinstaller
    python build.py

The viewer assets and the offline name snapshot are packed into the exe; at run
time report.asset_dir() finds them under sys._MEIPASS.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')
NAME = 'WARNO Replay Analyzer'


def main():
    if not os.path.exists(os.path.join(SRC, 'assets', 'warno_data.json')):
        print('src/assets/warno_data.json is missing -- run tools/make_snapshot.py first.')
        return 2

    for stale in ('build', 'dist'):
        shutil.rmtree(os.path.join(HERE, stale), ignore_errors=True)

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile', '--console', '--clean', '--noconfirm',
        '--name', NAME,
        '--distpath', os.path.join(HERE, 'dist'),
        '--workpath', os.path.join(HERE, 'build'),
        '--specpath', os.path.join(HERE, 'build'),
        '--paths', SRC,
        '--add-data', os.path.join(SRC, 'assets') + os.pathsep + 'assets',
        # trim what nothing here imports -- but leave email/http/urllib alone,
        # avatar fetching goes through urllib.request and it pulls both in
        '--exclude-module', 'tkinter', '--exclude-module', 'unittest',
        '--exclude-module', 'pydoc',
        os.path.join(SRC, 'main.py'),
    ]
    print(' '.join(cmd))
    rc = subprocess.call(cmd)
    if rc:
        return rc

    exe = os.path.join(HERE, 'dist', NAME + '.exe')
    print('\nBuilt %s (%.1f MB)' % (exe, os.path.getsize(exe) / 1e6))
    return 0


if __name__ == '__main__':
    sys.exit(main())
