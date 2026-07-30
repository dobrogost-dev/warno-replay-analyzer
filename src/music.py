"""Collect the soundtrack that gets embedded in the report.

Tracks come from a `music` folder: one sitting next to the program wins, so
anybody can swap the playlist without rebuilding, and the copy packed into the
.exe at build time is the fallback.

One file is not part of the shuffle. `papiezpedal` is held back and played by
the viewer only when the opponent-ELO filter lands on 2137.
"""
import base64
import os

SPECIAL = 'papiezpedal'
MIME = {
    '.m4a': 'audio/mp4', '.mp4': 'audio/mp4', '.aac': 'audio/aac',
    '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg', '.oga': 'audio/ogg',
    '.opus': 'audio/ogg', '.wav': 'audio/wav', '.flac': 'audio/flac',
    '.webm': 'audio/webm',
}
MAX_TOTAL_MB = 64        # refuse to build an unopenable report by accident


def folders(app_dir, asset_dir):
    """Where to look, nearest first."""
    out, seen = [], set()
    for path in (os.path.join(app_dir, 'music'), os.path.join(asset_dir, 'music')):
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen and os.path.isdir(path):
            seen.add(key)
            out.append(path)
    return out


def load(app_dir, asset_dir, log=print):
    """{'tracks': [...], 'special': {...}} with audio inlined as data URIs."""
    picked = {}
    for folder in folders(app_dir, asset_dir):
        for name in sorted(os.listdir(folder)):
            stem, ext = os.path.splitext(name)
            if ext.lower() in MIME and stem.lower() not in picked:
                picked[stem.lower()] = (stem, os.path.join(folder, name), ext.lower())
    if not picked:
        return {}

    total = sum(os.path.getsize(p) for _, p, _ in picked.values())
    if total > MAX_TOTAL_MB * 1024 * 1024:
        log('Music: %.0f MB is more than the %d MB cap, skipping'
            % (total / 1e6, MAX_TOTAL_MB))
        return {}

    tracks, special = [], None
    for key in sorted(picked):
        stem, path, ext = picked[key]
        try:
            with open(path, 'rb') as f:
                blob = f.read()
        except OSError as e:
            log('  ! %s: %s' % (stem, e))
            continue
        entry = {'name': stem,
                 'src': 'data:%s;base64,%s' % (MIME[ext], base64.b64encode(blob).decode('ascii'))}
        if key == SPECIAL:
            special = entry
        else:
            tracks.append(entry)

    log('Music: %d track%s in the shuffle%s (%.1f MB)'
        % (len(tracks), '' if len(tracks) == 1 else 's',
           ', plus a pdf music file' if special else '', total / 1e6))
    return {'tracks': tracks, 'special': special}
