#!/usr/bin/env python3
"""Join fixtures to measurements and emit the season pitch table."""
import json
from pathlib import Path

ROOT = Path(__file__).parent
fx = json.loads((ROOT / "data/fixtures.json").read_text("utf-8"))
ms = json.loads((ROOT / "out/measurements.json").read_text("utf-8"))
TRAINING = [c for c, m in ms.items()
            if not c.startswith("_") and m.get("venue", {}).get("training")]
ov = json.loads((ROOT / "data/overrides.json").read_text("utf-8"))

rows = []
for f in fx["fixtures"]:
    code = f["venue_code"]
    m = ms.get(code, {})
    c = (m.get("candidates") or [None])[0]
    v = m.get("venue", {})
    edges = (c or {}).get("edge_strength") or []
    rows.append({
        "round": f["round"], "date": f["date"], "time": f["time"],
        "opponent": f["opponent"], "home": f["home"], "code": code,
        "venue": v.get("name", "?"),
        # whole metres for reading; the annotated images keep the precise fit
        "l": c and round(c["play_l_m"]), "w": c and round(c["play_w_m"]),
        "l_exact": c and c["play_l_m"], "w_exact": c and c["play_w_m"],
        "area": c and round(round(c["play_l_m"]) * round(c["play_w_m"])),
        "kind": c and c["kind"],
        "src": c and c.get("play_src", ""),
        "turf": c and f'{round(c["turf_l_m"])} x {round(c["turf_w_m"])}',
        "capture": m.get("geo", {}).get("capture", "?"),
        "edges": edges,
        # every edge backed by a clear line -> trust it; a weak edge means the
        # marking is faint there and the number is a best fit, not a reading
        "conf": ("high" if edges and min(edges) >= 4
                 else "medium" if edges and min(edges) >= 2 else "low"),
        "note": ov.get(code, {}).get("note", ""),
    })

hdr = ("| R | Date | Venue | Code | Opponent | Pitch size (m) | Area (m2) |\n"
       "|---:|---|---|---|---|---|---:|")
lines = [hdr]
for r in rows:
    dim = f'{r["l"]} x {r["w"]}' if r["l"] else "n/a"
    kind = {"whole_pitch": "whole pitch"}.get(r["kind"] or "", (r["kind"] or "").replace("_", " "))
    lines.append(f'| {r["round"]} | {r["date"]} {r["time"]} | {r["venue"]} | {r["code"]} | '
                 f'{r["opponent"]} | {dim} | {r["area"] or "-"} |')
table = "\n".join(lines)
(ROOT / "out/table.md").write_text(table + "\n", "utf-8")
(ROOT / "out/table.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")
print(table)

for code in TRAINING:
    c = (ms[code].get("candidates") or [None])[0]
    if c:
        print(f'\nTraining pitch: {ms[code]["venue"]["name"]}  '
              f'{round(c["play_l_m"])} x {round(c["play_w_m"])} m  '
              f'({round(round(c["play_l_m"]) * round(c["play_w_m"]))} m2)')

uniq = {r["code"]: r for r in rows}
print("\nDistinct pitches:", len(uniq))
sz = sorted((r["l"] * r["w"], r["code"]) for r in uniq.values() if r["l"])
print(f'Smallest: {sz[0][1]} {round(sz[0][0])} m2   Largest: {sz[-1][1]} {round(sz[-1][0])} m2')
