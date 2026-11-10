"""FEH Fandom wiki data via its Cargo API: units, skills, per-unit skill lists, face icons."""
import json
import os

from . import http

API = "https://feheroes.fandom.com/api.php"
API_DELAY = 3  # the API rate-limits aggressively
# the image CDN rejects a browser UA coming from a script, and needs the wiki as Referer
HEADERS = {"User-Agent": "feh-personal-script/0.1", "Referer": "https://feheroes.fandom.com/"}


def cargo(table, fields, where=None, order_by=None):
    """All rows of a Cargo query, paginated. `fields` maps alias -> field."""
    rows, offset = [], 0
    field_list = ",".join(f"{f}={a}" for a, f in fields.items())
    while True:
        params = {"action": "cargoquery", "format": "json", "tables": table,
                  "fields": field_list, "limit": 500, "offset": offset}
        if where:
            params["where"] = where
        if order_by:
            params["order_by"] = order_by
        data = json.loads(http.get(API, params, delay=API_DELAY, headers=HEADERS))
        if "error" in data:
            raise RuntimeError(data["error"])
        batch = [r["title"] for r in data["cargoquery"]]
        rows += batch
        if len(batch) < 500:
            return rows
        offset += 500


def units():
    return cargo("Units", {
        "page": "_pageName", "name": "Name", "title": "Title", "wiki_name": "WikiName",
        "weapon": "WeaponType", "move": "MoveType", "properties": "Properties",
        "release": "ReleaseDate", "int_id": "IntID",
    }, order_by="IntID")


def unit_skills():
    return cargo("UnitSkills", {
        "wiki_name": "WikiName", "skill": "skill", "pos": "skillPos",
        "default_rarity": "defaultRarity", "unlock_rarity": "unlockRarity",
    }, order_by="WikiName,skillPos")


def skills():
    return cargo("Skills", {
        "wiki_name": "WikiName", "name": "Name", "category": "Scategory", "sp": "SP",
        "exclusive": "Exclusive", "description": "Description", "properties": "Properties",
    }, order_by="WikiName")


STATS = ("HP", "Atk", "Spd", "Def", "Res")


def gods():
    """Legendary and Mythic heroes, by page name: the blessing they grant and the stats it adds
    to allies carrying that blessing (Emblem heroes grant none)."""
    boosts = {s.lower(): f"AllyBoost{s}" for s in STATS}
    boost = lambda r: {s: int(r[s.lower()]) for s in STATS if r[s.lower()] not in ("", "0")}
    out = {}
    for r in cargo("LegendaryHero", {"page": "_pageName", "element": "LegendaryEffect", "duel": "Duel", **boosts}):
        out[r["page"]] = {"kind": "legendary", "element": r["element"], "boost": boost(r),
                          "duel": int(r["duel"]) if r["duel"] else None}
    for r in cargo("MythicHero", {"page": "_pageName", "element": "MythicEffect",
                                  "e2": "MythicEffect2", "e3": "MythicEffect3", **boosts}):
        out[r["page"]] = {"kind": "mythic", "element": r["element"], "boost": boost(r),
                          "effects": [e for e in (r["e2"], r["e3"]) if e and e != "None"]}
    return out


def face_urls(wiki_names):
    """wiki_name -> URL of its barracks face icon ('<WikiName> Face FC.webp')."""
    urls = {}
    names = list(wiki_names)
    for i in range(0, len(names), 50):
        chunk = names[i:i + 50]
        titles = "|".join(f"File:{n} Face FC.webp" for n in chunk)
        data = json.loads(http.get(API, {"action": "query", "format": "json", "prop": "imageinfo",
                                          "iiprop": "url", "titles": titles}, delay=API_DELAY, headers=HEADERS))
        # MediaWiki normalises titles (e.g. '_' -> ' '); map back through 'normalized'
        norm = {n["to"]: n["from"] for n in data["query"].get("normalized", [])}
        for page in data["query"]["pages"].values():
            if "imageinfo" not in page:
                continue
            title = norm.get(page["title"], page["title"])
            wiki_name = title[len("File:"):-len(" Face FC.webp")]
            urls[wiki_name] = page["imageinfo"][0]["url"]
    return urls


def download_faces(urls, out_dir):
    """Download face icons (static CDN, not rate-limited like the API). Returns wiki_name -> path."""
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for wiki_name, url in urls.items():
        path = os.path.join(out_dir, wiki_name.replace("/", "_") + ".webp")
        if not os.path.exists(path):
            data = http.get(url, delay=0.2, binary=True, headers=HEADERS)
            with open(path, "wb") as f:
                f.write(data)
        paths[wiki_name] = path
    return paths
