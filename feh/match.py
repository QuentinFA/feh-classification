"""Identify barracks tiles by comparing them with the wiki face icons.

A face icon (158x158, transparent background) appears in a 198px tile scaled to
FACE_SIZE at FACE_OFFSET. Both are downsampled to GRID px and compared only where
the face is opaque and no overlay (weapon icon, heart, level label) sits.
"""
import numpy as np
from PIL import Image

TILE = 198
FACE_SIZE, FACE_OFFSET = 194, (1, 4)  # calibrated by grid search on a known pair
GRID = 48
TOP_N = 5
MIN_AREA = 300  # grid cells (of GRID*GRID)
# second pass: re-rank the best coarse candidates at higher resolution, allowing a small
# shift since tile crops are only accurate to a few px (fractional grid pitch)
REFINE_K, REFINE_RES, REFINE_SHIFT = 25, 99, 3


def _overlay_mask():
    """True where the tile shows unobstructed artwork."""
    m = np.ones((TILE, TILE), bool)
    m[:, :62] = False    # weapon icon, heart, blessing icons
    m[150:] = False      # level label
    m[:8] = False        # frame
    m[:, 190:] = False
    m[:45, 140:] = False  # team check mark
    return m


def _down(arr, size=GRID):
    return np.asarray(Image.fromarray(arr).resize((size, size), Image.BILINEAR), dtype=np.float32)


def face_vector(path, size=GRID, overlay=True):
    """Face placed into tile coordinates, downsampled: (rgb size x size x 3, weight size x size)."""
    face = Image.open(path).convert("RGBA").resize((FACE_SIZE, FACE_SIZE), Image.LANCZOS)
    canvas = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    canvas.paste(face, FACE_OFFSET)
    a = np.asarray(canvas)
    opaque = a[..., 3] > 200
    if overlay:
        opaque &= _overlay_mask()
    weight = _down(opaque.astype(np.uint8) * 255, size) / 255.0
    return _down(np.ascontiguousarray(a[..., :3]), size), (weight > 0.99).astype(np.float32)


def tile_vector(path, size=GRID):
    return _down(np.asarray(Image.open(path).convert("RGB")), size)


def build_index(face_paths):
    """face_paths: wiki_name -> path. Returns (names, rgb[N,G,G,3], weight[N,G,G], paths)."""
    names = sorted(face_paths)
    vecs = [face_vector(face_paths[n]) for n in names]
    return names, np.stack([v[0] for v in vecs]), np.stack([v[1] for v in vecs]), [face_paths[n] for n in names]


_refine_cache = {}


def _refine_vector(path):
    if path not in _refine_cache:
        _refine_cache[path] = face_vector(path, REFINE_RES, overlay=False)
    return _refine_cache[path]


def _refine(tile_path, paths, clip_top):
    """Distance per candidate at REFINE_RES, best over small shifts."""
    t = tile_vector(tile_path, REFINE_RES)
    mask = _down(_overlay_mask().astype(np.uint8) * 255, REFINE_RES) > 254
    if clip_top:
        mask[:int(np.ceil((clip_top + 30) * REFINE_RES / TILE))] = False
    faces = [_refine_vector(p) for p in paths]
    rgb = np.stack([f[0] for f in faces])
    w = np.stack([f[1] for f in faces])
    n, r, k = len(paths), REFINE_RES, REFINE_SHIFT
    best = np.full(n, np.inf)
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            # compare tile[y, x] with face[y - dy, x - dx] over the overlap
            ty, tx = slice(max(dy, 0), r + min(dy, 0)), slice(max(dx, 0), r + min(dx, 0))
            fy, fx = slice(max(-dy, 0), r + min(-dy, 0)), slice(max(-dx, 0), r + min(-dx, 0))
            ww = w[:, fy, fx] * mask[ty, tx][None]
            diff = np.abs(rgb[:, fy, fx] - t[None, ty, tx]).mean(axis=3)
            area = ww.sum(axis=(1, 2))
            d = (diff * ww).sum(axis=(1, 2)) / np.maximum(area, 1)
            d[area < MIN_AREA * (REFINE_RES / GRID) ** 2] = np.inf
            best = np.minimum(best, d)
    return best


def match_tile(tile_path, index, clip_top=0):
    """Top candidates for one tile: [(wiki_name, distance)], best first."""
    names, rgb, weight, paths = index
    t = tile_vector(tile_path)
    w = weight.copy()
    if clip_top:  # rows blanked because the tile was cut off at the viewport edge
        w[:, :int(np.ceil((clip_top + 30) * GRID / TILE))] = 0
    diff = np.abs(rgb - t[None]).mean(axis=3)  # N,G,G
    area = w.sum(axis=(1, 2))
    dist = (diff * w).sum(axis=(1, 2)) / np.maximum(area, 1)
    dist[area < MIN_AREA] = np.inf  # too little visible art to judge
    coarse = np.argsort(dist)[:REFINE_K]
    fine = _refine(tile_path, [paths[i] for i in coarse], clip_top)
    order = np.argsort(fine)[:TOP_N]
    return [(names[coarse[i]], float(fine[i])) for i in order]
