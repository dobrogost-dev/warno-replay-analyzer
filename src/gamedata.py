"""Build the division/unit id -> name tables the viewer needs.

The numbers inside a WARNO deck string are indices into the game's own
serializer table (`GameData/Generated/Gameplay/Decks/DeckSerializer.ndf`).
Eugen ships that table -- together with `Divisions.ndf`, `UniteDescriptor.ndf`
and the English string table -- in plain text inside the modding template:

    <WARNO>/Mods/ModData/base.zip
    <WARNO>/Mods/ExampleAssets/Localisation/UNITS.csv

So when the game is installed we read the names straight out of it and they
always match the player's patch. Otherwise we fall back to the snapshot that
ships next to this file.

Two id conventions, both confirmed against real replays:
  * division id in the deck string == DeckSerializer `DivisionIds` value
  * unit / transport id            == DeckSerializer `UnitIds` value + 1
    (the +1 keeps 0 free to mean "no transport")
"""
import csv
import json
import os
import re
import zipfile

SCHEMA = 5  # bump when the emitted structure changes so old caches are dropped

BASE_ZIP = os.path.join('Mods', 'ModData', 'base.zip')
UNITS_CSV = os.path.join('Mods', 'ExampleAssets', 'Localisation', 'UNITS.csv')
Z_SERIALIZER = 'GameData/Generated/Gameplay/Decks/DeckSerializer.ndf'
Z_DIVISIONS = 'GameData/Generated/Gameplay/Decks/Divisions.ndf'
Z_UNITS = 'GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf'
# FOBs are entities you put in a deck like any card, but the game files them as
# buildings, so their names live here and not with the units.
Z_BUILDINGS = 'GameData/Generated/Gameplay/Gfx/BuildingDescriptors.ndf'

# ETypeStrategicDetailedCount -> the armory tab the viewer groups by
CATEGORY = {
    'Supply': 'log', 'Supply_Hel': 'log',
    'CMD_Inf': 'log', 'CMD_Veh': 'log', 'CMD_Tank': 'log', 'CMD_Hel': 'log',
    'Infantry': 'inf', 'Engineer': 'inf', 'AT': 'inf', 'AT_Gun': 'inf',
    'Howitzer': 'art', 'Mortar': 'art', 'Mlrs': 'art',
    'Armor': 'tank', 'Armor_Heavy': 'tank', 'AT_Veh': 'tank', 'Support': 'tank', 'Ifv': 'tank',
    'Reco': 'rec', 'Reco_Inf': 'rec', 'Reco_Veh': 'rec', 'Reco_Hel': 'rec',
    'AA': 'aa', 'AA_Veh': 'aa', 'Manpad': 'aa', 'AA_Hel': 'aa',
    'Hel_Support': 'hel', 'Hel_Transport': 'hel', 'AT_Hel': 'hel',
    'Air_Support': 'air', 'Air_AA': 'air', 'Air_AT': 'air', 'Air_Sead': 'air',
    'Transport': 'tr',
}
# TypeToken from Divisions.ndf -- the game only ships an icon per type, not a string
DIVISION_TYPE = {
    'MECHANIZ': 'Mechanized', 'INFANREG': 'Infantry', 'MOTORIZD': 'Motorized',
    'AIRBORNE': 'Airborne', 'ARMORED': 'Armored', 'DIVNAVAL': 'Naval',
    'AIRMOBIL': 'Airmobile', 'ARMORREC': 'Armored Recon',
}
# fallback when a unit carries no TypeStrategicCount
ROLE_CATEGORY = {
    'supply': 'log', 'hq_inf': 'log', 'hq_veh': 'log', 'hq_tank': 'log', 'hq_helo': 'log',
    'infantry': 'inf', 'engineer': 'inf', 'AT': 'inf',
    'howitzer': 'art', 'mortar': 'art', 'mlrs': 'art',
    'armor': 'tank', 'ifv': 'tank', 'appui': 'tank',
    'reco': 'rec', 'uav': 'rec', 'AA': 'aa', 'sead': 'air', 'transport': 'tr',
}


# ---------------------------------------------------------------- game lookup

def _steam_roots():
    """Folders Steam itself might be installed in."""
    roots = [
        os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'), 'Steam'),
        os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'Steam'),
    ]
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam'),
                          (winreg.HKEY_LOCAL_MACHINE, r'Software\WOW6432Node\Valve\Steam')):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ('SteamPath', 'InstallPath'):
                        try:
                            roots.append(winreg.QueryValueEx(k, name)[0])
                        except OSError:
                            pass
            except OSError:
                pass
    except ImportError:
        pass
    # the registry and the default paths usually point at the same folder
    seen, out = set(), []
    for r in roots:
        if not r or not os.path.isdir(r):
            continue
        key = os.path.normcase(os.path.abspath(r))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


WARNO_APPID = '1611600'
STEAM_ID64_BASE = 76561197960265728   # SteamID64 = base + 32-bit account id


def cloud_owners():
    """Steam Cloud replay folder -> SteamID64 of the account that owns it.

    `userdata/<account id>/1611600/remote` names its owner in the path, which
    is what tells us whose side a replay's result was recorded from.
    """
    out = {}
    for path in steam_replay_dirs():
        account = os.path.basename(os.path.dirname(os.path.dirname(path)))
        if account.isdigit():
            out[os.path.normcase(os.path.abspath(path))] = str(STEAM_ID64_BASE + int(account))
    return out


def steam_replay_dirs():
    """WARNO's Steam Cloud folders -- `userdata/<account>/1611600/remote`.

    This is where the bulk of a player's replays actually live; the Saved Games
    folder usually only holds the handful they renamed or were sent.
    """
    out = []
    for steam in _steam_roots():
        userdata = os.path.join(steam, 'userdata')
        if not os.path.isdir(userdata):
            continue
        try:
            accounts = os.listdir(userdata)
        except OSError:
            continue
        for account in accounts:
            remote = os.path.join(userdata, account, WARNO_APPID, 'remote')
            if os.path.isdir(remote):
                out.append(remote)
    return out


def local_steam_ids():
    """SteamID64s that have signed in on this PC, most likely one first.

    Replays store each player's avatar as .../SteamGamerPicture/<SteamID64>, so
    this is what tells the viewer which of the players in a lobby is *you*.
    """
    preferred, others = [], []
    for steam in _steam_roots():
        path = os.path.join(steam, 'config', 'loginusers.vdf')
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            continue
        for m in re.finditer(r'"(7656\d{13})"\s*\{(.*?)\n\t\}', text, re.S):
            sid, body = m.group(1), m.group(2)
            recent = re.search(r'"(?:MostRecent|AutoLogin)"\s*"1"', body)
            (preferred if recent else others).append(sid)
    seen, out = set(), []
    for sid in preferred + others:
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _steam_libraries():
    """Every steamapps/common root Steam knows about."""
    roots, seen = [], set()
    candidates = _steam_roots()

    for steam in candidates:
        vdf = os.path.join(steam, 'steamapps', 'libraryfolders.vdf')
        if not os.path.exists(vdf):
            continue
        try:
            with open(vdf, encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            continue
        for m in re.finditer(r'"path"\s*"([^"]+)"', text):
            p = os.path.join(m.group(1).replace('\\\\', '\\'), 'steamapps', 'common')
            k = os.path.normcase(p)
            if k not in seen and os.path.isdir(p):
                seen.add(k)
                roots.append(p)
    for steam in candidates:
        p = os.path.join(steam, 'steamapps', 'common')
        k = os.path.normcase(p)
        if k not in seen and os.path.isdir(p):
            seen.add(k)
            roots.append(p)
    return roots


def find_game_dir():
    """Locate the WARNO install, or None."""
    env = os.environ.get('WARNO_DIR')
    if env and is_game_dir(env):
        return env
    for root in _steam_libraries():
        for name in ('WARNO', 'Warno', 'warno'):
            p = os.path.join(root, name)
            if is_game_dir(p):
                return p
    return None


def is_game_dir(path):
    return bool(path) and os.path.exists(os.path.join(path, BASE_ZIP))


def game_stamp(game_dir):
    """Cheap fingerprint so the cache is rebuilt after a game patch."""
    parts = []
    for rel in (BASE_ZIP, UNITS_CSV):
        p = os.path.join(game_dir, rel)
        try:
            st = os.stat(p)
            parts.append('%d:%d' % (st.st_size, int(st.st_mtime)))
        except OSError:
            parts.append('-')
    return '|'.join(parts)


# ---------------------------------------------------------------- ndf parsing

def _localisation(game_dir):
    path = os.path.join(game_dir, UNITS_CSV)
    table = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for row in csv.reader(f, delimiter=';', quotechar='"'):
            if len(row) >= 2 and row[0]:
                table[row[0]] = row[1]
    table.pop('TOKEN', None)
    return table


def _bracketed(text, key):
    """The `[...]` block that follows `key`, brackets balanced."""
    i = text.index(key)
    i = text.index('[', i)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == '[':
            depth += 1
        elif text[j] == ']':
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return text[i:]


_PAIR_RX = re.compile(r'\(\s*([\w/$]+)\s*,\s*(\d+)\s*\)')


def _serializer_ids(text):
    div_block = _bracketed(text, 'DivisionIds')
    unit_block = _bracketed(text, 'UnitIds')
    divisions = {m.group(1).rsplit('/', 1)[-1]: int(m.group(2)) for m in _PAIR_RX.finditer(div_block)}
    units = {m.group(1).rsplit('/', 1)[-1]: int(m.group(2)) for m in _PAIR_RX.finditer(unit_block)}
    return divisions, units


_DIV_RX = re.compile(r'export\s+(\w+)\s+is\s+TDeckDivisionDescriptor\s*\((.*?)\n\)', re.S)
_UNIT_RX = re.compile(r'export\s+(Descriptor_Unit_\w+)\s+is\s+TEntityDescriptor\s*\(')


def _first(pattern, text, default=None):
    m = re.search(pattern, text)
    return m.group(1) if m else default


def _divisions(text, loc):
    out = {}
    for m in _DIV_RX.finditer(text):
        body = m.group(2)
        token = _first(r"DivisionName\s*=\s*'([^']*)'", body)
        type_token = _first(r'TypeToken\s*=\s*"([^"]*)"', body)
        out[m.group(1)] = {
            'name': loc.get(token) if token else None,
            'alliance': _first(r'DivisionCoalition\s*=\s*TWargameCoalition/(\w+)', body),
            'country': _first(r'CountryId\s*=\s*"([^"]*)"', body),
            'type': DIVISION_TYPE.get(type_token, type_token) if type_token else None,
            'cfg': _first(r"CfgName\s*=\s*'([^']*)'", body),
            'emblem': _first(r'EmblemTexture\s*=\s*"([^"]*)"', body),
        }
    return out


def _units(text, loc):
    out = {}
    marks = [(m.group(1), m.start()) for m in _UNIT_RX.finditer(text)]
    for i, (name, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        body = text[start:end]
        token = _first(r"NameToken\s*=\s*'([^']*)'", body)
        detail = _first(r'TypeStrategicCount\s*=\s*ETypeStrategicDetailedCount/(\w+)', body)
        role = _first(r"UnitRole\s*=\s*'([^']*)'", body)
        out[name] = {
            'name': loc.get(token) if token else None,
            'category': CATEGORY.get(detail) or ROLE_CATEGORY.get(role) or 'other',
            'type': detail or role,
            'country': _first(r"MotherCountry\s*=\s*'([^']*)'", body),
            'alliance': _first(r'Coalition\s*=\s*TWargameCoalition/(\w+)', body),
        }
    return out


def extract(game_dir):
    """Read the id -> name tables out of an installed WARNO."""
    loc = _localisation(game_dir)
    with zipfile.ZipFile(os.path.join(game_dir, BASE_ZIP)) as z:
        serializer = z.read(Z_SERIALIZER).decode('utf-8', 'replace')
        div_defs = _divisions(z.read(Z_DIVISIONS).decode('utf-8', 'replace'), loc)
        unit_defs = _units(z.read(Z_BUILDINGS).decode('utf-8', 'replace'), loc)
        unit_defs.update(_units(z.read(Z_UNITS).decode('utf-8', 'replace'), loc))

    div_ids, unit_ids = _serializer_ids(serializer)

    divisions = {}
    for descriptor, num in div_ids.items():
        info = div_defs.get(descriptor)
        if info:
            divisions[str(num)] = dict(info, descriptor=descriptor)

    units = {}
    for descriptor, num in unit_ids.items():
        info = unit_defs.get(descriptor)
        if info:
            units[str(num + 1)] = dict(info, descriptor=descriptor)

    return {
        'schema': SCHEMA,
        'source': game_dir,
        'stamp': game_stamp(game_dir),
        'divisions': divisions,
        'units': units,
    }


# ---------------------------------------------------------------- entry point

def _cache_path():
    root = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(root, 'WARNO Replay Analyzer', 'warno_data.json')


def _read_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load(game_dir=None, bundled=None, refresh=False, log=print):
    """Return (data, description). Never raises -- an empty table just means
    the viewer shows numeric ids."""
    if game_dir and not is_game_dir(game_dir):
        log('  ! %s does not look like a WARNO install, searching for one instead' % game_dir)
        game_dir = None
    game_dir = game_dir or find_game_dir()
    cache = _cache_path()

    if game_dir:
        stamp = game_stamp(game_dir)
        cached = None if refresh else _read_json(cache)
        if cached and cached.get('schema') == SCHEMA and cached.get('stamp') == stamp:
            return cached, 'game data (cached) from %s' % game_dir
        try:
            data = extract(game_dir)
        except Exception as e:  # corrupt zip, partial Steam download, ...
            log('  ! could not read game data from %s: %s' % (game_dir, e))
        else:
            try:
                os.makedirs(os.path.dirname(cache), exist_ok=True)
                with open(cache, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)
            except OSError:
                pass
            return data, 'game data from %s' % game_dir

    if bundled:
        data = _read_json(bundled)
        if data:
            return data, 'bundled snapshot (WARNO install not found)'

    cached = _read_json(cache)
    if cached:
        return cached, 'previously cached game data'

    return {'divisions': {}, 'units': {}}, 'none - ids will be shown as numbers'
