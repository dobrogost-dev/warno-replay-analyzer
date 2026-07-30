"""Fetch Steam avatar thumbnails for the players seen in the replays.

Off by default: everything else in this tool works without a network, so
reaching out to Steam is something you ask for with --avatars. Only SteamID64s
-- which the replays already carry, and which are public -- leave the machine.

Steam's public profile XML needs no API key:
    https://steamcommunity.com/profiles/<id>/?xml=1  ->  <avatarIcon> URL

Results (and misses) are cached under %LOCALAPPDATA% so later runs are instant.
"""
import base64
import json
import os
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PROFILE_URL = 'https://steamcommunity.com/profiles/%s/?xml=1'
AVATAR_RX = re.compile(r'<avatarIcon><!\[CDATA\[(.*?)\]\]></avatarIcon>')
USER_AGENT = 'warno-replay-analyzer'
TIMEOUT = 15
WORKERS = 8


def cache_dir():
    root = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(root, 'WARNO Replay Analyzer', 'avatars')


def _get(url, timeout=TIMEOUT):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _reachable():
    """One quick probe, so an offline run fails in seconds instead of stalling
    on hundreds of timeouts."""
    try:
        _get('https://steamcommunity.com/', timeout=6)
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _fetch_one(steam_id):
    """The avatar bytes for one account, or None if it cannot be had."""
    try:
        xml = _get(PROFILE_URL % steam_id).decode('utf-8', 'replace')
    except (urllib.error.URLError, OSError, ValueError):
        return None
    match = AVATAR_RX.search(xml)
    if not match:
        return None
    try:
        return _get(match.group(1))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def load(steam_ids, log=print, refresh=False):
    """steam id -> base64 jpeg, for as many of `steam_ids` as we can resolve."""
    folder = cache_dir()
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = None

    misses_path = os.path.join(folder, 'misses.json') if folder else None
    misses = set()
    if misses_path and not refresh:
        try:
            with open(misses_path, encoding='utf-8') as f:
                misses = set(json.load(f))
        except (OSError, ValueError):
            misses = set()

    out, todo = {}, []
    for steam_id in steam_ids:
        path = os.path.join(folder, steam_id + '.jpg') if folder else None
        if path and not refresh and os.path.exists(path):
            try:
                with open(path, 'rb') as f:
                    out[steam_id] = base64.b64encode(f.read()).decode('ascii')
                continue
            except OSError:
                pass
        if steam_id not in misses or refresh:
            todo.append(steam_id)

    if todo and not _reachable():
        log('Steam unreachable — skipping %d avatar%s (%d served from cache)'
            % (len(todo), '' if len(todo) == 1 else 's', len(out)))
        todo = []

    if todo:
        log('Fetching %d Steam avatar%s (%d already cached)...'
            % (len(todo), '' if len(todo) == 1 else 's', len(out)))
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for steam_id, blob in zip(todo, pool.map(_fetch_one, todo)):
                if not blob:
                    misses.add(steam_id)
                    continue
                out[steam_id] = base64.b64encode(blob).decode('ascii')
                if folder:
                    try:
                        with open(os.path.join(folder, steam_id + '.jpg'), 'wb') as f:
                            f.write(blob)
                    except OSError:
                        pass
        if misses_path:
            try:
                with open(misses_path, 'w', encoding='utf-8') as f:
                    json.dump(sorted(misses), f)
            except OSError:
                pass

    log('Steam avatars: %d of %d players' % (len(out), len(steam_ids)))
    return out
