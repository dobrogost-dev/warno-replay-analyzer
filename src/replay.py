"""Read WARNO .rpl3 replays.

Layout (reverse-engineered, stable since release):
  * "ESAV" container; near the start a readable JSON header
      {"game":{...}, "player_2":{...}, "player_4":{...}, ..., "ingamePlayerId":N}
  * binary command stream (ignored)
  * trailing {"result":{"Duration":"1211","Victory":"5"}} -- ABSENT when the
    match was aborted or the recording was cut short.

`ingamePlayerId` indexes the player list in header order, so victory is read
relative to whoever saved the replay:
    0/1/2 = total/major/minor defeat, 3 = draw, 4/5/6 = minor/major/total victory

Deck strings are base64 bitstreams:
    [5-bit length + payload] x4  -> format version, modded flag, division id, card count
    [5-bit value] x2            -> bit width of the veterancy and unit-id fields
    then per card: veterancy, unit id, transport id (0 = none)
See gamedata.py for what those ids mean.
"""
import base64
import json
import os
import re
from datetime import datetime, timezone

MODES = {
    'CONQ': 'Conquest', 'DEST': 'Destruction', 'BKD': 'Breakthrough',
    'CD': 'Closer Combat', 'ASSAULT': 'Assault', 'SIEGE': 'Siege',
}
RANKED_MARKER = 'DUEL'  # ranked 1v1 maps carry the _DUEL suffix in their internal name

FILE_DATE_RX = re.compile(r'(\d{4})-(\d{2})-(\d{2})[_ ](\d{2})-(\d{2})(?:-(\d{2}))?')
MAP_RX = re.compile(r'^_?(\d+x\d+)_(.+)$')
SIZE_RX = re.compile(r'^(.*?)_(\d+)vs(\d+)$')
CAMEL_RX = re.compile(r'(?<=[a-z0-9])(?=[A-Z])')


class ReplayError(Exception):
    pass


# ---------------------------------------------------------------- primitives

def find_json(data, marker, from_end=False):
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
            elif c == 0x5C:      # backslash
                esc = True
            elif c == 0x22:      # quote
                in_str = False
            continue
        if c == 0x22:
            in_str = True
        elif c == 0x7B:          # {
            depth += 1
        elif c == 0x7D:          # }
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(data[idx:i + 1].decode('utf-8', 'replace'))
                except ValueError:
                    return None
    return None


def decode_deck(code):
    """Decode a deck string into {modded, divisionId, cards:[[xp, unitId, transportId]]}."""
    raw = base64.b64decode(code + '=' * (-len(code) % 4))
    bits = ''.join(format(b, '08b') for b in raw)
    pos = 0

    def field():
        nonlocal pos
        n = int(bits[pos:pos + 5] or '0', 2)
        payload = bits[pos + 5:pos + 5 + n]
        pos += 5 + n
        return payload

    def fixed():
        nonlocal pos
        v = int(bits[pos:pos + 5] or '0', 2)
        pos += 5
        return v

    version = int(field() or '0', 2)
    modded = int(field() or '0', 2) == 1
    division = int(field() or '0', 2)
    count = int(field() or '0', 2)
    xp_width, id_width = fixed(), fixed()

    cards = []
    if xp_width + id_width > 0:
        step = xp_width + 2 * id_width
        while len(cards) < count and pos + step <= len(bits):
            xp = int(bits[pos:pos + xp_width] or '0', 2)
            pos += xp_width
            unit = int(bits[pos:pos + id_width] or '0', 2)
            pos += id_width
            transport = int(bits[pos:pos + id_width] or '0', 2)
            pos += id_width
            cards.append([xp, unit, transport])
    return {'formatVersion': version, 'modded': modded, 'divisionId': division,
            'cards': cards, 'truncated': len(cards) < count}


def parse_map(raw):
    """`_2x3_BlackForestStorm_1vs1_CONQ_DUEL` -> readable name / size / mode."""
    raw = raw or ''
    out = {'raw': raw, 'name': raw.strip('_').replace('_', ' ') or '?',
           'size': None, 'mode': None, 'teams': None, 'ranked': RANKED_MARKER in raw.upper()}
    m = MAP_RX.match(raw)
    if not m:
        return out
    out['size'] = m.group(1)
    rest = m.group(2)

    tags = []
    while '_' in rest:
        head, _, tail = rest.rpartition('_')
        if tail.upper() not in MODES and tail.upper() != RANKED_MARKER:
            break
        tags.insert(0, tail.upper())
        rest = head

    size = SIZE_RX.match(rest)
    if size:
        rest = size.group(1)
        out['teams'] = int(size.group(2))

    out['name'] = CAMEL_RX.sub(' ', rest.replace('_', ' ')).strip()
    modes = [MODES[t] for t in tags if t in MODES]
    out['mode'] = ' · '.join(modes) or None
    return out


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


def _timestamp(path):
    """Prefer the date WARNO put in the filename; fall back to the file's mtime."""
    m = FILE_DATE_RX.search(os.path.basename(path))
    if m:
        y, mo, d, h, mi, s = (int(x or 0) for x in m.groups())
        try:
            return datetime(y, mo, d, h, mi, s), 'filename'
        except ValueError:
            pass
    return datetime.fromtimestamp(os.path.getmtime(path)), 'file date'


# ---------------------------------------------------------------- replay file

def parse(path):
    with open(path, 'rb') as f:
        data = f.read()

    header = find_json(data, b'{"game"')
    if not header or 'game' not in header:
        raise ReplayError('no game header found (not a WARNO replay?)')
    game = header['game']
    result = find_json(data[-65536:], b'{"result"', from_end=True)

    players = []
    for key in sorted((k for k in header if k.startswith('player')),
                      key=lambda k: to_int(re.sub(r'\D', '', k), 0)):
        raw = header[key]
        if not isinstance(raw, dict):
            continue
        deck, code = None, raw.get('PlayerDeckContent')
        if code:
            try:
                deck = decode_deck(code)
            except Exception:
                deck = {'divisionId': None, 'cards': [], 'error': True}
            deck['code'] = code
        avatar = str(raw.get('PlayerAvatar', ''))
        steam = re.search(r'(7656\d{13})', avatar)
        players.append({
            'slot': to_int(re.sub(r'\D', '', key)),
            'userId': str(raw.get('PlayerUserId', '')),
            'steamId': steam.group(1) if steam else '',
            'name': raw.get('PlayerName') or '?',
            # 0 means "not on the ladder yet", not "rated 0" -- don't average it in
            'elo': (lambda v: v if v and v > 0 else None)(to_float(raw.get('PlayerElo'))),
            'rank': to_int(raw.get('PlayerRank')) or None,
            'level': to_int(raw.get('PlayerLevel')),
            'alliance': to_int(raw.get('PlayerAlliance'), 0),
            'ai': to_int(raw.get('PlayerIALevel'), 0) > 0,
            'deckName': raw.get('PlayerDeckName') or '',
            'deck': deck,
        })

    network = str(game.get('IsNetworkMode', '1')) == '1'
    humans = [p for p in players if not p['ai']]
    sides = {}
    for p in humans:
        sides.setdefault(p['alliance'], []).append(p)
    per_side = sorted(len(v) for v in sides.values()) or [0]

    map_info = parse_map(game.get('Map', ''))
    if not network or any(p['ai'] for p in players) or to_int(game.get('NbIA'), 0) > 0:
        match_type = 'vs_ai'
    elif len(sides) == 2 and per_side == [1, 1] and map_info['ranked']:
        match_type = 'ranked'
    else:
        match_type = 'casual'

    # Team size: trust the recorded line-up once both sides are in it -- a 2v2 is
    # often played on a map whose internal name still says 1vs1. With fewer than
    # two humans recorded there is nothing to trust, so fall back to the map.
    if len(humans) >= 2:
        team_size = max(per_side)
    else:
        team_size = map_info['teams'] or (to_int(game.get('NbMaxPlayer'), 2) or 2) // 2
    team_size = max(1, min(10, team_size or 1))

    local = to_int(header.get('ingamePlayerId'), -1)
    if not (0 <= local < len(players)):
        local = None

    victory = duration = winner = None
    if result and isinstance(result.get('result'), dict):
        victory = to_int(result['result'].get('Victory'))
        duration = to_int(result['result'].get('Duration'))
        if victory is not None and local is not None:
            mine = players[local]['alliance']
            winner = 'draw' if victory == 3 else (mine if victory > 3 else 1 - mine)

    stamp, stamp_source = _timestamp(path)
    return {
        'id': game.get('UniqueSessionId') or os.path.basename(path),
        'file': os.path.basename(path),
        'path': os.path.abspath(path),
        'date': stamp.replace(tzinfo=timezone.utc).isoformat(timespec='seconds'),
        'dateSource': stamp_source,
        'version': str(game.get('Version', '')),
        'mods': game.get('ModList', '') or '',
        'server': game.get('ServerName', '') or '',
        'map': map_info,
        'type': match_type,
        'teamSize': team_size,
        'config': {
            'nbMaxPlayer': to_int(game.get('NbMaxPlayer')),
            'initMoney': to_int(game.get('InitMoney')),
            'scoreLimit': to_int(game.get('ScoreLimit')),
            'timeLimit': to_int(game.get('TimeLimit')),
            'incomeRate': game.get('IncomeRate'),
            'private': str(game.get('Private', '0')) == '1',
            'networkMode': network,
            'gameType': to_int(game.get('GameType')),
        },
        'result': {'present': result is not None, 'victoryRaw': victory,
                   'duration': duration, 'winnerAlliance': winner},
        'localPlayer': local,
        'players': players,
    }


def find_replays(folders):
    """Every .rpl3 under `folders`, de-duplicated by real path."""
    found, seen = [], set()
    for folder in folders:
        if os.path.isfile(folder) and folder.lower().endswith('.rpl3'):
            candidates = [folder]
        else:
            candidates = (os.path.join(root, name)
                          for root, _dirs, names in os.walk(folder)
                          for name in names if name.lower().endswith('.rpl3'))
        for path in candidates:
            key = os.path.normcase(os.path.realpath(path))
            if key not in seen:
                seen.add(key)
                found.append(path)
    found.sort()
    return found


def default_folders():
    """Where WARNO keeps replays, plus the usual places people move them to."""
    home = os.path.expanduser('~')
    candidates = [
        os.path.join(home, 'Saved Games', 'EugenSystems', 'WARNO'),
        os.path.join(home, 'Documents', 'EugenSystems', 'WARNO'),
        os.path.join(os.environ.get('OneDrive', ''), 'Documents', 'EugenSystems', 'WARNO'),
    ]
    return [p for p in candidates if p and os.path.isdir(p)]
