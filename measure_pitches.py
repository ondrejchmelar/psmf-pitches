#!/usr/bin/env python3
"""Measure football-pitch dimensions from Prague orthophoto imagery.

Imagery: IPR Praha "Ortofotomapa 2025" (0.10 m/px, EPSG:5514 S-JTSK), with the
national CUZK orthophoto as a fallback source.

Method
------
Turf is separated from vegetation by colour *and* texture. The key signal,
measured off the imagery rather than assumed: artificial turf is a smooth,
weakly-saturated green (H~60, S~30, local sd~5), while trees and rough grass
are strongly saturated and highly textured (S~60, sd~15).

White markings cut a turf blob into fragments, so candidate rectangles are
proposed at several morphological closing scales and de-duplicated by IoU,
keeping the most rectangular fit. That avoids one global kernel having to both
bridge a halfway line and preserve the gap between neighbouring pitches.

Two numbers are reported per pitch:
  turf_*  - the extent of the turf carpet (minAreaRect of the blob)
  line_*  - the marked playing area, read from the painted lines inside it

PSMF publishes one GPS point per *areal*, so multi-pitch sites yield several
candidates; overrides.json records which candidate is which numbered pitch.
"""
from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path

import cv2
import numpy as np
import requests
from pyproj import Transformer

ROOT = Path(__file__).parent
DATA, OUT, CACHE = ROOT / "data", ROOT / "out", ROOT / "data" / "tiles"

IPR = ("https://gs-pub.praha.eu/arcgis/rest/services/ort/ortofotomapa_archiv"
       "/MapServer/export")
IPR_LAYER = 284                     # "Ortofotomapa 2025" -> Image sublayer
# Other captures in the same archive. Leaf-off ("mimovegetacni") flights carry
# no tree shadow and, at these grounds, noticeably crisper markings.
IPR_LAYERS = {284: "2025", 280: "2024", 272: "2024 leaf-off",
              154: "2025 leaf-off", 285: "2026 leaf-off", 264: "2023"}
CUZK = "https://ags.cuzk.cz/arcgis1/services/ORTOFOTO/MapServer/WMSServer"

TO_JTSK = Transformer.from_crs(4326, 5514, always_xy=True)
TO_WGS = Transformer.from_crs(5514, 4326, always_xy=True)

# turf appearance, measured from the imagery (see module docstring)
HUE_LO, HUE_HI = 45, 85
SAT_LO, SAT_HI = 10, 48
VAL_LO = 70
SD_MAX = 13
SD_WIN_M = 1.7          # texture window, in metres (not pixels)
SEED_M = 12.0
CLOSE_M = 0.5           # fill pinholes in the turf mask
OPEN_M = 0.9            # drop speckle
# closing scales that bridge painted lines without bridging a real gap between
# neighbouring pitches, in metres
CLOSE_SCALES_M = (0.9, 1.3, 1.7, 2.1, 2.5, 2.9, 3.3)

# a Hanspaulka pitch is small-sided; keep a generous envelope
MIN_AREA_M2, MAX_AREA_M2 = 420, 12000
MIN_SHORT_M, MAX_LONG_M = 18, 130
MIN_ASPECT, MAX_ASPECT = 1.02, 3.00
MIN_RECTANGULARITY = 0.70
NMS_IOU = 0.35
# Turf segmentation runs at a fixed working resolution. Local texture variance
# rises with sharper imagery, so an adaptive sd threshold tuned at 10 cm floods
# the mask at 5 cm. Segment at 10 cm, fit the painted lines at full resolution.
WORK_RES = 0.10
RIM_M = 1.0             # turf rim recovered after thresholding (see turf_mask)


def _px(metres, res, odd=True):
    """Kernel size in pixels for a physical size, so tuning is resolution-free."""
    n = max(int(round(metres / res)), 3)
    return n | 1 if odd else n


# --------------------------------------------------------------------------- imagery
MAX_BLACK_FRAC = 0.01   # a good ortho tile has essentially no pure-black pixels


def _tile_ok(path):
    """Reject a partially rendered tile: the server sometimes returns an image
    with a large black region instead of failing outright."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        return None, "unreadable"
    black = float((cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) < 5).mean())
    if black > MAX_BLACK_FRAC:
        return None, f"{black:.0%} black"
    return img, ""


def fetch_crop(lat, lon, half_m, res, code, source="ipr", tries=3, layer=None):
    """Return (BGR image, georef dict) for a square crop centred on lat/lon."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cx, cy = TO_JTSK.transform(lon, lat)
    size = int(round(2 * half_m / res))
    if size > 4096:
        raise ValueError(f"{size} px exceeds the 4096 px server limit; raise --res")
    x0, y0, x1, y1 = cx - half_m, cy - half_m, cx + half_m, cy + half_m
    layer = layer or IPR_LAYER
    path = CACHE / f"{code}_{source}_L{layer}_{int(half_m)}m_{res}.png"

    img = None
    if path.exists():
        img, why = _tile_ok(path)
        if img is None:
            print(f"  {code}: cached tile {why}, refetching", file=sys.stderr)
            path.unlink(missing_ok=True)

    for attempt in range(tries):
        if img is not None:
            break
        if source == "ipr":
            url = (f"{IPR}?bbox={x0},{y0},{x1},{y1}&bboxSR=5514&imageSR=5514"
                   f"&size={size},{size}&format=png&transparent=false"
                   f"&layers=show:{layer}&f=image")
        else:
            url = (f"{CUZK}?service=WMS&version=1.3.0&request=GetMap&layers=0"
                   f"&styles=&crs=EPSG:5514&bbox={y0},{x0},{y1},{x1}"
                   f"&width={size}&height={size}&format=image/png")
        r = requests.get(url, timeout=180)
        r.raise_for_status()
        if not r.headers.get("content-type", "").startswith("image"):
            raise RuntimeError(f"{source} returned {r.headers.get('content-type')}")
        path.write_bytes(r.content)
        img, why = _tile_ok(path)
        if img is None:
            print(f"  {code}: tile attempt {attempt + 1} {why}, retrying",
                  file=sys.stderr)
            path.unlink(missing_ok=True)

    if img is None:
        raise RuntimeError(f"could not get a clean tile for {code}")
    # row 0 is the NORTH edge, so JTSK y decreases as pixel y increases
    return img, {"x0": x0, "y1": y1, "res": res, "size": size, "source": source,
                 "layer": layer, "capture": IPR_LAYERS.get(layer, str(layer)),
                 "centre_jtsk": [cx, cy]}


def pick_layer(lat, lon, res, code, candidates=tuple(IPR_LAYERS), probe_m=55.0):
    """Choose the capture whose markings stand out most at this ground.

    Scored on how far the brightest line response rises above the median, on a
    small probe crop, so only the winner is downloaded at full size.
    """
    best, best_score = IPR_LAYER, -1.0
    for lyr in candidates:
        try:
            img, _ = fetch_crop(lat, lon, probe_m, res, code, tries=1, layer=lyr)
        except Exception:
            continue
        r = line_response(img, res)
        score = float(np.percentile(r, 99.5) / max(np.median(r), 1e-6))
        if score > best_score:
            best, best_score = lyr, score
    return best, round(best_score, 1)


def load_venues():
    """PSMF venue directory plus any extra venues (e.g. our training pitch).

    Extras live in their own file so re-running scrape_psmf.py, which rewrites
    venues.json wholesale, cannot drop them.
    """
    venues = json.loads((DATA / "venues.json").read_text("utf-8"))
    extra = DATA / "extra_venues.json"
    if extra.exists():
        venues.update({k: v for k, v in json.loads(extra.read_text("utf-8")).items()
                       if not k.startswith("_")})
    return venues


def px_to_lonlat(pt, geo):
    x = geo["x0"] + pt[0] * geo["res"]
    y = geo["y1"] - pt[1] * geo["res"]
    return TO_WGS.transform(x, y)


# --------------------------------------------------------------------------- masks
def turf_mask(img, seed_xy, seed_m=SEED_M, res=0.10):
    """Turf vs vegetation, adapted per venue from a seed patch on the pitch.

    Measured off the imagery: artificial turf is a smooth, weakly-saturated
    green (S~30, local sd~5); trees and rough grass are strongly saturated and
    highly textured (S~60, sd~15). Absolute thresholds do not transfer between
    venues (turf hue ranges 58-105 across this season's grounds), so the colour
    model is built from a patch at the seed point and widened by its own MAD.
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    sw = _px(SD_WIN_M, res)
    mu = cv2.blur(gray, (sw, sw))
    sd = np.sqrt(np.maximum(cv2.blur(gray * gray, (sw, sw)) - mu * mu, 0))

    sx, sy = int(seed_xy[0]), int(seed_xy[1])
    r = max(int(seed_m / res / 2), 8)
    y0, y1 = max(sy - r, 0), min(sy + r, img.shape[0])
    x0, x1 = max(sx - r, 0), min(sx + r, img.shape[1])
    patch = hsv[y0:y1, x0:x1].reshape(-1, 3)
    med = np.median(patch, axis=0)
    mad = np.median(np.abs(patch - med), axis=0) * 1.4826
    tol = np.maximum(mad * 4.0, [10, 20, 30])
    lo, hi = med - tol, med + tol

    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    def in_range(scale):
        t = tol * scale
        a, b = med - t, med + t
        return ((h >= a[0]) & (h <= b[0]) & (s >= a[1]) & (s <= b[1])
                & (v >= a[2]) & (v <= b[2]))

    smooth = sd < max(3.0 * float(np.median(sd[y0:y1, x0:x1])), 9.0)
    strict = (in_range(1.0) & smooth).astype(np.uint8)
    # Hysteresis: the strict threshold stops short of the real turf edge, where
    # pixels mix with the kerb, so the rectangle came out *smaller* than the
    # painted pitch inside it. Grow the strict core through a looser threshold.
    loose = (in_range(1.35) & smooth).astype(np.uint8)
    n, labels = cv2.connectedComponents(loose, 8)[:2]
    keep = np.unique(labels[(strict > 0) & (labels > 0)])
    m = np.isin(labels, keep).astype(np.uint8) if keep.size else strict
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, _k(_px(CLOSE_M, res)))
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, _k(_px(OPEN_M, res)))


def _k(n):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (n, n))


# --------------------------------------------------------------------------- geometry
def roi_box(geo, roi_m):
    """ROI given in metres relative to the GPS point -> pixel slice."""
    c = geo["size"] / 2.0
    x0 = int(round(c + roi_m[0] / geo["res"]))
    x1 = int(round(c + roi_m[1] / geo["res"]))
    y0 = int(round(c + roi_m[2] / geo["res"]))
    y1 = int(round(c + roi_m[3] / geo["res"]))
    return (max(x0, 0), max(y0, 0),
            min(x1, geo["size"]), min(y1, geo["size"]))


def border_support(turf, rect, res, off_m=2.0):
    """Fraction of the rectangle outline that has NON-turf just outside it.

    Distinguishes a real pitch edge (surface changes) from a fragment boundary
    created by a painted line, which has turf on both sides.
    """
    (cx, cy), (w, h), a = rect
    ring = cv2.boxPoints(((cx, cy), (w + 2 * off_m / res, h + 2 * off_m / res), a))
    pts = []
    for i in range(4):
        p, q = ring[i], ring[(i + 1) % 4]
        n = max(int(np.linalg.norm(q - p) / 5), 2)
        pts += [p + (q - p) * t for t in np.linspace(0, 1, n)]
    pts = np.array(pts)
    H, W = turf.shape
    ok = (pts[:, 0] >= 0) & (pts[:, 0] < W) & (pts[:, 1] >= 0) & (pts[:, 1] < H)
    if ok.sum() < 8:
        return 0.0
    return float((turf[pts[ok, 1].astype(int), pts[ok, 0].astype(int)] == 0).mean())


def measure_roi(img, geo, roi_m):
    """Measure the single pitch inside `roi_m`. Returns the best turf rectangle."""
    res = geo["res"]
    x0, y0, x1, y1 = roi_box(geo, roi_m)
    if x1 - x0 < 40 or y1 - y0 < 40:
        return None, None, None
    sub = img[y0:y1, x0:x1]
    f = res / WORK_RES                      # <1 when the tile is finer than 10 cm
    if abs(f - 1.0) > 1e-6:
        sub_w = cv2.resize(sub, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    else:
        sub_w = sub
    wres = WORK_RES
    seed = (sub_w.shape[1] / 2.0, sub_w.shape[0] / 2.0)
    turf = turf_mask(sub_w, seed, res=wres)

    best = None
    for scale_m in CLOSE_SCALES_M:
        k = _px(scale_m, wres)
        m = cv2.morphologyEx(turf, cv2.MORPH_CLOSE, _k(k))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA] * wres * wres
            if not (MIN_AREA_M2 <= area <= MAX_AREA_M2):
                continue
            cnts, _ = cv2.findContours((labels == i).astype(np.uint8),
                                       cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            rect = cv2.minAreaRect(max(cnts, key=cv2.contourArea))
            w, h = rect[1]
            long_m, short_m = max(w, h) * wres, min(w, h) * wres
            if short_m < MIN_SHORT_M or long_m > MAX_LONG_M or short_m <= 0:
                continue
            if not (MIN_ASPECT <= long_m / short_m <= MAX_ASPECT):
                continue
            rectness = area / (long_m * short_m)
            if rectness < MIN_RECTANGULARITY:
                continue
            bs = border_support(turf, rect, wres)
            if bs < 0.45:
                continue        # a blob clipped by the ROI edge scores a perfect
                                # rectness with no real surface change around it
            score = 0.6 * rectness + 0.4 * bs
            if best is None or score > best["score"]:
                best = {"rect": rect, "long_m": long_m, "short_m": short_m,
                        "rectness": rectness, "border": bs, "score": score,
                        "scale_m": scale_m}
    if best is None:
        return None, turf, (x0, y0)
    # Even with hysteresis the colour threshold stops just inside the rim, where
    # turf pixels mix with the kerb, so the extent came out *smaller* than the
    # painted pitch it contains -- which cannot be true. Grow the rectangle (not
    # the mask: dilating that merges neighbouring surfaces) by the rim width.
    (cx, cy), (bw, bh), ang = best["rect"]
    rim = 2 * RIM_M / wres
    bw, bh = bw + rim, bh + rim
    best["long_m"] = max(bw, bh) * wres
    best["short_m"] = min(bw, bh) * wres
    inv = 1.0 / f
    best["rect"] = ((cx * inv + x0, cy * inv + y0), (bw * inv, bh * inv), ang)
    best["turf_scale"] = f
    return best, turf, (x0, y0, f)





def line_response(img, res, line_w_m=0.12, bg_m=1.6, mode="white"):
    """Thin-structure response against the local turf background.

    Whole pitches are always marked in white, so `mode="white"` scores
    luminance alone. Feeding chroma into those makes turf colour noise compete
    with genuine touchlines and the fit drifts.

    The numbered cross-pitches at Sterboholy and Prazacka are marked in faint
    blue over green: barely any luminance step, but a clear chroma one. Their
    side boundaries need `mode="chroma"`, while their goal lines lie on the
    parent's white touchlines and still want `mode="white"`.
    """
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    bg = cv2.cvtColor(cv2.medianBlur(img, min(_px(bg_m, res), 31)),
                      cv2.COLOR_BGR2LAB).astype(np.float32)
    d = lab - bg
    mag = (np.abs(d[..., 0]) if mode == "white"
           else np.sqrt(d[..., 1] ** 2 + d[..., 2] ** 2))
    k = _k(_px(line_w_m * 3.5, res))
    return np.maximum(cv2.morphologyEx(mag, cv2.MORPH_TOPHAT, k), 0)


def _subpix(prof, i):
    """Parabolic interpolation around a profile peak."""
    if i <= 0 or i >= len(prof) - 1:
        return float(i)
    a, b, c = float(prof[i - 1]), float(prof[i]), float(prof[i + 1])
    d = a - 2 * b + c
    return float(i) if abs(d) < 1e-9 else float(i) - 0.5 * (c - a) / d


def _snap(prof, pos, res, base, rng_m=0.5, min_rel=1.5):
    """Settle a modelled line position onto its own peak, if it has one.

    Only a peak clearly above background counts. Where the division lines are
    too faint to see at all -- Prazacka -- the local maximum is turf noise, and
    following it would move the edge off the geometry that was actually fitted;
    there the modelled position stands, interpolated in place as before.
    """
    a, b = int(round(pos - rng_m / res)), int(round(pos + rng_m / res))
    a, b = max(a, 1), min(b, len(prof) - 2)
    if b <= a:
        return float(pos)
    i = a + int(np.argmax(prof[a:b + 1]))
    return _subpix(prof, i if prof[i] > min_rel * base else int(round(pos)))


def _rotate(resp, centre, ang):
    M = cv2.getRotationMatrix2D(centre, ang, 1.0)
    return cv2.warpAffine(resp, M, (resp.shape[1], resp.shape[0]),
                          flags=cv2.INTER_LINEAR, borderValue=0.0)


def fit_painted(resp_cols, resp_rows, rect, res, out_m=0.4, in_m=3.5,
                iters=4, angle_range=2.0, fix_cols=False):
    """Fit the painted rectangle, starting from a turf or geometric estimate.

    Coordinate descent: with the cross-axis extent held fixed, each edge is the
    profile peak inside a search band, so a faint but continuous line beats a
    bright but short one (a penalty-box side, a shadow). Sub-pixel interpolation
    keeps the answer finer than the pixel grid.

    The band matters. A touchline sits within a metre or so of the turf edge --
    often just outside it, because the turf mask erodes slightly -- while the
    penalty-area line is several metres in and the fence several metres out.
    Searching too wide lets an edge jump to the wrong line and the whole
    rectangle cascades off.
    """
    (cx, cy), (w, h), ang0 = rect

    def sharpness(ang):
        R = _rotate(resp_cols + resp_rows, (cx, cy), ang)
        band = out_m / res
        sl = R[int(max(cy - h / 2 - band, 0)):int(cy + h / 2 + band),
               int(max(cx - w / 2 - band, 0)):int(cx + w / 2 + band)]
        if sl.size == 0:
            return -1.0
        px, py = sl.mean(axis=0), sl.mean(axis=1)
        return float(((px - px.mean()) ** 2).sum() + ((py - py.mean()) ** 2).sum())

    angles = np.arange(ang0 - angle_range, ang0 + angle_range + 0.01, 0.1)
    best_ang = float(max(angles, key=sharpness))
    RC = _rotate(resp_cols, (cx, cy), best_ang)
    RR = _rotate(resp_rows, (cx, cy), best_ang)


    xl, xr = cx - w / 2, cx + w / 2
    yt, yb = cy - h / 2, cy + h / 2
    lo, hi = out_m / res, in_m / res

    # Anchor each band to the *initial* edge, never to the running estimate:
    # re-centring every pass lets an edge walk in_m per iteration and drift
    # metres away from the pitch it started on.
    xl0, xr0, yt0, yb0 = xl, xr, yt, yb

    def pick(prof, anchor, inward, cov=None):
        a = int(round(anchor - (lo if inward > 0 else hi)))
        b = int(round(anchor + (hi if inward > 0 else lo)))
        a, b = max(a, 0), min(b, len(prof) - 1)
        if b - a < 3:
            return anchor, 0.0
        seg = prof[a:b + 1]
        i = int(np.argmax(seg))
        return a + _subpix(seg, i), float(seg[i])

    conf = [0.0] * 4
    for _ in range(iters):
        rows = slice(int(max(yt, 0)), int(min(yb, RC.shape[0])))
        colprof = RC[rows, :].mean(axis=0)
        cbase = max(float(np.median(colprof[colprof > 0])) if (colprof > 0).any() else 0.0, 1e-6)
        if fix_cols:
            # the section boundaries are already fitted across the whole parent
            cl = float(colprof[int(np.clip(xl, 0, len(colprof) - 1))])
            cr = float(colprof[int(np.clip(xr, 0, len(colprof) - 1))])
        else:
            xl, cl = pick(colprof, xl0, +1)
            xr, cr = pick(colprof, xr0, -1)
        cols = slice(int(max(xl, 0)), int(min(xr, RR.shape[1])))
        rowprof = RR[:, cols].mean(axis=1)
        rbase = max(float(np.median(rowprof[rowprof > 0])) if (rowprof > 0).any() else 0.0, 1e-6)
        yt, ct = pick(rowprof, yt0, +1)
        yb, cb = pick(rowprof, yb0, -1)
        conf = [cl / cbase, cr / cbase, ct / rbase, cb / rbase]

    W, H = (xr - xl) * res, (yb - yt) * res
    if W <= 0 or H <= 0:
        return None
    pts = np.array([[xl, yt], [xr, yt], [xr, yb], [xl, yb]], np.float32)
    Minv = cv2.invertAffineTransform(cv2.getRotationMatrix2D((cx, cy), best_ang, 1.0))
    world = cv2.transform(pts.reshape(-1, 1, 2), Minv).reshape(-1, 2)

    return {"l_m": round(max(W, H), 2), "w_m": round(min(W, H), 2),
            "angle": round(best_ang % 180, 2), "pts": world,
            "edge_strength": [round(c, 1) for c in conf]}


def find_divisions(chroma, rect, n, res, tol_m=6.0, gap_m=0.0):
    """Locate the cross-pitch side lines on a parent field, all at once.

    Fitting each section on its own lets neighbouring thirds disagree about
    where the line between them is. The sections are evenly pitched, so fitting
    one (offset, width, gap) triple to the whole set is both more robust and
    self-consistent.

    `gap_m` is the widest run-off to consider *between* sections. At zero the
    sections are contiguous and share n+1 boundaries, which is what Prazacka
    wants. Sterboholy does not: its three pitches are separated by ~3.8 m of
    spare turf and each has its own pair of side lines, so taking a section's
    west edge from its neighbour's east edge made it ~3.8 m too wide on that
    side -- with the goals then visibly off-centre. Fitting the gap puts every
    edge on its own paint.

    Returns one (lo, hi) pair per section; with no gap the pairs share endpoints
    and this is the old n+1 boundaries by another name.
    """
    (cx, cy), (w, h), ang = rect
    long_is_w = w >= h
    L = (w if long_is_w else h)
    R = _rotate(chroma, (cx, cy), ang)
    if long_is_w:
        lo_i, hi_i = int(cy - h / 2), int(cy + h / 2)
        prof = R[max(lo_i, 0):hi_i, :].mean(axis=0)
        start0 = cx - L / 2
    else:
        lo_i, hi_i = int(cx - w / 2), int(cx + w / 2)
        prof = R[:, max(lo_i, 0):hi_i].mean(axis=1)
        start0 = cy - L / 2

    span = tol_m / res
    # allow the marked pitches to leave a margin inside the parent
    totals = np.arange(L * 0.75, L * 1.001, 2.0)
    # Contiguous sections start within tol_m of the parent edge. Gapped ones do
    # not -- Sterboholy's first side line is 9.5 m in -- so the block is free to
    # sit anywhere it fits inside the parent.
    starts = (np.arange(start0 - span, start0 + span + 1, 2.0) if not gap_m
              else np.arange(start0, start0 + L, 2.0))
    best, best_score = None, -1.0
    for gap in np.arange(0.0, gap_m / res + 0.01, 2.0):
        steps = (totals - (n - 1) * gap) / n
        ok = steps > 0
        if not ok.any():
            continue
        tot, step_v = totals[ok], steps[ok]
        for start in starts:
            los = start + np.arange(n)[:, None] * (step_v + gap)
            # with no gap the section edges coincide: score the n+1 distinct
            # boundaries, not the interior ones twice
            edges = (np.vstack([los, los + step_v]) if gap else
                     start + np.arange(n + 1)[:, None] * step_v)
            idx = np.round(edges).astype(int)
            valid = ((idx.min(axis=0) >= 0) & (idx.max(axis=0) < len(prof))
                     & (start - start0 + tot <= L))
            if not valid.any():
                continue
            scores = np.where(valid, prof[np.clip(idx, 0, len(prof) - 1)].mean(axis=0), -1.0)
            i = int(np.argmax(scores))
            if scores[i] > best_score:
                best_score = float(scores[i])
                best = (float(start), float(step_v[i]), float(gap))
    if best is None:
        return None, 0.0
    start, step, gap = best
    base = max(float(np.median(prof[prof > 0])) if (prof > 0).any() else 0.0, 1e-6)
    # One width for every section is the right model but not the last word: the
    # thirds differ by a few tens of centimetres. Let each edge settle on its
    # own peak, close enough that it cannot leave the line it was fitted to.
    edges = [(_snap(prof, start + i * (step + gap), res, base),
              _snap(prof, start + i * (step + gap) + step, res, base))
             for i in range(n)]
    strength = round(best_score / base, 1)
    return {"edges": edges, "gap": gap, "long_is_w": long_is_w, "angle": ang,
            "centre": (cx, cy), "size": (w, h)}, strength


def find_goal_lines(white, div, res, sep_m=(42.0, 50.0), flush=None):
    """Find the cross-pitch goal lines: a pair of white lines ~45 m apart.

    They are *not* the parent's touchlines. The marked cross-pitches are inset,
    and asymmetrically -- at Sterboholy the spare ground is all at one end -- so
    the pair has to be found rather than assumed centred or flush.

    Several pairs are plausible and raw peak strength does not pick the right
    one: at Sterboholy it favours the pair flush with the *south* touchline when
    the spare ground is in fact at the south. `flush` names the compass end the
    marked pitches start from, which resolves it.
    """
    cx, cy = div["centre"]
    w, h = div["size"]
    R = _rotate(white, (cx, cy), div["angle"])
    if div["long_is_w"]:                      # divisions vertical -> goals horizontal
        lo, hi = int(cx - w / 2), int(cx + w / 2)
        prof = R[:, max(lo, 0):hi].mean(axis=1)
        c0, extent = cy, h
    else:
        lo, hi = int(cy - h / 2), int(cy + h / 2)
        prof = R[max(lo, 0):hi, :].mean(axis=0)
        c0, extent = cx, w
    # keep clear of the turf rim, which is bright but is not a painted line
    rim = 1.5 / res
    a = int(max(c0 - extent / 2 + rim, 0))
    b = int(min(c0 + extent / 2 - rim, len(prof) - 1))
    lo_px, hi_px = int(sep_m[0] / res), int(sep_m[1] / res)

    flush_at_start = None
    if flush:
        # does a rising profile index run south/east, or north/west?
        cxx, cyy = div["centre"]
        Minv = cv2.invertAffineTransform(
            cv2.getRotationMatrix2D((cxx, cyy), div["angle"], 1.0))
        step = (0.0, 100.0) if div["long_is_w"] else (100.0, 0.0)
        p0 = cv2.transform(np.array([[[cxx, cyy]]], np.float32), Minv).reshape(2)
        p1 = cv2.transform(np.array([[[cxx + step[0], cyy + step[1]]]],
                                    np.float32), Minv).reshape(2)
        d = p1 - p0                     # +x east, +y south
        toward = {"N": -d[1], "S": d[1], "W": -d[0], "E": d[0]}[flush]
        flush_at_start = toward < 0     # the flush end is at the low-index side
    margin = int(6.0 / res)

    # Only genuine line peaks are candidates. Allowing any index lets the pair
    # settle on the bright turf rim instead of a painted line.
    win = max(int(0.5 / res), 2)
    base = float(np.median(prof[a:b])) if b > a else 0.0
    peaks = [i for i in range(a, b)
             if prof[i] >= prof[max(i - win, 0):i + win + 1].max()
             and prof[i] > 2.0 * base]

    best, best_score = None, -1.0
    for i in peaks:
        if flush_at_start is True and i > a + margin:
            continue
        for j in peaks:
            if not (lo_px <= j - i <= hi_px):
                continue
            if flush_at_start is False and j < b - margin:
                continue
            score = min(float(prof[i]), float(prof[j]))
            if score > best_score:
                best, best_score = (i, j), score
    if best is None:
        return None, 0.0
    i, j = best
    base = max(float(np.median(prof[prof > 0])) if (prof > 0).any() else 0.0, 1e-6)
    return (_subpix(prof, i), _subpix(prof, j)), round(best_score / base, 1)


def _compass(nx, ny):
    """Compass letter for an outward normal in image coords (+x E, +y S)."""
    return ("E" if nx > 0 else "W") if abs(nx) > abs(ny) else ("S" if ny > 0 else "N")


def nudge_rect(pts, nudges, res):
    """Move individual edges of a fitted rectangle, in metres, by compass side.

    Positive moves that edge inward. The automatic fit lands on the wrong line
    at a few grounds -- a bright kerb, a stray marking -- and this is the escape
    hatch for saying so per venue rather than bending the detector until it
    breaks somewhere else.
    """
    if not nudges:
        return pts
    rect = cv2.minAreaRect(np.array(pts, np.float32))
    (cx, cy), (w, h), ang = rect
    th = np.radians(ang)
    u = np.array([np.cos(th), np.sin(th)])      # along w
    vv = np.array([-np.sin(th), np.cos(th)])    # along h
    c = np.array([cx, cy], np.float64)
    for axis, half in ((u, w / 2), (vv, h / 2)):
        pass
    dims = {"u": w, "v": h}
    for name, axis in (("u", u), ("v", vv)):
        for sign in (+1, -1):
            d = float(nudges.get(_compass(*(axis * sign)), 0.0)) / res
            if d:
                dims[name] -= d
                c = c - axis * sign * (d / 2.0)
    new = ((float(c[0]), float(c[1])), (dims["u"], dims["v"]), ang)
    return cv2.boxPoints(new)


def _apply_goals(div, target, goals, res, fit):
    """Replace the fitted length with the shared goal-line pair.

    The rectangle comes out at the angle `fit` refined, not the turf carpet's:
    at Sterboholy the paint sits 0.7 deg off the carpet, and emitting the carpet
    angle left the side lines crossing the blue paint instead of lying along it
    -- while the JSON reported the refined angle, which was simply untrue of the
    rectangle beside it.
    """
    (tcx, tcy), (tw, th), ang = target
    g0, g1 = sorted(goals)
    length = (g1 - g0) * res
    mid = (g0 + g1) / 2.0
    cx, cy = div["centre"]
    Minv = cv2.invertAffineTransform(cv2.getRotationMatrix2D((cx, cy), ang, 1.0))
    # target centre expressed in the rotated frame
    M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
    tc_rot = cv2.transform(np.array([[[tcx, tcy]]], np.float32), M).reshape(2)
    if div["long_is_w"]:
        c_rot = (float(tc_rot[0]), float(mid))
        size = (tw, g1 - g0)
    else:
        c_rot = (float(mid), float(tc_rot[1]))
        size = (g1 - g0, th)
    c = cv2.transform(np.array([[c_rot]], np.float32), Minv).reshape(2)
    paint = fit["angle"]                     # reported modulo 180
    while paint - ang > 90:
        paint -= 180
    while ang - paint > 90:
        paint += 180
    rect = ((float(c[0]), float(c[1])), size, paint)
    pts = cv2.boxPoints(rect)
    width = min(fit["l_m"], fit["w_m"])
    return {**fit, "l_m": round(max(length, width), 2),
            "w_m": round(min(length, width), 2), "pts": pts}


def rects_from_divisions(div, n, first_end="W"):
    """Turn the fitted (lo, hi) edge pairs into n section rectangles, ordered
    from `first_end`."""
    cx, cy = div["centre"]
    w, h = div["size"]
    ang = div["angle"]
    e = div["edges"]
    Minv = cv2.invertAffineTransform(cv2.getRotationMatrix2D((cx, cy), ang, 1.0))
    out = []
    for i in range(n):
        a, b = e[i]
        if div["long_is_w"]:
            c_rot, size = ((a + b) / 2.0, cy), (b - a, h)
        else:
            c_rot, size = (cx, (a + b) / 2.0), (w, b - a)
        c = cv2.transform(np.array([[c_rot]], np.float32), Minv).reshape(2)
        out.append(((float(c[0]), float(c[1])), size, ang))
    # order so index 0 sits at the requested end (+x is east, +y is south)
    key = {"W": lambda r: r[0][0], "E": lambda r: -r[0][0],
           "N": lambda r: r[0][1], "S": lambda r: -r[0][1]}.get(first_end,
                                                                lambda r: r[0][0])
    return sorted(out, key=key)


def section_rects(rect, n, first_end="W"):
    """Split a parent field into n cross-pitches along its long axis.

    Returns the sections ordered so that index 0 is the one at `first_end`,
    matching how PSMF numbers them ("c. 1 je nejblize hale").
    """
    (cx, cy), (w, h), ang = rect
    long_is_w = w >= h
    L, S = (w, h) if long_is_w else (h, w)
    th = np.radians(ang if long_is_w else ang + 90)
    u = np.array([np.cos(th), np.sin(th)])       # +x east, +y south
    # orient u so it points away from the "first" end
    east, south = u[0], -u[1]
    towards = {"W": east, "E": -east, "N": -south, "S": south}.get(first_end, east)
    if towards < 0:
        u = -u
    step = L / n
    out = []
    for i in range(n):
        off = (i - (n - 1) / 2.0) * step
        c = np.array([cx, cy]) + u * off
        size = (step, S) if long_is_w else (S, step)
        out.append(((float(c[0]), float(c[1])), size, ang))
    return out


def detect(img, geo, roi_m, cfg):
    best, turf, origin = measure_roi(img, geo, roi_m)
    if best is None:
        return []
    (rcx, rcy), _, ang = best["rect"]
    lon, lat = px_to_lonlat((rcx, rcy), geo)
    # markings are painted ON the turf: gating by the turf mask removes the
    # fence and kerb just outside it, which otherwise capture the edge search
    white = line_response(img, geo["res"], mode="white")

    cand = {
        "candidate": 1,
        "turf_l_m": round(best["long_m"], 1),
        "turf_w_m": round(best["short_m"], 1),
        "turf_area_m2": round(best["long_m"] * best["short_m"]),
        "aspect": round(best["long_m"] / best["short_m"], 2),
        "rectness": round(best["rectness"], 3),
        "border_support": round(best["border"], 3),
        "bearing_deg": round(ang % 180, 1),
        "centre_lat": round(lat, 7), "centre_lon": round(lon, 7),
        "rect_px": [[round(float(a), 1), round(float(b), 1)]
                    for a, b in cv2.boxPoints(best["rect"])],
        "kind": "whole_pitch",
    }
    n = cfg.get("sections")
    if n:
        # numbered cross-pitches: the parent's long side splits n ways, each
        # section plays across the parent's width
        idx = int(cfg.get("section_index", 1))
        cand["kind"] = f"section_{idx}_of_{n}"
        cand["parent_l_m"] = cand["turf_l_m"]
        cand["parent_w_m"] = cand["turf_w_m"]
        secs = section_rects(best["rect"], n, cfg.get("first_end", "W"))
        cand["section_rects_px"] = [[[round(float(a), 1), round(float(b), 1)]
                                     for a, b in cv2.boxPoints(r)] for r in secs]
        target = secs[idx - 1]
        cand["section_order"] = f'section 1 at the {cfg.get("first_end", "W")} end'
    else:
        target = best["rect"]

    if n:
        # A cross-pitch is bounded by the parent's white touchlines at the goal
        # ends and by faint blue division lines at the sides. Fit the divisions
        # across the whole parent so neighbouring sections agree, then fit only
        # the goal lines here.
        chroma = line_response(img, geo["res"], mode="chroma")
        div, div_strength = find_divisions(chroma, best["rect"], n, geo["res"],
                                           gap_m=cfg.get("section_gap_m", 0.0))
        if div:
            secs = rects_from_divisions(div, n, cfg.get("first_end", "W"))
            cand["section_rects_px"] = [[[round(float(a), 1), round(float(b), 1)]
                                         for a, b in cv2.boxPoints(r)] for r in secs]
            target = secs[idx - 1]
            cand["division_strength"] = div_strength
            cand["section_gap_m"] = round(div["gap"] * geo["res"], 2)
            resp_cols = chroma if div["long_is_w"] else white
            resp_rows = white if div["long_is_w"] else chroma
            # The goal lines are shared by all three sections and are inset
            # from the parent touchlines, so find the pair once for the whole
            # field and give every section the same length.
            goals, goal_strength = find_goal_lines(white, div, geo["res"],
                                                   flush=cfg.get("goal_flush"))
            fit = fit_painted(resp_cols, resp_rows, target, geo["res"],
                              out_m=0.8, in_m=3.0, fix_cols=div["long_is_w"])
            if goals and fit:
                fit = _apply_goals(div, target, goals, geo["res"], fit)
                cand["goal_strength"] = goal_strength
        else:
            fit = fit_painted(white, white, target, geo["res"],
                          out_m=cfg.get("fit_out_m", 0.4),
                          in_m=cfg.get("fit_in_m", 3.5))
    else:
        fit = fit_painted(white, white, target, geo["res"],
                          out_m=cfg.get("fit_out_m", 0.4),
                          in_m=cfg.get("fit_in_m", 3.5))
    if fit:
        nudged = nudge_rect(fit["pts"], cfg.get("edge_nudge_m"), geo["res"])
        if cfg.get("edge_nudge_m"):
            r = cv2.minAreaRect(np.array(nudged, np.float32))
            fit = {**fit, "pts": nudged,
                   "l_m": round(max(r[1]) * geo["res"], 2),
                   "w_m": round(min(r[1]) * geo["res"], 2)}
            cand["edge_nudged"] = cfg["edge_nudge_m"]
        cand["painted_l_m"] = fit["l_m"]
        cand["painted_w_m"] = fit["w_m"]
        cand["painted_angle"] = fit["angle"]
        cand["edge_strength"] = fit["edge_strength"]
        cand["play_l_m"], cand["play_w_m"] = fit["l_m"], fit["w_m"]
        cand["play_src"] = "painted lines"
        cand["play_rect_px"] = [[round(float(a), 1), round(float(b), 1)]
                                for a, b in fit["pts"]]
    else:
        cand["play_l_m"] = round(min(target[1]) * geo["res"], 1) if n else cand["turf_l_m"]
        cand["play_w_m"] = round(max(target[1]) * geo["res"] / (n or 1), 1) if n else cand["turf_w_m"]
        cand["play_src"] = "turf extent (no line fit)"
        cand["play_rect_px"] = [[round(float(a), 1), round(float(b), 1)]
                                for a, b in cv2.boxPoints(target)]
    cand.setdefault("play_rect_px", cand["rect_px"])
    return [cand]


# --------------------------------------------------------------------------- output
def _label(img, text, org, scale=1.0, colour=(0, 255, 255)):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 6)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, colour, 2)


def overview(img, cands, geo, code, name, path):
    vis = img.copy()
    c = geo["size"] // 2
    cv2.drawMarker(vis, (c, c), (0, 0, 255), cv2.MARKER_CROSS, 46, 3)
    _label(vis, "PSMF GPS", (c + 26, c - 12), 0.9, (0, 0, 255))
    for cand in cands:
        # the parent field, thin, when this code is only a section of it
        if cand.get("section_rects_px"):
            cv2.polylines(vis, [np.array(cand["rect_px"], np.int32)], True, (200, 200, 200), 2)
            for box in cand["section_rects_px"]:
                cv2.polylines(vis, [np.array(box, np.int32)], True, (200, 200, 200), 2)
        box = np.array(cand["play_rect_px"], dtype=np.int32)
        cv2.polylines(vis, [box], True, (0, 255, 255), 4)
        _label(vis, f'{cand["play_l_m"]:.0f}x{cand["play_w_m"]:.0f} m',
               tuple(box[1] + np.array([6, -12])), 1.1)
    _label(vis, f"{code} - {name}  ({geo['source']} {geo['res']} m/px)",
           (16, 44), 1.1, (255, 255, 255))
    cv2.imwrite(str(path), vis)


def pitch_crop(img, cand, geo, code, name, path, pad_m=12.0):
    """Zoomed photo of one pitch with its measured rectangle drawn on.

    For a numbered cross-pitch the crop frames the whole parent field and shows
    all the sections, so the pitch can be located within the ground it sits on.
    """
    play = np.array(cand["play_rect_px"], dtype=np.float32)
    frame = np.array(cand["rect_px"], dtype=np.float32)   # parent when sectioned
    pad = pad_m / geo["res"]
    x0, y0 = np.floor(frame.min(0) - pad).astype(int)
    x1, y1 = np.ceil(frame.max(0) + pad).astype(int)
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, img.shape[1]), min(y1, img.shape[0])
    crop = img[y0:y1, x0:x1].copy()
    if crop.size == 0:
        return
    shift = np.array([x0, y0])

    if cand.get("section_rects_px"):
        for box in cand["section_rects_px"]:
            cv2.polylines(crop, [(np.array(box, np.float32) - shift).astype(np.int32)],
                          True, (210, 210, 210), 2)

    sp = (play - shift).astype(np.int32)
    cv2.polylines(crop, [sp], True, (0, 255, 255), 3)
    for (px, py) in sp:
        cv2.circle(crop, (int(px), int(py)), 6, (0, 0, 255), -1)

    def side(a, b, text):
        mid = ((sp[a] + sp[b]) // 2).astype(int)
        _label(crop, text, (int(mid[0]) - 60, int(mid[1])), 0.85)

    side(0, 1, f'{np.linalg.norm(sp[0] - sp[1]) * geo["res"]:.1f} m')
    side(1, 2, f'{np.linalg.norm(sp[1] - sp[2]) * geo["res"]:.1f} m')

    hdr = f'{code}  {cand["play_l_m"]} x {cand["play_w_m"]} m  [{cand["kind"]}]'
    _label(crop, hdr, (12, 30), 0.75, (255, 255, 255))
    _label(crop, name, (12, 58), 0.7, (255, 255, 255))
    cv2.imwrite(str(path), crop)


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", help="comma-separated venue codes (default: all fixtures)")
    ap.add_argument("--half", type=float, default=100.0, help="crop half-width, m")
    ap.add_argument("--res", type=float, default=0.05, help="metres per pixel")
    ap.add_argument("--source", default="ipr", choices=["ipr", "cuzk"])
    ap.add_argument("--auto-layer", action="store_true",
                    help="probe the archive and use the sharpest capture per venue")
    args = ap.parse_args()

    venues = load_venues()
    overrides = json.loads((DATA / "overrides.json").read_text("utf-8"))
    fixtures = json.loads((DATA / "fixtures.json").read_text("utf-8"))["fixtures"]
    codes = ([c.strip() for c in args.codes.split(",")] if args.codes
             else sorted({f["venue_code"] for f in fixtures}
                         | {k for k, v in venues.items() if v.get("training")}))

    OUT.mkdir(exist_ok=True)
    # a --codes run must not drop the venues it did not touch
    out_path = OUT / "measurements.json"
    results = (json.loads(out_path.read_text("utf-8"))
               if out_path.exists() and args.codes else {})
    for code in codes:
        v = venues.get(code)
        if not v:
            print(f"{code:<6} SKIP - not in the PSMF venue directory", file=sys.stderr)
            continue
        try:
            cfg = overrides.get(code, {})
            layer = cfg.get("layer")
            if layer is None and args.auto_layer:
                layer, sc = pick_layer(v["lat"], v["lon"], args.res, code)
                print(f'  {code}: capture "{IPR_LAYERS.get(layer, layer)}" '
                      f'(contrast {sc})', file=sys.stderr)
            img, geo = fetch_crop(v["lat"], v["lon"], args.half, args.res,
                                  code, args.source, layer=layer)
            roi = cfg.get("roi_m", [-args.half, args.half, -args.half, args.half])
            cands = detect(img, geo, roi, cfg)
            overview(img, cands, geo, code, v["name"], OUT / f"{code}.png")
            for cand in cands:
                pitch_crop(img, cand, geo, code, v["name"],
                           OUT / f'{code}_pitch{cand["candidate"]}.png')
        except Exception as e:
            print(f"{code:<6} FAIL - {e}", file=sys.stderr)
            results[code] = {"venue": v, "error": str(e), "candidates": []}
            continue
        results[code] = {"venue": v, "geo": geo, "candidates": cands}
        parts = []
        for c in cands:
            t = f'{c["play_l_m"]}x{c["play_w_m"]} m [{c["kind"]}]'
            t += f' turf {c["turf_l_m"]}x{c["turf_w_m"]}'
            if c.get("edge_strength"):
                t += f' edges {c["edge_strength"]}'
            if c["kind"] != "whole_pitch":
                t += f' parent {c["parent_l_m"]}x{c["parent_w_m"]}'
            t += f'  rect={c["rectness"]:.2f} border={c["border_support"]:.2f}'
            parts.append(t)
        summary = ", ".join(parts) or "none"
        print(f'{code:<6} {v["name"]:<16} {len(cands)}: {summary}')

    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n-> {OUT/'measurements.json'}; overview + per-pitch PNGs in {OUT}/")


if __name__ == "__main__":
    main()
