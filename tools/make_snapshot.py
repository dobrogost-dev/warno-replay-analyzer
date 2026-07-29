"""Refresh src/assets/warno_data.json -- the id -> name table shipped inside the .exe.

Run this on a machine with WARNO installed whenever the game gets a patch that
adds units or divisions. Users with the game installed never touch it (the
analyzer reads their own install); it only matters for people running the
report on a PC without WARNO.

    python tools/make_snapshot.py [--game-dir "...\\steamapps\\common\\WARNO"]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'src'))

import gamedata  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), 'src', 'assets', 'warno_data.json')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game-dir')
    ap.add_argument('-o', '--out', default=OUT)
    args = ap.parse_args()

    game = args.game_dir or gamedata.find_game_dir()
    if not game or not gamedata.is_game_dir(game):
        print('WARNO install not found. Pass --game-dir.')
        return 2

    print('Reading %s' % game)
    data = gamedata.extract(game)
    data['source'] = os.path.basename(game)  # do not ship someone's local paths
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    print('%d divisions, %d units -> %s (%.0f KB)'
          % (len(data['divisions']), len(data['units']), args.out,
             os.path.getsize(args.out) / 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
