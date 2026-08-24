#!/usr/bin/env python3
"""Check a fitted pitch against the markings, and say by how much it is off.

Every correction this project has needed came from two questions: which edge is
which compass side, and how far is each edge from the nearest painted line.
Answering them by eye is slow and error-prone -- the rectangles are rotated
90-120 degrees, so "left" in a north-up view is often the rectangle's south edge.

    ./.venv/bin/python diagnose.py --codes STER2,STER3

prints the offset from each edge to the nearest line peak, with the peak's
strength relative to background, and writes a compass-labelled image to
out/diag_<CODE>.png.

Offsets are signed along the profile axis, NOT relative to "inward": whether a
positive offset means nudge-in or nudge-out depends on which end of the axis
that edge sits on, and it is inverted between the two opposite edges. Do not
reason it out -- apply a nudge, re-run this, and check the offset moved toward
zero. A well-fitted edge reads about 0.0 with a strong peak (MOTO4 sits at
0.00-0.02 on all four, at 16-24x background).
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import cv2
import numpy as np

import measure_pitches as M

ROOT = Path(__file__).parent


def peaks_near(prof, pos, res, rng=4.0, min_rel=2.0, top=3):
    a, b = int(pos - rng / res), int(pos + rng / res)
    a, b = max(a, 1), min(b, len(prof) - 2)
    pos_vals = prof[prof > 0]
    base = float(np.median(pos_vals)) if pos_vals.size else 0.0
    if base <= 0:
        return []
    out = [(round(float((i - pos) * res), 2), round(float(prof[i] / base), 1))
           for i in range(a, b)
           if prof[i] >= prof[i - 1] and prof[i] >= prof[i + 1] and prof[i] > min_rel * base]
    return sorted(out, key=lambda t: -t[1])[:top]


def diagnose(code, venues, overrides, meas, res, half):
    v, cfg = venues[code], overrides.get(code, {})
    cand = (meas.get(code, {}).get("candidates") or [None])[0]
    if cand is None:
        print(f"{code}: no fit")
        return
    img, geo = M.fetch_crop(v["lat"], v["lon"], half, res, code, layer=cfg.get("layer"))
    # same default as measure_pitches.main(): a venue needs no override to be
    # looked at, which matters when you are working through a backlog of them
    roi = cfg.get("roi_m", [-half, half, -half, half])
    best, _, _ = M.measure_roi(img, geo, roi)
    (pcx, pcy), (pw, ph), turf_ang = best["rect"]
    # Profile in the frame of the *paint*, not of the turf carpet. At
    # Sterboholy the markings sit 0.7 deg off the carpet, which is half a metre
    # of drift over a 48 m line: enough to smear a faint blue touchline flat and
    # have this print "no line found" for an edge sitting right on it.
    ang = cand.get("painted_angle", turf_ang)
    while ang - turf_ang > 90:
        ang -= 180
    while turf_ang - ang > 90:
        ang += 180

    white = M.line_response(img, res, mode="white")
    chroma = M.line_response(img, res, mode="chroma")
    orange = M.line_response(img, res, mode="orange")
    pts = np.array(cand["play_rect_px"], np.float32)
    rot = cv2.getRotationMatrix2D((pcx, pcy), ang, 1.0)
    rp = cv2.transform(pts.reshape(-1, 1, 2), rot).reshape(-1, 2)
    x0, x1 = float(rp[:, 0].min()), float(rp[:, 0].max())
    y0, y1 = float(rp[:, 1].min()), float(rp[:, 1].max())

    Rw, Rc = M._rotate(white, (pcx, pcy), ang), M._rotate(chroma, (pcx, pcy), ang)
    Ro = M._rotate(orange, (pcx, pcy), ang)
    colW = Rw[int(y0):int(y1), :].mean(axis=0)
    rowW = Rw[:, int(x0):int(x1)].mean(axis=1)
    colC = Rc[int(y0):int(y1), :].mean(axis=0)
    rowC = Rc[:, int(x0):int(x1)].mean(axis=1)
    colO = Ro[int(y0):int(y1), :].mean(axis=0)
    rowO = Ro[:, int(x0):int(x1)].mean(axis=1)

    # Sections: the side lines run along the parent's long axis. They are blue
    # at Sterboholy and white-ish at Prazacka, so try chroma and fall back to
    # luminance rather than reporting "no line found" for an edge that is on
    # paint this profile simply cannot see.
    sectioned = bool(cfg.get("sections"))
    div_on_x = pw >= ph
    col_src = (colC if (sectioned and div_on_x) else colW)
    row_src = (rowC if (sectioned and not div_on_x) else rowW)
    # blue first, then white, then orange: three grounds, three paints
    col_alt = [colW, colO] if col_src is colC else []
    row_alt = [rowW, rowO] if row_src is rowC else []

    ctr = pts.mean(0)
    print(f"--- {code}  {cand['play_l_m']} x {cand['play_w_m']} m   "
          f"angle {ang:.2f}   parent {pw * res:.1f} x {ph * res:.1f} m")
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        mid = (a + b) / 2.0
        n = mid - ctr
        n = n / np.linalg.norm(n)
        side = M._compass(float(n[0]), float(n[1]))
        # Which profile, and which end of it? Decide by whichever of the four
        # rotated-frame bounds the edge midpoint actually sits on. Inferring it
        # from the edge normal instead made opposite edges resolve to the same
        # bound whenever the rectangle was strongly rotated.
        mr = cv2.transform(mid.reshape(1, 1, 2), rot).reshape(2)
        opts = [(abs(float(mr[0]) - x0), col_src, col_alt, x0),
                (abs(float(mr[0]) - x1), col_src, col_alt, x1),
                (abs(float(mr[1]) - y0), row_src, row_alt, y0),
                (abs(float(mr[1]) - y1), row_src, row_alt, y1)]
        _, prof, alt, pos = min(opts, key=lambda o: o[0])
        # Three grounds, three paints: blue at Sterboholy, white at Prazacka,
        # orange at Podvinny mlyn. Ask each profile and keep whichever has a
        # peak nearest this edge -- taking the first that finds *any* peak lets
        # a bit of turf noise in one channel outrank the real line in another.
        best = None
        for src in [prof, *alt]:
            got = peaks_near(src, pos, res)
            if not got:
                continue
            near = min(got, key=lambda t: abs(t[0]))
            score = (abs(near[0]), -near[1])
            if best is None or score < best[0]:
                best = (score, src, got)
        prof, pk = (best[1], best[2]) if best else (prof, [])
        kind = ("blue" if prof is colC or prof is rowC
                else "orange" if prof is colO or prof is rowO else "white")
        # The strongest peak nearby is often the kerb or the surround rather
        # than a marking, so report the closest one separately: that is the
        # number to act on.
        closest = min(pk, key=lambda t: abs(t[0])) if pk else None
        head = f"{closest[0]:+.2f} m ({closest[1]}x)" if closest else "no line found"
        print(f"    {side} edge ({kind:5s}) {head:22s} candidates: {pk}")
    _render(img, pts, code, cand, ROOT / "out" / f"diag_{code}.png", res)


def _render(img, pts, code, cand, path, res, pad_m=8.0):
    vis = img.copy()
    cv2.polylines(vis, [pts.astype(np.int32)], True, (0, 255, 255), 3)
    ctr = pts.mean(0)
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        mid = (a + b) / 2.0
        n = mid - ctr
        n = n / np.linalg.norm(n)
        label = M._compass(float(n[0]), float(n[1]))
        org = tuple((mid + n * (2.5 / res)).astype(int))
        cv2.putText(vis, label, org, cv2.FONT_HERSHEY_SIMPLEX, 1.8, (0, 0, 0), 8)
        cv2.putText(vis, label, org, cv2.FONT_HERSHEY_SIMPLEX, 1.8, (0, 0, 255), 3)
    for p in pts:
        cv2.circle(vis, tuple(p.astype(int)), 8, (0, 0, 255), 2)
    pad = int(pad_m / res)
    x0, y0 = np.floor(pts.min(0) - pad).astype(int)
    x1, y1 = np.ceil(pts.max(0) + pad).astype(int)
    crop = vis[max(y0, 0):y1, max(x0, 0):x1]
    h, w = crop.shape[:2]
    sc = min(1100 / w, 1100 / h)
    out = cv2.resize(crop, (int(w * sc), int(h * sc)), interpolation=cv2.INTER_AREA)
    txt = f"{code}  {cand['play_l_m']} x {cand['play_w_m']} m"
    cv2.putText(out, txt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 5)
    cv2.putText(out, txt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 1)
    path.parent.mkdir(exist_ok=True)
    cv2.imwrite(str(path), out)
    print(f"    -> {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", help="comma-separated venue codes (default: all measured)")
    ap.add_argument("--res", type=float, default=0.05)
    ap.add_argument("--half", type=float, default=100.0)
    args = ap.parse_args()

    venues = M.load_venues()
    overrides = json.loads((ROOT / "data/overrides.json").read_text("utf-8"))
    meas = json.loads((ROOT / "out/measurements.json").read_text("utf-8"))
    codes = ([c.strip() for c in args.codes.split(",")] if args.codes
             else [c for c in meas if not c.startswith("_")])
    for code in codes:
        diagnose(code, venues, overrides, meas, args.res, args.half)


if __name__ == "__main__":
    main()
