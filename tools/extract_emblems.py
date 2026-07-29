"""Extract division emblems from an installed WARNO into src/assets/emblems.json.

The emblems are cooked textures inside Eugen's packed archives, so unlike the
name tables they cannot be read from the modding template. This runs at build
time and bakes the result into the .exe; re-run it after a patch that adds
divisions.

    pip install zstandard
    python tools/extract_emblems.py [--game-dir ...] [--size 64]

Chain: Divisions.ndf gives each division an EmblemTexture, DivisionTextures.ndf
maps that to a .png asset path, and the archives hold it as <name>.tgv.
"""
import argparse
import base64
import glob
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'src'))

import gamedata          # noqa: E402
import warno_edat        # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), 'src', 'assets', 'emblems.json')
Z_TEXTURES = 'GameData/Generated/UserInterface/Textures/DivisionTextures.ndf'
EMBLEM_DIR = 'Division/Emblem/'

TEXTURE_RX = re.compile(
    r'(\w+)\s+is\s+TUIResourceTexture_Common\s*\(\s*FileName\s*=\s*"([^"]*)"', re.S)


def emblem_files(game_dir):
    """Texture id -> asset basename, e.g. Texture_..._8th_infantry -> 8th_infantry."""
    with zipfile.ZipFile(os.path.join(game_dir, gamedata.BASE_ZIP)) as z:
        text = z.read(Z_TEXTURES).decode('utf-8', 'replace')
    out = {}
    for m in TEXTURE_RX.finditer(text):
        name = m.group(2).replace('\\', '/').rsplit('/', 1)[-1]
        out[m.group(1)] = os.path.splitext(name)[0]
    return out


def _version_of(path, base):
    """Sort key for a data folder: Data/PC/<from>/<to> patches the <to> version."""
    parts = [int(p) for p in os.path.relpath(path, base).split(os.sep)[:-1] if p.isdigit()]
    return parts[-1] if parts else 0


def collect_textures(game_dir, log=print):
    """basename -> raw .tgv bytes, taking the newest version of each."""
    base = os.path.join(game_dir, 'Data', 'PC')
    archives = [p for p in glob.glob(os.path.join(base, '**', '*.dat'), recursive=True)
                if os.sep + 'DecorsSets' + os.sep not in p and os.sep + 'Maps' + os.sep not in p]
    archives.sort(key=lambda p: _version_of(p, base))

    found = {}
    for path in archives:
        try:
            archive = warno_edat.EDat(path)
        except (ValueError, OSError):
            continue
        try:
            hits = archive.find(EMBLEM_DIR, '.tgv')
            if hits:
                log('  %-44s %3d emblems' % (os.path.relpath(path, base), len(hits)))
            for key in hits:
                name = os.path.splitext(key.replace('\\', '/').rsplit('/', 1)[-1])[0]
                try:
                    found[name] = archive.read(key)      # later version wins
                except ValueError as e:
                    log('    ! %s: %s' % (name, e))
        finally:
            archive.close()
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game-dir')
    ap.add_argument('--size', type=int, default=64,
                    help='shortest acceptable mip size in px (default 64)')
    ap.add_argument('-o', '--out', default=OUT)
    args = ap.parse_args()

    game = args.game_dir or gamedata.find_game_dir()
    if not game or not gamedata.is_game_dir(game):
        print('WARNO install not found. Pass --game-dir.')
        return 2
    print('Reading %s' % game)

    wanted = emblem_files(game)
    print('%d division textures referenced by the game' % len(wanted))

    textures = collect_textures(game)
    print('%d emblem textures found in the archives' % len(textures))

    images, skipped = {}, []
    for texture_id, basename in sorted(wanted.items()):
        blob = textures.get(basename)
        if blob is None:
            skipped.append(basename)
            continue
        try:
            tex = warno_edat.Texture(blob)
            level = tex.best_mip(args.size)
            width, height = tex.mip_size(level)
            png = warno_edat.write_png(tex.rgba(level), width, height)
        except Exception as e:
            skipped.append('%s (%s)' % (basename, e))
            continue
        images[texture_id] = base64.b64encode(png).decode('ascii')

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump({'size': args.size, 'images': images}, f, separators=(',', ':'))

    print('%d emblems written -> %s (%.0f KB)'
          % (len(images), args.out, os.path.getsize(args.out) / 1024))
    if skipped:
        print('%d not found: %s' % (len(skipped), ', '.join(sorted(skipped)[:12])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
