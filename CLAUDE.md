# CLAUDE.md — working notes

Measures the painted pitch at each PSMF fixture venue from Prague orthophoto
imagery. Read this before changing the detector; most of it was learned the
hard way and several "obvious" fixes here are wrong.

## Layout

```
scrape_psmf.py      our fixtures + venue directory -> data/fixtures.json, data/venues.json
scrape_season.py    every team's fixtures          -> data/season.json
data/extra_venues.json  venues not on the fixture list (our training pitch)
measure_pitches.py  segment turf, fit the lines    -> out/measurements.json, out/*.png
diagnose.py         how far is each edge off?      -> out/diag_*.png
make_table.py       our season table               -> out/table.md, out/table.json
build_page.py       self-contained HTML report     -> docs/index.html
data/overrides.json the per-venue human input      (the important file)
```

The page is for the whole league, not just us: every venue in the directory,
every team's fixtures, and the team picked in the browser. It renders
client-side from one JSON blob because the file is mostly data-URI imagery —
rendering the cards in Python would repeat each venue's image once per team
that plays there. `scrape_season.py` is ~720 requests, one per team, because a
division page carries only a window of the schedule; run it rarely and leave
the pause in.

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
| `section_gap_m` | widest run-off to allow *between* cross-pitches (0 = they touch) |
| `section_edges_m` | the section boundaries as measured, when no fit can find them |
| `pitch_m` | the whole pitch rectangle as measured, when no fit can find *it* |
| `measure` | measure this code on a default run though we have no fixture there |
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

**Three grounds, three paints.** Sterboholy's cross-pitch lines are blue,
Prazacka's are white, and Podvinny mlyn's are ORANGE — barely a luminance step,
and lost in `chroma` because that mixes both colour axes against the turf's own
noise. Orange over green moves b* and little else, which is what
`line_response(mode="orange")` scores. `diagnose.py` now asks all three and
keeps whichever has a peak nearest the edge; taking the first that finds *any*
peak let turf noise in one channel outrank the real line in another, and had it
reporting Podvinny's edges 2-4 m off when they were on the paint.

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

**A ground can carry two nested rectangles.** At Hostivar the pitch is the
inner one and the fit had taken the outer line on one axis and the inner on the
other, so it was too big on all four sides at once. When a venue reads as "too
big in every dimension", look for the second rectangle before touching the
detector.

**The strongest nearby peak is often not a marking.** At several grounds the
kerb or the surround outshines the touchline, which is why HANSP carries a
`fit_out_m` that starts the search inside the carpet. `diagnose.py` prints the
*closest* peak first for this reason; a stronger one 1-3 m out is usually the
surround, not evidence the fit is wrong. Confirm against the image before
chasing it.

**A section edge with no line under it keeps its modelled position.** The
division fit interpolates each edge onto its own peak, since the thirds differ
by tens of centimetres. Where the blue lines are invisible — Pražačka — the
nearest local maximum is turf noise, so `_snap` only moves an edge onto a peak
that is clearly above background. Do not drop that guard: without it Pražačka's
west edge walks 0.4 m and its hand-set nudge no longer means what it says.

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
(offset, width, gap) triple across the whole parent so the sections stay
consistent with each other, then a goal-line pair ~45 m apart. The marked pitches do not fill the
parent and are not centred in it — at Štěrboholy the spare ground is all at the
south end, which is what `goal_flush` encodes.

At Štěrboholy the north goal line coincides with a white marking while the
other three edges are blue; that edge is therefore the one that can be located
precisely.

**Two grounds are beyond any search, and say so.** Mikulova marks four
pitches in two columns and two rows on one full-size field: two-dimensional,
so `sections` cannot describe it. Stodulky's carpet runs 30 m east past the
pitch and the pitch's own halfway line cuts the turf blob in half, so the
detector sees a fragment rather than a field to divide. Both carry `pitch_m`,
the rectangle written down in parent-frame metres — the coordinates the line
probes and `diagnose.py` print. `fit_painted` still settles the result onto the
paint, so it is a starting point, not the answer. Four venues in forty-two need
this or `section_edges_m`; if a fifth does, that is still cheaper than a
detector that can be talked into finding the wrong thing.

**Prazacka cannot be fitted at all.** Its six cross-pitch side lines are in
the imagery — 24 m apart in pairs, 5.7 m between pitches — but the parent's own
goal, penalty and halfway lines are about twice as bright, so a search wide
enough to see the faint ones prefers the bright ones (it scores the parent's
markings 5.4 against the real pitches' 4.0), and chroma sees neither: at this
ground the cross-pitch paint reads in luminance, not colour. `section_edges_m`
therefore carries the three measured pairs. That is better than the nudge it
replaced, which cancelled a wrong fit with a constant and left P2 depending on
a division search that had landed on noise. Do not try to make the search find
these; it is the one venue where the honest answer is to write the numbers down.

**Cross-pitches need not touch.** Štěrboholy's three are 23.9 m wide with 3.8 m
of spare turf between them, so each has its own pair of blue side lines — six
lines, not four. Fitted as contiguous thirds, STER2 and STER3 each took their
west edge from the *neighbour's* east line and came out 27.5 m wide, ~3.8 m too
wide on that side, with the goals visibly off-centre. `section_gap_m` lets the
(offset, width, gap) fit find the real pairs; leave it out and the sections
share edges as Pražačka's do. A block of gapped sections no longer starts near
the parent's edge (Štěrboholy's first side line is 9.5 m in), so with a gap the
block is free to sit anywhere inside the parent instead of within `tol_m`.

**The paint is not square to the turf.** At Štěrboholy the markings sit 0.7°
off the turf carpet's rectangle: half a metre of drift along a 48 m line. That
is enough to smear a faint blue line flat in a carpet-frame profile, which is
why `diagnose.py` profiles at the *fitted* angle and `_apply_goals` emits the
rectangle at it too. Before, the JSON reported the refined angle beside a
rectangle that was not at it.

Every venue in the PSMF directory is measured, not just the ones we play:
41 grounds plus our training pitch, 162 of their 165 edges landing within
0.25 m of a painted line. The three that do not are Hanspaulka's north edge
(the teal kerb, long-standing and correct as measured) and Astra's two east
edges, where the surround outshines the court line by 3x — the documented trap,
not a bad fit. Venues we play no fixture at carry `measure: true`.

`STER1`, `P1` and `P3` are the cross-pitches we have no fixture on. They carry
`measure: true` so a default run still measures them — the numbers are then
already there if the draw moves us — and the page lists them apart from the
season table.

Both grounds number from a landmark, which is what `first_end` records. At
Sterboholy the hall is in the imagery, at the west end, so `first_end: "W"`
follows from the picture. At Prazacka the kabiny are not something the
orthophoto can pick out; they are at the **east** end of the infield, known
from the ground rather than read off the image, so `first_end: "E"` and P1 is
the eastern third. Getting that backwards swaps P1 and P3 and nothing else —
all three measure within 0.1 m of each other — but it is worth having right.

Verified per-venue state as of autumn 2026 is in `data/overrides.json`, each
entry with a `note` saying why it is set that way.

## Output

`out/measurements.json` keeps everything — turf extent, exact sub-metre fits,
capture used, per-edge strengths, lat/lon and bearing. The table and page are
deliberately stripped to venue, size and area; pull detail from the JSON rather
than re-adding columns.
