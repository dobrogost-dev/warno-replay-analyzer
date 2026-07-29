"""WARNO Replay Analyzer -- scan .rpl3 replays, build a report, open it.

Double-click the .exe and it finds your replay folder, reads every replay,
resolves division and unit names from your WARNO install, writes a
self-contained HTML report next to itself and opens it in your browser.
"""
import argparse
import json
import os
import sys
import time
import traceback
import webbrowser
from datetime import datetime, timezone

import gamedata
import replay
import report

VERSION = '1.0'
REPORT_NAME = 'WARNO Replay Report.html'


def app_dir():
    """Folder the program lives in (the .exe when frozen)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fallback_dir():
    root = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(root, 'WARNO Replay Analyzer')


def writable(folder):
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, '.write-test')
        with open(probe, 'w'):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


def build(folders, names, log=print):
    """Parse every replay under `folders` into the dataset the viewer reads."""
    files = replay.find_replays(folders)
    log('Found %d replay file%s' % (len(files), '' if len(files) == 1 else 's'))

    matches, errors = [], []
    started = time.time()
    for i, path in enumerate(files, 1):
        if len(files) > 200 and i % 250 == 0:
            log('  ...%d/%d' % (i, len(files)))
        try:
            matches.append(replay.parse(path))
        except Exception as e:
            errors.append({'file': os.path.basename(path), 'error': str(e)})

    # the same replay often sits in several folders (backups, shared copies)
    seen, unique, dupes = set(), [], 0
    for m in matches:
        key = (m['id'], m['result']['duration'], len(m['players']))
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        unique.append(m)
    unique.sort(key=lambda m: m['date'], reverse=True)

    # keep only the ids these replays actually reference
    div_ids, unit_ids = set(), set()
    for m in unique:
        for p in m['players']:
            deck = p.get('deck') or {}
            if deck.get('divisionId') is not None:
                div_ids.add(str(deck['divisionId']))
            for card in deck.get('cards', []):
                unit_ids.add(str(card[1]))
                if card[2]:
                    unit_ids.add(str(card[2]))

    divisions = {i: names['divisions'][i] for i in sorted(div_ids) if i in names['divisions']}
    units = {i: names['units'][i] for i in sorted(unit_ids) if i in names['units']}

    counts = {t: sum(1 for m in unique if m['type'] == t) for t in ('ranked', 'casual', 'vs_ai')}
    aborted = sum(1 for m in unique if not m['result']['present'])
    log('Parsed %d/%d replays in %.1fs  (%d ranked, %d casual, %d vs AI, %d aborted%s)'
        % (len(matches), len(files), time.time() - started, counts['ranked'], counts['casual'],
           counts['vs_ai'], aborted, ', %d duplicates skipped' % dupes if dupes else ''))
    log('Named %d/%d divisions and %d/%d units seen in these decks'
        % (len(divisions), len(div_ids), len(units), len(unit_ids)))
    if errors:
        log('%d file%s could not be read:' % (len(errors), '' if len(errors) == 1 else 's'))
        for e in errors[:10]:
            log('  - %s: %s' % (e['file'], e['error']))
        if len(errors) > 10:
            log('  ... and %d more' % (len(errors) - 10))

    return {
        'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'tool': 'warno-replay-analyzer/%s' % VERSION,
        'sourceDirs': [os.path.abspath(f) for f in folders],
        'gameVersions': sorted({m['version'] for m in unique if m['version']}),
        'divisions': divisions,
        'units': units,
        'matches': unique,
        'errors': errors,
        'localSteamIds': gamedata.local_steam_ids(),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='WARNO Replay Analyzer',
        description='Scan WARNO .rpl3 replays and open an interactive report in your browser.')
    ap.add_argument('folders', nargs='*',
                    help='folders (or single .rpl3 files) to scan; default: your WARNO save folder')
    ap.add_argument('-o', '--out', help='where to write the report (default: next to this program)')
    ap.add_argument('--json', action='store_true', help='also write data.json alongside the report')
    ap.add_argument('--no-open', action='store_true', help='do not launch the browser')
    ap.add_argument('--game-dir', help='WARNO install folder, if it is not auto-detected')
    ap.add_argument('--refresh-data', action='store_true',
                    help='re-read unit/division names from the game, ignoring the cache')
    ap.add_argument('--version', action='version', version='WARNO Replay Analyzer ' + VERSION)
    args = ap.parse_args(argv)

    print('WARNO Replay Analyzer %s' % VERSION)
    print('-' * 58)

    folders = args.folders or (gamedata.steam_replay_dirs() + replay.default_folders())
    if not folders:
        print('No replay folder found.')
        print('WARNO keeps replays in Steam Cloud and in your save folder:')
        print('  %s' % os.path.join('<Steam>', 'userdata', '<account>', gamedata.WARNO_APPID, 'remote'))
        print('  %s' % os.path.join(os.path.expanduser('~'), 'Saved Games', 'EugenSystems', 'WARNO'))
        print('Pass a folder explicitly, or drag one onto this program.')
        return 2
    for f in folders:
        print('Scanning %s' % os.path.abspath(f))

    bundled = os.path.join(report.asset_dir(), 'warno_data.json')
    names, how = gamedata.load(game_dir=args.game_dir, bundled=bundled,
                               refresh=args.refresh_data, log=print)
    print('Unit/division names: %s' % how)

    dataset = build(folders, names)
    dataset['dataSource'] = how

    out_dir = args.out or app_dir()
    if not writable(out_dir):
        out_dir = fallback_dir()
        os.makedirs(out_dir, exist_ok=True)
        print('Cannot write next to the program, using %s' % out_dir)

    path = report.write(dataset, os.path.join(out_dir, REPORT_NAME))
    print('Report: %s' % path)
    if args.json:
        json_path = os.path.join(out_dir, 'data.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(dataset, f, ensure_ascii=False, indent=1)
        print('Data:   %s' % json_path)

    if not args.no_open:
        webbrowser.open('file:///' + path.replace('\\', '/'))
        print('Opening in your browser...')
    return 0


def run():
    interactive = not sys.argv[1:] and getattr(sys, 'frozen', False)
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1
    if interactive or code not in (0, None):
        try:
            input('\nPress Enter to close...')
        except EOFError:
            pass
    return code


if __name__ == '__main__':
    sys.exit(run() or 0)
