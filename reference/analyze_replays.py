#!/usr/bin/env python3
"""WARNO Replay Analyzer -- scans .rpl3 replays and writes data.json for the web viewer.

Usage:
    python analyze_replays.py [folder ...] [-o data.json] [--data warno_data.json] [--pretty]

Replay layout (reverse-engineered, stable since release):
  * ESAV container; near the start a readable JSON header:
      {"game":{...}, "player_2":{...}, "player_4":{...}, ..., "ingamePlayerId":N}
  * binary command stream (ignored)
  * trailing {"result":{"Duration":"1211","Victory":"5"}} -- ABSENT when the match was aborted.

Victory is relative to the player who saved the replay (ingamePlayerId = index into the
player list in header order): 0/1/2 = total/major/minor defeat, 3 = draw,
4/5/6 = minor/major/total victory.

Deck strings are base64 bitstreams (same format the game/deck-builders use):
  [5-bit len + data] x4  -> eugen version, modded flag, division id, number of cards
  [5-bit fixed] x2       -> bit width of veterancy field, bit width of unit-id field
  then per card: veterancy, unit id, transport id (0 = none).

Numeric ids change between patches. Names come from the optional warno_data.json
mapping file ({"divisions": {"221": {"name": ...}}, "units": {"13": {"name": ..., "category": ...}}});
unknown ids are kept numeric and the viewer shows them as "#221".
"""
import argparse
import base64
import json
import os
import re
import sys
from datetime import datetime, timezone

RANKED_MARKER = 'DUEL'  # ranked 1v1 maps carry the _DUEL suffix in their internal name


# ---------------------------------------------------------------- file parsing

def find_json(data: bytes, marker: bytes, from_end: bool = False):
    """Extract the balanced JSON object starting at the first/last `marker`."""
    idx = data.rfind(marker) if from_end else data.find(marker)
    if idx < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(idx, len(data)):
        c = data[i]
        if in_str:
            if esc:
                esc = False
            elif c == 0x5C:  # backslash
                esc = True
            elif c == 0x22:  # quote
                in_str = False
            continue
        if c == 0x22:
            in_str = True
        elif c == 0x7B:  # {
            depth += 1
        elif c == 0x7D:  # }
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(data[idx:i + 1].decode('utf-8', 'replace'))
                except json.JSONDecodeError:
                    return None
    return None


def decode_deck(code: str):
    """Decode a WARNO deck string into {modded, divisionId, cards:[[xp, unitId, transportId]]}."""
    raw = base64.b64decode(code + '=' * (-len(code) % 4))
    bits = ''.join(f'{b:08b}' for b in raw)
    pos = 0

    def field():
        nonlocal pos
        n = int(bits[pos:pos + 5] or '0', 2)
        d = bits[pos + 5:pos + 5 + n]
        pos += 5 + n
        return d

    def fixed():
        nonlocal pos
        v = int(bits[pos:pos + 5] or '0', 2)
        pos += 5
        return v

    field()  # eugen format version
    modded = int(field() or '0', 2) == 1
    division = int(field() or '0', 2)
    ncards = int(field() or '0', 2)
    xw, iw = fixed(), fixed()
    cards = []
    if xw + iw > 0:
        while len(cards) < ncards and pos + xw + 2 * iw <= len(bits):
            xp = int(bits[pos:pos + xw] or '0', 2); pos += xw
            uid = int(bits[pos:pos + iw] or '0', 2); pos += iw
            tid = int(bits[pos:pos + iw] or '0', 2); pos += iw
            cards.append([xp, uid, tid])
    return {'modded': modded, 'divisionId': division, 'cards': cards}


MAP_RX = re.compile(r'^_?(\d+x\d+)_(.+?)(?:_(\d)vs\3)?(?:_(CONQ|DEST|BKD|CD))?(?:_(DUEL))?$', re.I)
MODES = {'CONQ': 'Conquest', 'DEST': 'Destruction', 'BKD': 'Breakthrough', 'CD': 'Closer Combat'}


def parse_map(raw: str):
    m = MAP_RX.match(raw or '')
    if not m:
        return {'raw': raw, 'name': (raw or '?').strip('_').replace('_', ' '), 'size': None, 'mode': None}
    return {
        'raw': raw,
        'name': m.group(2).replace('_', ' '),
        'size': m.group(1),
        'mode': MODES.get((m.group(4) or '').upper(), m.group(4)),
    }


def to_int(v, default=None):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def to_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_replay(path: str):
    with open(path, 'rb') as f:
        data = f.read()
    header = find_json(data, b'{"game"')
    if not header or 'game' not in header:
        raise ValueError('no game header found')
    game = header['game']
    result = find_json(data[-65536:], b'{"result"', from_end=True)

    # players, in header order
    player_keys = sorted((k for k in header if k.startswith('player')),
                         key=lambda k: to_int(re.sub(r'\D', '', k), 0))
    players = []
    for k in player_keys:
        p = header[k]
        deck = None
        code = p.get('PlayerDeckContent')
        if code:
            try:
                deck = decode_deck(code)
                deck['code'] = code
            except Exception:
                deck = {'code': code, 'error': True, 'divisionId': None, 'cards': []}
        players.append({
            'slot': to_int(re.sub(r'\D', '', k), None),
            'userId': str(p.get('PlayerUserId', '')),
            'name': p.get('PlayerName', '?'),
            'elo': to_float(p.get('PlayerElo')),
            'rank': to_int(p.get('PlayerRank')),
            'level': to_int(p.get('PlayerLevel')),
            'alliance': to_int(p.get('PlayerAlliance'), 0),
            'ai': to_int(p.get('PlayerIALevel'), 0) > 0,
            'deck': deck,
        })

    network = str(game.get('IsNetworkMode', '1')) == '1'
    if not network or any(p['ai'] for p in players):
        mtype = 'vs_ai'
    elif to_int(game.get('NbMaxPlayer'), 0) == 2 and RANKED_MARKER in (game.get('Map') or ''):
        mtype = 'ranked'
    else:
        mtype = 'casual'

    local = header.get('ingamePlayerId')
    local = to_int(local, -1)
    if not (0 <= local < len(players)):
        local = None

    victory = duration = winner = None
    if result and 'result' in result:
        victory = to_int(result['result'].get('Victory'))
        duration = to_int(result['result'].get('Duration'))
        if victory is not None and local is not None:
            la = players[local]['alliance']
            winner = 'draw' if victory == 3 else (la if victory > 3 else 1 - la)

    mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    return {
        'id': game.get('UniqueSessionId') or os.path.basename(path),
        'file': os.path.basename(path),
        'date': mtime.isoformat(timespec='seconds'),
        'version': str(game.get('Version', '')),
        'mods': game.get('ModList', '') or '',
        'map': parse_map(game.get('Map', '')),
        'type': mtype,
        'config': {
            'nbMaxPlayer': to_int(game.get('NbMaxPlayer')),
            'initMoney': to_int(game.get('InitMoney')),
            'scoreLimit': to_int(game.get('ScoreLimit')),
            'timeLimit': to_int(game.get('TimeLimit')),
            'incomeRate': game.get('IncomeRate'),
            'private': str(game.get('Private', '0')) == '1',
            'networkMode': network,
        },
        'result': {'present': result is not None, 'victoryRaw': victory,
                   'duration': duration, 'winnerAlliance': winner},
        'localPlayer': local,
        'players': players,
    }


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description='Scan WARNO .rpl3 replays into data.json')
    ap.add_argument('folders', nargs='*', default=['.'],
                    help='folders to scan recursively (default: current dir). '
                         'Tip: WARNO saves replays under Saved Games/EugenSystems/WARNO')
    ap.add_argument('-o', '--out', default='data.json')
    ap.add_argument('--data', default='warno_data.json',
                    help='optional id->name mapping file (divisions/units)')
    ap.add_argument('--pretty', action='store_true', help='indent output JSON')
    args = ap.parse_args()

    mapping = {'divisions': {}, 'units': {}}
    if os.path.exists(args.data):
        with open(args.data, encoding='utf-8') as f:
            m = json.load(f)
            mapping['divisions'] = m.get('divisions', {}) or {}
            mapping['units'] = m.get('units', {}) or {}
        print(f'Loaded mapping: {len(mapping["divisions"])} divisions, {len(mapping["units"])} units')

    files = []
    seen_paths = set()
    for folder in (args.folders or ['.']):
        for root, _dirs, names in os.walk(folder):
            for nm in names:
                if nm.lower().endswith('.rpl3'):
                    p = os.path.normcase(os.path.abspath(os.path.join(root, nm)))
                    if p not in seen_paths:
                        seen_paths.add(p)
                        files.append(os.path.join(root, nm))
    files.sort()
    print(f'Found {len(files)} replay files')

    matches, errors = [], []
    for path in files:
        try:
            matches.append(parse_replay(path))
        except Exception as e:
            errors.append((path, str(e)))

    # the same replay often exists in several folders (archives, backups) -- keep one copy
    seen, unique, dupes = {}, [], 0
    for m in matches:
        key = (m['id'], m['result']['duration'], len(m['players']))
        if key in seen:
            dupes += 1
            continue
        seen[key] = True
        unique.append(m)
    matches = unique
    matches.sort(key=lambda m: m['date'], reverse=True)

    # collect the id universe actually seen, attach known names
    div_ids, unit_ids = set(), set()
    for m in matches:
        for p in m['players']:
            d = p.get('deck') or {}
            if d.get('divisionId') is not None:
                div_ids.add(d['divisionId'])
            for c in d.get('cards', []):
                unit_ids.add(c[1])
                if c[2]:
                    unit_ids.add(c[2])
    divisions = {str(i): mapping['divisions'].get(str(i), {'name': None}) for i in sorted(div_ids)}
    units = {str(i): mapping['units'].get(str(i), {'name': None}) for i in sorted(unit_ids)}

    out = {
        'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'tool': 'warno-replay-analyzer/1.0',
        'sourceDirs': [os.path.abspath(f) for f in args.folders],
        'gameVersions': sorted({m['version'] for m in matches}),
        'divisions': divisions,
        'units': units,
        'matches': matches,
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2 if args.pretty else None)

    n = len(matches)
    ab = sum(1 for m in matches if not m['result']['present'])
    by = {t: sum(1 for m in matches if m['type'] == t) for t in ('ranked', 'casual', 'vs_ai')}
    print(f'Parsed {n}/{len(files)} replays -> {args.out}'
          f'  ({by["ranked"]} ranked, {by["casual"]} casual, {by["vs_ai"]} vs AI, {ab} aborted'
          + (f', {dupes} duplicates skipped' if dupes else '') + ')')
    named = sum(1 for d in divisions.values() if d.get('name'))
    print(f'Division ids seen: {len(divisions)} ({named} named via {args.data});'
          f' unit ids seen: {len(units)}')
    if errors:
        print(f'{len(errors)} files failed:')
        for p, e in errors[:10]:
            print(f'  {p}: {e}')

    # serve the viewer folder with:  python -m http.server  (fetch() needs http://, not file://)


if __name__ == '__main__':
    main()
