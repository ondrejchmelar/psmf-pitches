# PSMF pitch dimensions from orthophoto

Measures the pitch we play on at every venue in our PSMF fixture list, straight
from Prague orthophoto imagery.

The report is published at <https://ondrejchmelar.github.io/psmf-pitches/>:
every ground in the PSMF directory, and a team picker that shows any team's
fixtures with the size of each pitch they play on. GitHub Pages serves what
`build_page.py` writes into `docs/`: a 60 kB `index.html`, the venue photos as
files, and the fixtures as JSON fetched once the page is on screen.

## Usage

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python scrape_psmf.py            # our fixtures + venue directory -> data/
./.venv/bin/python scrape_season.py          # every team, all four competitions -> data/season.json
./.venv/bin/python scrape_season.py --colours-only   # just the jersey colours
./.venv/bin/python scrape_season.py --results        # scores for matches already played
./.venv/bin/python scrape_history.py         # our own past seasons -> data/history.json
./.venv/bin/python measure_pitches.py --auto-layer   # measure + annotate -> out/
./.venv/bin/python make_table.py             # our season table -> out/table.md
./.venv/bin/python build_page.py             # the published site -> docs/
python3 -m http.server -d docs               # preview it (file:// will not do)
```

`scrape_psmf.py` takes an optional team URL; it defaults to our 7-G team page.

`scrape_history.py` is the slow one and is meant to be run once. psmf.cz keeps
every season back to 2007 but links a team to none of its earlier selves, so
finding it means walking a season's division pages until its slug turns up —
which it does start from the division the team was in last time, so the usual
cost is a handful of pages rather than sixty-eight. What it is after is the
referee's write-up: every played match has a paragraph describing it, and it
exists nowhere else. Afterwards `--seasons 1` re-reads only the season being
played and merges it in, which is one request.

## How the measurement works

Imagery is the IPR Praha orthophoto archive at 0.05 m/px, requested in EPSG:5514
(S-JTSK) so pixel spacing is metres and no reprojection error creeps in. The
national CUZK orthophoto is available via `--source cuzk` as a fallback.

Tiles are validated on arrival: the server occasionally returns a partially
rendered image with a large black region rather than failing, and one of those
got cached and quietly broke a venue for several runs.

Turf is separated from vegetation by colour **and** texture. The thresholds are
not hand-picked: artificial turf turned out to be a smooth, weakly-saturated
green (S~30, local sd~5) while trees and rough grass are strongly saturated and
textured (S~60, sd~15) — the opposite of the obvious guess. Turf hue also ranges
58-105 across these ten grounds, so absolute thresholds do not transfer between
venues; the colour model is seeded from a patch on the pitch and widened by its
own MAD.

Two things then have to be got right:

* **White lines cut a turf blob into fragments** (a halfway line splits a pitch
  in two). Candidate rectangles are proposed at several morphological closing
  scales and scored, so no single kernel has to both bridge a halfway line and
  preserve the gap between neighbouring pitches.
* **Neighbouring pitches merge.** `data/overrides.json` carries a region of
  interest per venue, in metres relative to the PSMF GPS point, isolating the
  pitch we actually play on. This is the one piece of human input, and it is
  visible and checkable in the annotated output.

Turf segmentation runs at a fixed 10 cm working resolution regardless of the
tile: local texture variance rises with sharper imagery, so the adaptive
threshold that works at 10 cm floods the mask at 5 cm. Segment coarse, fit fine.

Each candidate is scored on rectangularity plus *border support* — the fraction
of its outline with non-turf just outside it. A real pitch edge changes surface;
a fragment boundary made by a painted line has turf on both sides.

## Measuring the painted pitch

The headline number is the **painted rectangle** -- the touchlines and goal
lines you actually play between -- not the turf carpet, which includes the
run-off margin and reads 1-3 m bigger.

Finding it takes three things:

* **Resolution.** The archive serves finer than 10 cm: at 0.05 m/px a 12 cm line
  is 2-3 px instead of barely 1, and the extra detail is real (checked against
  the power spectrum, not assumed). This is the single biggest accuracy win.
* **A colour-agnostic line filter.** The cross-pitch markings at Sterboholy and
  Prazacka are painted in faint blue, not white, so a whiteness key misses them
  entirely. `line_response()` instead looks for *thin structures whose colour
  differs from the turf around them*, via a top-hat on the Lab distance from a
  median-filtered background. White and coloured lines both light up.
* **A tight search band.** Each edge is found by coordinate descent: with the
  cross-axis extent held fixed, an edge is the profile peak within a band, with
  sub-pixel parabolic interpolation. The band is what keeps it honest -- a
  touchline sits within about a metre of the turf edge (often just *outside* it,
  since the turf mask erodes slightly), while the penalty-area line is metres in
  and the fence metres out. Searching +/-5 m let edges jump to the wrong line and
  the whole rectangle cascaded off; +1.5/-2.5 m does not.

The pitch angle is refined at the same time, over +/-2 degrees in 0.1 degree steps,
by maximising how sharply the line profiles peak.

### Picking the imagery

`--auto-layer` probes the archive per venue and keeps the capture whose markings
stand out most above background. The leaf-off ("mimovegetacni") flights usually
win: no tree shadow, and crisper paint. It matters most at Hanspaulka, which
sits under trees.

### Overrides

`data/overrides.json` is the escape hatch, and it is deliberately visible rather
than buried in tuned thresholds:

* `roi_m` -- the region isolating the pitch we play, so neighbouring pitches
  cannot merge into one turf blob.
* `layer` -- which capture to use. Leaf-off flights win wherever trees are
  involved; Hanspaulka measures ~9 m short on the summer imagery.
* `fit_out_m` / `fit_in_m` -- the touchline search band, for grounds where a
  bright kerb sits exactly where the search would otherwise land.
* `goal_flush` -- which end the marked cross-pitches start from. Peak strength
  alone picks the wrong pair at Sterboholy.
* `pitch_m` -- the pitch rectangle itself, measured, for the two grounds where
  no search can find it: Mikulova's four pitches are laid out two-by-two, and
  Stodulky's turf blob comes back as a fragment because its halfway line cuts
  the carpet in two.
* `section_edges_m` -- the cross-pitch boundaries as measured off the imagery,
  for the ground where no fit can find them. At Prazacka the parent's own
  markings are twice as bright as the cross-pitch ones, so any search that can
  see the faint lines locks onto the bright ones.
* `section_gap_m` -- how much run-off may sit *between* numbered cross-pitches.
  Sterboholy's three are 23.9 m wide with 3.8 m between them, so each has its
  own pair of side lines; fitted as contiguous thirds they came out 3.8 m too
  wide, each borrowing its neighbour's line.
* `edge_nudge_m` -- per-edge corrections in metres by compass side, positive
  inward. A matched +/- pair translates a rectangle without resizing it, which
  is what Sterboholy needed: the size fitted well but sat too far south.

Nudges are recorded per venue instead of being absorbed into detector
thresholds, so a correction at one ground cannot silently break another.

### How far to trust a number

`edge_strength` in `out/measurements.json` reports, per side, how far that
edge's peak rose above the median line response. All four edges above ~4 means
every side was read off a clear line. A weak edge means the marking is faint
there and the fit is an estimate rather than a reading -- the table carries this
as a confidence column. Expect roughly +/-0.5 m where confidence is high.

Every measurement has an annotated PNG in `out/`. The rectangle drawn on it is
the one that produced the number: if it does not sit on the paint, the number is
wrong.

## Pitch numbers are not always separate pitches

PSMF publishes one GPS point per *areal*, and some codes are a numbered
cross-pitch of a larger field rather than a standalone pitch:

* `STER1`/`STER2`/`STER3` — cross-pitches on one big UMT field ("c. 1 je
  nejblize hale, c. 3 nejdale"). All three the same size, 3.8 m of spare turf
  apart.
* `P1`/`P2`/`P3` — three pitches marked across the stadium infield, 24 m wide
  with 5.7 m between them and a shared pair of goal lines 45.3 m apart. They are
  numbered from the kabiny, at the east end.

Each of those is measured off its own pair of side lines, not divided out of
the parent, and is flagged `section_N_of_M` in the output. `SANC1`/`SANC2` are two
genuinely separate adjacent pitches; PSMF's numbering is relative to the changing
rooms, which the imagery cannot resolve, but the two measure within ~3 m of each
other so it makes little practical difference.

## Output

* `out/table.md`, `out/table.json` — the season table
* `out/measurements.json` — full geometry, incl. lat/lon and bearing per pitch
* `out/<CODE>.png` — areal overview with the measured rectangle
* `out/<CODE>_pitch1.png` — per-pitch photo crop with the rectangle and side lengths
