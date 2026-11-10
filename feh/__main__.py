"""Pipeline entry point.

    uv run python -m feh build   # screenshots + wiki + Game8 -> web/data.js
    uv run python -m feh serve   # UI on http://localhost:8000, saves edits to state.json
"""
import argparse
import difflib
import json
import os
import re
import sys
import unicodedata

from . import game8, match, screens, server, wiki

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BUILD = os.path.join(ROOT, "build")
STATE = os.path.join(ROOT, "state.json")
EXCLUDED = {"enemy", "generic"}  # NPC-only wiki entries


def norm(s):
    """'Alfaðör' and 'Alfador' compare equal; case- and accent-insensitive."""
    s = s.replace("ð", "d").replace("Ð", "D").replace("þ", "th").replace("Þ", "Th")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().casefold().strip()


def find_unit(game8_name, by_key, titles_by_name):
    """Wiki unit for a Game8 'Name - Title' (separators and spelling vary a little)."""
    name, title = (re.split(r"\s*(?: - |- | -|: )\s*", game8_name, maxsplit=1) + [""])[:2]
    name = re.sub(r"\s*\((?:F|M)\)$", "", name)
    key = (norm(name), norm(title))
    if key in by_key:
        return by_key[key]
    close = difflib.get_close_matches(norm(title), titles_by_name.get(norm(name), []), n=1, cutoff=0.8)
    return by_key[(norm(name), close[0])] if close else None


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def build(args):
    log("1/6 slicing screenshots")
    tiles = screens.slice_screenshots(os.path.join(ROOT, "screenshots"), os.path.join(BUILD, "tiles"))
    log(f"    {len(tiles)} tiles")

    log("2/6 wiki units, skills, face icons")
    units = [u for u in wiki.units() if not EXCLUDED & set((u["properties"] or "").split(","))]
    unit_skills = wiki.unit_skills()
    skills = wiki.skills()
    gods = wiki.gods()
    faces = wiki.download_faces(wiki.face_urls(u["wiki_name"] for u in units), os.path.join(BUILD, "faces"))
    log(f"    {len(units)} units, {len(faces)} faces, {len(skills)} skills, {len(gods)} gods")

    log("3/6 matching tiles to faces")
    index = match.build_index(faces)
    for t in tiles:
        cands = match.match_tile(os.path.join(BUILD, "tiles", t["img"]), index, clip_top=t["clipped"])
        t["candidates"] = [{"unit": n, "dist": round(min(d, 999), 2)} for n, d in cands]

    log("4/6 Game8 ratings")
    by_key = {(norm(u["name"]), norm(u["title"])): u for u in units}
    titles_by_name = {}
    for n, t in by_key:
        titles_by_name.setdefault(n, []).append(t)
    unmatched = []
    for h in game8.heroes(refresh=args.refresh):
        u = find_unit(h["name"], by_key, titles_by_name)
        if u is None:
            unmatched.append(h["name"])
            continue
        u.update(game8_id=h["game8_id"], game8_url=h["url"], shortname=h["shortname"],
                 rating=h["rating"], game8_type=h["type"])
    if unmatched:
        log(f"    {len(unmatched)} Game8 heroes not found on the wiki: {unmatched[:10]}")

    log("5/6 Game8 builds for owned units")
    state = load_state()
    overrides = state.get("tiles", {})
    owned = {overrides.get(str(t["idx"]), {}).get("unit") or t["candidates"][0]["unit"] for t in tiles}
    owned |= {a["unit"] for a in state.get("added", [])}  # added in the UI, no screenshot
    owned.discard(None)
    by_wiki = {u["wiki_name"]: u for u in units}
    todo = [by_wiki[w] for w in sorted(owned) if w in by_wiki and by_wiki[w].get("game8_url")]
    for i, u in enumerate(todo, 1):
        try:
            page = game8.unit_page(u["game8_url"])
        except Exception as e:  # keep going; a re-run retries uncached pages
            log(f"    {u['wiki_name']}: {e}")
            continue
        u["builds"] = page["builds"]
        u["summon_rarity"] = page["rarity"]
        if i % 25 == 0:
            log(f"    {i}/{len(todo)}")

    log("6/6 writing web/data.js")
    skills_by_unit = {}
    for row in unit_skills:
        skills_by_unit.setdefault(row["wiki_name"], []).append({
            "skill": row["skill"],
            "default": int(row["default_rarity"]) if row["default_rarity"] else None,
            "unlock": int(row["unlock_rarity"]) if row["unlock_rarity"] else None,
        })
    data = {
        "tiles": tiles,
        "units": {u["wiki_name"]: {
            "name": u["name"], "title": u["title"], "weapon": u["weapon"], "move": u["move"],
            "properties": [p for p in (u["properties"] or "").split(",") if p],
            "shortname": u.get("shortname"), "rating": u.get("rating"), "game8_url": u.get("game8_url"),
            "summon_rarity": u.get("summon_rarity"), "builds": u.get("builds"),
            "skills": skills_by_unit.get(u["wiki_name"], []),
            "blessing": gods.get(u["page"]),
            "face": os.path.relpath(faces[u["wiki_name"]], ROOT) if u["wiki_name"] in faces else None,
        } for u in units},
        "skills": {s["wiki_name"]: {
            "name": s["name"], "category": s["category"], "sp": int(s["sp"]) if s["sp"] else None,
            "exclusive": s["exclusive"] == "1", "description": s["description"],
        } for s in skills},
    }
    os.makedirs(os.path.join(ROOT, "web"), exist_ok=True)
    with open(os.path.join(ROOT, "web", "data.js"), "w", encoding="utf-8") as f:
        f.write("window.FEH_DATA = ")
        json.dump(data, f, ensure_ascii=False)
        f.write(";\n")
    log("done")


def main():
    p = argparse.ArgumentParser(prog="feh")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="rebuild web/data.js from screenshots, wiki and Game8")
    b.add_argument("--refresh", action="store_true", help="re-download the Game8 hero ratings")
    s = sub.add_parser("serve", help="serve the UI and persist edits to state.json")
    s.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    if args.cmd == "build":
        build(args)
    else:
        server.serve(ROOT, STATE, args.port)


if __name__ == "__main__":
    main()
