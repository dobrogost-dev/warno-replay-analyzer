repo: izohek/warno-deck-utils
branch: master

Related repo also read: izohek/warno-db (master) — community unit/division data.

## Last sync
date: 2026-07-27T10:54:52Z

### Updated in this project
- Ported the deck-string decoder (DeckStringParser.ts) to Python in analyze_replays.py
- Copied src/json/units.json from izohek/warno-db into warno_data.json (id→name mapping; divisions map empty — db is launch-era stale)

## Screen map
| Screen | Built from |
| --- | --- |
| analyze_replays.py deck decoder | src/DeckStringParser.ts, src/DeckStringDecoder.ts, src/Constants.ts |
| warno_data.json | warno-db: src/json/units.json |
