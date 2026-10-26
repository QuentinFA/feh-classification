"""Slice barracks screenshots ("Edit Teams" grid, 1320x2868) into unit tiles.

Screenshots are taken in scroll order. Consecutive shots may share a row; those are
detected by pixel comparison and dropped. Each tile gets its rarity (frame colour)
and whether its level has one or two digits (Lv.1 vs Lv.40).
"""
import glob
import os

import numpy as np
from PIL import Image

COL_X = (97, 330, 562, 795, 1027)  # left edge of each grid column
PITCH = 232.5                      # row pitch in px
TILE = 198                         # tile size in px
SCAN = (1200, 2250)                # y range scanned for the row phase
VIEW_TOP, VIEW_BOTTOM = 1268, 2186 # visible part of the grid


def _gray(img):
    return np.asarray(img.convert("L"), dtype=np.float32)


def row_tops(img):
    """Y of every tile row whose top lies in the visible grid (or slightly above)."""
    a = _gray(img)
    cols = np.concatenate([np.arange(x + 20, x + TILE - 20) for x in COL_X])
    prof = a[SCAN[0]:SCAN[1]][:, cols].mean(axis=1)

    def gap_brightness(p):
        vals = []
        for k in range(-1, 5):
            g0, g1 = int(p + k * PITCH + TILE + 5), int(p + k * PITCH + PITCH - 5)
            if g0 >= 0 and g1 < len(prof):
                vals.append(prof[g0:g1].mean())
        return np.mean(vals)

    phase = min(range(int(PITCH)), key=gap_brightness)  # gaps between rows are dark
    tops = [SCAN[0] + phase + k * PITCH for k in range(-1, 6)]
    return [round(t) for t in tops if VIEW_TOP - TILE / 3 <= t <= VIEW_BOTTOM - TILE * 0.8]


def crop_tile(img, x, top):
    """Tile crop; the part outside the visible grid is blanked so it never matches."""
    tile = np.asarray(img.convert("RGB").crop((x, top, x + TILE, top + TILE))).copy()
    clip_top = max(0, VIEW_TOP - top)
    clip_bottom = max(0, top + TILE - VIEW_BOTTOM)
    tile[:clip_top] = 0
    if clip_bottom:
        tile[TILE - clip_bottom:] = 0
    return tile, clip_top, clip_bottom


def _rows_equal(a, b):
    """Two rows (lists of (tile, clip_top, clip_bottom)) show the same units."""
    diffs = []
    for (ta, ca, ba), (tb, cb, bb) in zip(a, b):
        # the grid fades out near the viewport edges: skip 30px past any clipped edge
        y0 = max(c + 30 if c else 20 for c in (ca, cb))
        y1 = TILE - max(c + 30 if c else 20 for c in (ba, bb))
        if y1 - y0 < 40:
            return False
        # row tops are detected to within a few px, so allow a small vertical shift
        diffs.append(min(np.abs(ta[y0 + s:y1 + s].astype(np.float32) - tb[y0:y1]).mean()
                         for s in range(-4, 5) if 0 <= y0 + s and y1 + s <= TILE))
    return bool(diffs) and max(diffs) < 15


def classify_slot(tile):
    """'unit', 'empty' or 'undo' based on how a slot looks."""
    rgb = tile[40:160, 40:160].astype(np.float32)
    if rgb.std() < 18:  # flat teal background
        return "empty"
    # the 'Undo' button is a flat teal panel with white text
    teal = (rgb[..., 2] > rgb[..., 0] + 30).mean()
    return "undo" if teal > 0.8 else "unit"


def rarity(tile):
    """Frame colour: gold=5, silver=4, copper=3, pink (special frame)=5.

    The frame is the outer ~3px of the tile. Only the left edge is used: it is the
    lit side, the right edge is shaded and makes gold look copper.
    """
    edge = tile[60:150, 0:5].astype(np.float32)
    # the frame line is the brightest pixel of each row (column offsets vary by ~1px)
    brightest = edge[np.arange(len(edge)), edge.sum(axis=2).argmax(axis=1)]
    r, g, b = np.median(brightest, axis=0)
    if b >= 0.95 * r:
        return 4  # silver, slightly bluish
    if g > 0.9 * r and b < 0.75 * r:
        return 5  # gold
    if b > 0.75 * g:
        return 5  # pink special frame
    return 3


def level_digits(tile):
    """1 for 'Lv.N', 2 for 'Lv.NN'.

    The label is centred, so the vertical stroke of the 'L' sits at x~40 for one digit
    and x~22 for two. Returns None when no stroke is found.
    """
    label = tile[TILE - 46:TILE - 2, 10:190].astype(np.float32)
    stroke = (label.min(axis=2) > 220).sum(axis=0) >= 18
    if stroke[37:43].any():
        return 1
    if stroke[20:26].any():
        return 2
    return None


def slice_screenshots(folder, out_dir):
    """Return the list of unit tiles in barracks order and save each crop as PNG."""
    os.makedirs(out_dir, exist_ok=True)
    rows = []  # (source file, top, [(tile, clip_top, clip_bottom)])
    prev = []  # rows of the previous screenshot
    for f in sorted(glob.glob(os.path.join(folder, "*.PNG")) + glob.glob(os.path.join(folder, "*.png"))):
        img = Image.open(f)
        shot_rows = [(f, top, [crop_tile(img, x, top) for x in COL_X]) for top in row_tops(img)]
        # drop leading rows already seen at the end of the previous screenshot
        new_rows = list(shot_rows)
        while new_rows and any(_rows_equal(r[2], new_rows[0][2]) for r in prev):
            new_rows.pop(0)
        rows.extend(new_rows)
        prev = shot_rows

    tiles = []
    for f, top, row in rows:
        for col, (tile, ct, cb) in enumerate(row):
            kind = classify_slot(tile)
            if kind != "unit":
                continue
            idx = len(tiles)
            name = f"tile_{idx:03d}.png"
            Image.fromarray(tile).save(os.path.join(out_dir, name))
            tiles.append({
                "idx": idx,
                "img": name,
                "source": os.path.basename(f),
                "row_top": top,
                "col": col,
                "clipped": ct + cb,
                "rarity": rarity(tile),
                "level_digits": level_digits(tile),
            })
    return tiles
