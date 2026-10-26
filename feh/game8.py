"""Game8 data: hero ratings (internal JSON behind the hero list widget) and per-unit builds."""
import json
import re

from bs4 import BeautifulSoup

from . import http

HERO_LIST_PAGE = "https://game8.co/games/fire-emblem-heroes/archives/242267"
DELAY = 2

# build slot icon alt text -> slot key
SLOTS = {
    "Weapon": "weapon", "Assist": "assist", "Special": "special",
    "Passive Skill A": "A", "Passive Skill B": "B", "Passive Skill C": "C",
    "Sacred Seal": "S", "Attuned": "X", "Emblem": "emblem",
}


def heroes(refresh=False):
    """All heroes: id, name ('Name - Title'), shortname, rating, url, weapon, movement, type."""
    page = http.get(HERO_LIST_PAGE, delay=DELAY, refresh=refresh)
    m = re.search(r"&quot;toolStructuralMapping&quot;:\{&quot;id&quot;:&quot;(\d+)&quot;,&quot;updatedAt&quot;:(\d+)", page) \
        or re.search(r'"toolStructuralMapping":\{"id":"(\d+)","updatedAt":(\d+)', page)
    if not m:
        raise RuntimeError("hero list widget not found on " + HERO_LIST_PAGE)
    url = f"https://game8.co/api/tool_structural_mappings/{m.group(1)}.json?updatedAt={m.group(2)}"
    data = json.loads(http.get(url, delay=DELAY, headers={"Accept": "application/json"}))
    out = []
    for it in data["collectionArraySchema"]["collectionItems"]:
        out.append({
            "game8_id": it["url"].rstrip("/").rsplit("/", 1)[-1],
            "name": it["name"],
            "shortname": it["shortname"],
            "rating": float(it["rating"]) if it.get("rating") else None,
            "url": it["url"],
            "type": it.get("type"),
        })
    return out


def _slot(img_alt):
    for prefix, key in SLOTS.items():
        if img_alt.startswith(prefix):
            return key
    return None


def unit_page(url):
    """Builds and basic info parsed from a hero page."""
    soup = BeautifulSoup(http.get(url, delay=DELAY), "html.parser")
    info = {}
    for h3 in soup.find_all("h3"):
        if h3.get_text(strip=True).endswith("Basic Information"):
            table = h3.find_next("table")
            for tr in table.find_all("tr", recursive=False) if table else []:
                cells = tr.find_all(["th", "td"], recursive=False)
                if len(cells) == 2:
                    info[cells[0].get_text(" ", strip=True)] = cells[1].get_text(" ", strip=True)
            break

    builds = []
    section = next((h for h in soup.find_all("h2") if h.get_text(strip=True).endswith("Best Builds")), None)
    if section:
        title = None
        for el in section.find_all_next(["h2", "h3", "table"]):
            if el.name == "h2":
                break
            if el.name == "h3":
                title = el.get_text(" ", strip=True)
            elif el.name == "table" and title:
                slots, links = {}, {}
                for div in el.select("div.align"):
                    img, link = div.find("img"), div.find("a")
                    key = _slot(img.get("alt", "")) if img else None
                    if key and link:
                        slots[key] = link.get_text(" ", strip=True)
                        if link.get("href"):
                            links[key] = link["href"]
                if slots:
                    builds.append({"title": title, "slots": slots, "links": links})
                title = None  # only the first table after a build heading
    return {
        "type": info.get("Color / Weapon Type / Move Type"),
        "rarity": info.get("Rarity"),
        "builds": builds,
    }
