"""Bake the analysis into one self-contained HTML file.

Everything -- CSS, JS and the data itself -- is inlined, so the page works from
file:// with no server and no network. That also sidesteps the fetch()/CORS
problem the old two-file viewer had.
"""
import json
import os
import re
import sys

PLACEHOLDER = re.compile(r'__(TITLE|CSS|JS|DATA)__')


def asset_dir():
    """Where the bundled assets live -- inside the PyInstaller bundle or next to the source."""
    base = getattr(sys, '_MEIPASS', None)
    if base:
        return os.path.join(base, 'assets')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')


def _read(name):
    with open(os.path.join(asset_dir(), name), encoding='utf-8') as f:
        return f.read()


def write(dataset, path, title='WARNO Replay Analyzer'):
    # `</` would close the <script> early; \/ is a legal JSON escape
    payload = json.dumps(dataset, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    parts = {'TITLE': title, 'CSS': _read('viewer.css'), 'JS': _read('viewer.js'), 'DATA': payload}
    # one pass, so a placeholder appearing inside substituted text is left alone
    html = PLACEHOLDER.sub(lambda m: parts[m.group(1)], _read('viewer.html'))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return path
