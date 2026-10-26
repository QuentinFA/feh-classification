# FEH barracks vs Game8 tier list

Personal tool: identifies the units in barracks screenshots, ranks them with Game8 ratings,
shows Game8 builds per unit, and suggests which units can be deleted or used as skill fodder.

## Usage

```sh
# 1. Put "Edit Teams" barracks screenshots (iPhone, 1320x2868, scroll order) in screenshots/
# 2. Build the data (first run is slow: the wiki API is rate-limited; everything is cached in cache/)
uv run python -m feh build            # --refresh re-downloads the Game8 ratings
# 3. Open the UI
uv run python -m feh serve            # http://localhost:8000
```

After confirming or correcting units in the UI, run `build` again to fetch Game8 builds for the newly identified units.

## How it works

| Step | Source | Module |
|---|---|---|
| Slice the screenshots into tiles, detect rarity (frame colour) and Lv.1 vs Lv.10+ | screenshots | `feh/screens.py` |
| Units, skills with their unlock rarity, face icons | FEH Fandom wiki Cargo API | `feh/wiki.py` |
| Identify each tile by comparing it with every face icon | | `feh/match.py` |
| Ratings for all heroes (internal JSON behind the hero list) and builds per hero page | Game8 | `feh/game8.py` |
| UI (vanilla JS); edits are saved to `state.json` | | `web/`, `feh/server.py` |

Deletion rule: a unit is deletable when it isn't invested (Lv.1–9) and is either a duplicate or rated below 9.0.
Deletable units that carry an inheritable skill needed by a keeper's build are listed as fodder; the others as "send home".
Any decision can be overridden per unit in the UI.

Game8 data is for personal use only (republishing is not allowed): `cache/`, `build/` and `web/data.js` are git-ignored.
