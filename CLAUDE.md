# CLAUDE.md — working notes

Measures the painted pitch at each PSMF fixture venue from Prague orthophoto
imagery. Read this before changing the detector; most of it was learned the
hard way and several "obvious" fixes here are wrong.

## Layout

```
scrape_psmf.py      fixtures + venue directory  -> data/fixtures.json, data/venues.json
data/extra_venues.json  venues not on the fixture list (our training pitch)
measure_pitches.py  segment turf, fit the lines -> out/measurements.json, out/*.png
diagnose.py         how far is each edge off?   -> out/diag_*.png
make_table.py       season table                -> out/table.md, out/table.json
build_page.py       self-contained HTML report  -> out/pitches.html
data/overrides.json the per-venue human input   (the important file)
```

## New season, from scratch

```bash
./.venv/bin/python scrape_psmf.py "https://www.psmf.cz/souteze/<season>/<group>/tymy/<team>/"
./.venv/bin/python measure_pitches.py --auto-layer   # drop --auto-layer once layers are pinned
./.venv/bin/python diagnose.py                       # check every edge
./.venv/bin/python make_table.py && ./.venv/bin/python build_page.py
```

`scrape_psmf.py` filters the fixture list to rows where our team is one of the
two named sides — the team page also lists other teams' matches at the same
venue and day, which is easy to miss.

Venue codes carry over between seasons, so an existing entry in
`data/overrides.json` usually still applies. Only genuinely new codes need work.

## Adding a venue

1. Run `measure_pitches.py --codes NEW1`. If it says "not in the venue
   directory", the code is missing from psmf.cz/hriste — nothing to do here.
2. Look at `out/NEW1.png`. The PSMF GPS point is one per *areál*, so a
   multi-pitch ground will grab the wrong blob or merge two.
3. Add a `roi_m` to `data/overrides.json`: `[x_min, x_max, y_min, y_max]` in
   metres from the GPS point, x east, y south. Make it stop in the gap between
   pitches — if the ROI clips into a neighbour, the blob fills the ROI, scores a
   perfect rectangularity with zero border support, and is rejected.
4. Run `diagnose.py --codes NEW1` and nudge until every edge reads ~0.0.

### A venue that is not on the fixture list

Our training pitch at Újezd is measured for comparison. Non-PSMF venues go in
`data/extra_venues.json`, not `data/venues.json`, because `scrape_psmf.py`
rewrites the latter wholesale and would drop them. Give the entry
`"training": true` and it is measured automatically, kept out of the fixture
table, and shown on the page as a scale comparison.

### overrides.json keys

| key | what it does |
| --- | --- |
| `roi_m` | isolates the pitch we play from its neighbours |
| `layer` | which capture (see IPR_LAYERS); leaf-off wins wherever trees are |
| `fit_out_m` / `fit_in_m` | touchline search band, for grounds with a bright kerb |
| `sections` / `section_index` / `first_end` / `goal_flush` | numbered cross-pitches |
| `edge_nudge_m` | per-edge correction in metres by compass side |

Corrections belong here, per venue. Twice I tried to generalise a fix into the
detector (a two-sided turf test for HANSP's kerb; separately-normalised chroma)
and both regressed every other ground while not fixing the target.

## Traps

**Turf saturation is LOW, not high.** Artificial turf reads S≈30 and smooth
(local sd≈5); trees read S≈60 and textured (sd≈15). The first version filtered
`S > 40` and found zero pitches at every venue. Hue also spans 58–105 across
these grounds, so the colour model is seeded per venue from a patch at the GPS
point and widened by its own MAD.

**Segment coarse, fit fine.** Turf segmentation runs at a fixed `WORK_RES`
of 10 cm even when the tile is 5 cm; sharper imagery raises local texture
variance and the adaptive sd threshold floods the mask. Line fitting uses the
full 5 cm.

**Whole pitches are white; only sections use chroma.** Feeding chroma into a
whole-pitch fit lets turf colour noise compete with real touchlines. The
cross-pitch boundaries at STER/P2 are painted faint blue and are invisible to a
whiteness key. `line_response(mode=...)` selects.

**Search bands anchor to the initial rectangle, never the running estimate.**
Re-centring each iteration let an edge walk `in_m` per pass; MOTO4 drifted 10 m
over four iterations.

**The imagery is finer than 10 cm.** Request 0.05 m/px — the detail is real,
not interpolation. And the server sometimes returns a partially rendered tile
with a large black region instead of failing; that gets cached and silently
breaks a venue, so `fetch_crop` validates and refetches.

**Leaf-off captures.** Hanspaulka measures ~9 m short on summer imagery because
a tree shadow swallows the east end. `--auto-layer` scores captures by line
contrast, but check the result: it picked leaf-off for P2, where it breaks the
parent-field segmentation.

**`--codes` merges, it does not replace.** A partial run used to rewrite
`out/measurements.json` with only the venues it touched, silently dropping the
rest. It now loads the existing file first.

**Nudge signs are inverted between opposite edges.** Apply, re-run
`diagnose.py`, confirm the offset moved toward zero. Do not reason it out.

**Compass labels, not "left".** The rectangles sit at 16–120°, so what looks
left in a north-up view is often the rectangle's south edge. `diagnose.py`
draws N/S/E/W on the image; use those when someone reports "too wide on the
left".

## Footwear

`parse_footwear()` in scrape_psmf.py reads the venue's `Obuv:` line. Both
phrasings mention lisovky, so presence alone decides nothing — the rule is
whether lisovky sits nearer "povoleny" or "zakazany" in the sentence. Same test
for AG, which Mecholupy bans alongside lisovky while the others allow it.

This season: lisovky OK at Aritma, Motorlet, Prazacka and both Sterboholy
pitches; banned at Cechie Smichov, Hanspaulka and Bechovice; Mecholupy is turf
or indoor only.

## PSMF quirks

A venue code is not always a pitch. `STER2`, `STER3` and `P2` are numbered
cross-pitches marked across one full-size field, per the venue notes ("č. 1 je
nejblíže hale", "č. 1 nejblíže kabinám"). They are found by fitting one
(offset, spacing) pair across the whole parent so neighbouring thirds share
edges, then a goal-line pair ~45 m apart. The marked pitches do not fill the
parent and are not centred in it — at Štěrboholy the spare ground is all at the
south end, which is what `goal_flush` encodes.

At Štěrboholy the north goal line coincides with a white marking while the
other three edges are blue; that edge is therefore the one that can be located
precisely.

Verified per-venue state as of autumn 2026 is in `data/overrides.json`, each
entry with a `note` saying why it is set that way.

## Output

`out/measurements.json` keeps everything — turf extent, exact sub-metre fits,
capture used, per-edge strengths, lat/lon and bearing. The table and page are
deliberately stripped to venue, size and area; pull detail from the JSON rather
than re-adding columns.
