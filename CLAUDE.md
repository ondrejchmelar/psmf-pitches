# CLAUDE.md — working notes

Measures the painted pitch at each PSMF fixture venue from Prague orthophoto
imagery. Read this before changing the detector; most of it was learned the
hard way and several "obvious" fixes here are wrong.

## Layout

```
scrape_psmf.py      our fixtures + venue directory -> data/fixtures.json, data/venues.json
scrape_season.py    every team's fixtures          -> data/season.json
scrape_history.py   every team's past seasons      -> data/archive/, data/hist/
data/extra_venues.json  venues not on the fixture list (our training pitch)
measure_pitches.py  segment turf, fit the lines    -> out/measurements.json, out/*.png
diagnose.py         how far is each edge off?      -> out/diag_*.png
make_table.py       our season table               -> out/table.md, out/table.json
build_page.py       the published site             -> docs/ (html, img, data)
data/overrides.json the per-venue human input      (the important file)
```

The page is served in four pieces: index.html is the shell plus the venue
records (60 kB), docs/img holds the photos, docs/data/teams.json the fixtures,
fetched after the pitches are on screen, and docs/data/h-<hash>/ a small file per
team of past meetings, fetched only when one is asked for. It was one self-contained
file until that meant 4.6 MB before the first pitch appeared. Each names
itself after a hash of its own contents — `MOTO1.cae3f104.jpg`,
`teams.b37b70e8.json` — so a URL changes when and only when its content does; a
dated `?v=` expired everything on a date roll and nothing on a same-day
re-measure, and some caches drop query strings anyway. The previous teams file
is kept alongside the current one — as is the previous history directory —
because for a few minutes after a build a reader can still hold an index.html
that asks for it.
Opening index.html over file:// leaves the
picker empty — serve it instead.

The page is for the whole league, not just us, and it is in Czech: every venue
in the directory, every team's fixtures, and the team picked in the browser.
The choice goes into the URL (`?team=`) so a link shares the view, and each
pick is a history entry so Back returns to the team you were looking at.
Clearing replaces rather than pushes: it undoes a choice instead of making one,
and as an entry of its own it made Back land on the empty page you had just
left. Typing to filter does not touch the URL at all, so no entry is one the
reader did not ask for. Our
training pitch is measured but kept off the page — it is not a PSMF ground. It renders
client-side from one JSON blob because the file is mostly data-URI imagery —
rendering the cards in Python would repeat each venue's image once per team
that plays there. `scrape_season.py` is ~940 requests, one per team, because a
division page carries only a window of the schedule; run it rarely and leave
the pause in.

It walks four competitions: the Hanspaulská plus the veteran, super-veteran and
ultra-veteran leagues. They cost only their fixtures — every ground they play on
was already measured for the main league, all 39 codes of it. Futsal is left
out, being played in halls no orthophoto can see into. Division names repeat
across competitions, so a label carries the competition ("Vet 3-B"); the main
league keeps a bare division, which is what people call it and what
already-shared `?team=` links contain. `--colours-only` refreshes just the jersey colours, which is one
request per division rather than per team.

Every fixture row can open the day's programme at that ground, in a dialog — what is played
before and after, on the neighbouring pitches too. The index is built in the
browser rather than shipped: every match is already in the blob twice, once from
each side, so it costs a pass over the fixtures instead of another 400 kB.
Grouping is by venue *name*, which puts Pražačka 1-3 and Mikulova 1-4 together
and keeps Běchovice 2 apart from SC Běchovice. Teams in the list are links, as are opponents in the
fixture table itself, so a friend's fixtures are one click away. The dialog is
not a row inside the table on purpose: the table carries a 720px minimum and
scrolls sideways on a phone, and a nested row inherited that.

Each team's fixtures export as an `.ics`, built in the browser from the same
blob. Times are written floating — no zone — because every match is in Prague
and 19:15 should stay 19:15 whatever the reader's calendar is set to, including
across the October clock change. Events carry a stable ASCII UID, so
re-importing a refreshed file updates the entries instead of duplicating them.
Lines fold at 75 *octets*, not characters: a Czech diacritic is two of them, and
counting characters left a third of the lines over the limit.

Results ride along in the fixture rows: a played match ends its row with the
score, home:away. A score is written twice — first a provisional one a player
phones in, then the referee's official result, which is not always the same
number. psmf.cz greys the provisional (`is-gray`) and marks the official
`is-result`, so `parse_fixtures` reads the score cell's classes and sets
`official`. Anything it does not recognise counts as *not* official, which
matters: if that detection is ever wrong, the refresh keeps asking instead of
trusting a number too early, and the behaviour degrades to what it did before.

`scrape_season.py --results` re-reads, within a ten-day window, every team with
a match not yet marked official. That is ~900 teams while nothing is marked and
~300 once results start being confirmed — it gets cheaper on its own.
`--missing-only` is the cheap pass for teams with no score at all. The window is
what stops it growing: a result that never gets recorded would otherwise keep
its two teams in the queue for the rest of the season.

The provisional/official split was verified only in the direction that could be:
every score in the finished spring season reads as official. No provisional
result existed anywhere on the site to test against.

`.github/workflows/refresh.yml` runs that twice a day and rebuilds the page.
It installs `requests` and `pyproj` and nothing else — `build_page.py
--no-images` reuses the committed photos and imports opencv only when it has to
write one, which is why measuring stays a local, by-hand job. The image cache
stamp is a hash of `out/measurements.json`, not its mtime: a fresh CI checkout
would otherwise stamp every photo with today and expire every reader's cache
nightly for nothing.

`scrape_tables.py` reads the final standing of every division of every season
into `data/tables`: 144 seasons, 36,426 finishing places, 3.2 MB, for 3,228
requests. A team page never carries a table — where a side finished and on how
many points is only on the division page, behind `?cmd=tables&…&type=final`,
which answers with the whole group at once. Twelve teams a request is what makes
it affordable; the same coverage from team pages would be twelve times the walk.
`league` is the number in the division slug and `group_id` its letter's
position, but `competition` and `season` are internal ids that are not
derivable — veteran spring 2026 is season=10, super-veteran the same spring
season=21 — so each season is probed once and the ids read off the link the
division page would have called itself.

That gives every team a placing per season, and the career paragraph a real
top and bottom: **the league first, the place within it second**, because
fourth in the 6th is a better season than third in the 7th and ranking on the
place alone said otherwise. Titles get their own clause when there are any. The
card under the fixtures draws the whole thing as a line — league down the y
axis, one dot a season, coloured by how it ended — from `cr` in the per-team
file. The line comes from `data/archive`, which is complete, so it is unbroken
even where a dot is hollow because no table was played (jaro 2020) or none has
been yet.

The axis labels sit on the chart rather than in a strip beside it — "6. liga"
above its gridline, the years along the floor — stroked in `var(--ground)` with
`paint-order:stroke`, so a label the line runs through stays readable and the
line is not cut. Their size is in user units, which the viewBox scales with
everything else: at 430px the chart renders at about 0.6, so under 640px the
labels are set to 18px to come out the same size they do on a desktop.

Every dot carries its whole row — group, place, played, W-D-L, score, points —
in a readout under the chart, on hover and on tap. A 4.5px dot is nothing to aim
at with a thumb, so each one has a second invisible circle of r=13 over it that
carries the pointer and the text; `<title>` stays on it as well, for anything
that only does tooltips. The readout starts on the last season actually played,
not the newest, which for most of a season is a row of noughts.

There are two ways a dot can be hollow and they read differently. The current
season has no table yet — "zatím bez tabulky". **Jaro 2020 has none at all**, in
any competition: 720 rows across 60 divisions, every one of them nought, and
`type=actual` is empty too, so this is psmf.cz's own gap, not the scrape's. The
matches were played — our team has all eleven with scores — but no standing was
ever published, and nobody moved: 686 of 709 teams were in the same league that
autumn, against 284 who moved a year earlier. So that one says "bez tabulky",
and the note under the chart says why.

Do not call that paragraph `.pick`. That class is the team picker's box, and the
readout quietly inherited its border and background until it was `.crpick`.

`scrape_history.py --detail` keeps the rest of a match block as well: who
played, who kept goal, who wore the armband, who scored and in which minute,
who was booked, and who the referee marked as the best on the pitch. It re-reads
whatever it is given, since the files already on disk do not have it, and only
our own team has been scraped that way — 32 seasons, 465 kB. `squad()` in
build_page.py turns it into the block under the fixtures: the career record, the
biggest win and heaviest defeat, and every player who has ever been named in a
line-up with their appearances, goals and man-of-the-match marks. Keeping goal is a count, not a
label: three men have kept 254 of the 301 between them, but outfield players
stand in often enough that "brankář" beside a name would be wrong. The captain
is a tag rather than a column, because it is one or two people for years at a
time and a column of blanks says less than a word beside a name. Twenty-one
people over sixteen years, and it exists nowhere else — psmf.cz has no career
page for anybody, and a season's line-ups are only on that season's page.

It rides in the same per-team file as the head-to-heads and is drawn when that
arrives, so the fixtures never wait for it; `sq: 1` on the team record is what
says to ask. Going league-wide would mean the full crawl (15,600 pages) and
`data/hist` at perhaps 90 MB — and it would publish appearance and scoring
tallies for every amateur in the league, which is a different thing from a
single match report even though every number in it is already public.

psmf.cz keeps no description of a team — no founding date, no history, nothing
on its page but the season you are looking at, and the one club link it offers
points at `mujtym.psmf.cz`, which no longer resolves. The one biography the
league does keep is `data/archive`: which division every slug was in, every
season back to 2007. `bio()` in build_page.py turns that into the paragraph
under each team's heading — how long they have been here, the highest and lowest
league they have reached and when they were last there, and whether this season
is a step up or down. It costs no requests; the archive was built for finding
teams in the first place.

The wording stays descriptive on purpose — "letos o ligu níž než loni", never
"sestoupil", and never a count of places. How many go up is not a rule anybody
published; it is whatever balances the books that season, and it changes with
the level (Hanspaulská, per group, seasons since 2017):

| liga | nahoru (medián, rozsah) | dolů |
| --- | --- | --- |
| 2. | 1 (1–1) | 2 (1–3) |
| 4. | 2 (2–3) | 3 (0–3) |
| 6. | 3 (1–4) | 3 (0–3) |
| 7. | 4 (2–5) | 3 (0–3) |
| 8. | 4 (2–6) | — |

Going down is close to a rule: of 2,573 relegations, 2,556 are from the bottom
three places. Going up is not — 1,286 from 1st, 1,085 from 2nd, 787 from 3rd,
382 from 4th and 66 from 5th. So a fourth place going up is ordinary in the 7th
league and impossible in the 2nd, which is why nothing on the page claims a
promotion or names a number of places.

The top of the pyramid is fixed — 1 group, then 2, 4, 6, 9, 12, 12 — so the
flows up there are tightly constrained. The bottom is the shock absorber: the
8th league carries 13 or 14 groups depending on the season, takes almost every
new team (20 of 34 entrants in one transition) and loses the most to teams
folding. Podzim 2025 to jaro 2026 it sent 54 up and took 32 down, plus 20 new
against 10 gone — net twelve teams short, which is exactly the group it lost,
14 down to 13. That is why the 8th promotes four a group and the 2nd promotes
one: not depth, but who has room.

A handful of moves are neither: 95 of 33,883 jump two levels or more, and the
extremes — 2-A to 8-L in one step — are a side re-entering at the bottom, or a
slug two different clubs have held. That last one is worth remembering, because
the career model assumes one slug is one team.

Two more things it is careful about. A team already present in the oldest archived
season has been here longer than can be said, so it reads "od jara 2007 nebo
dřív" rather than naming a start it does not know. And the season cited beside a
league is the *most recent* one at that level, so it says "naposledy" — without
that, "6. liga (podzim 2025)" reads as the only time they were ever there.

`scrape_history.py` is the back catalogue: every team's past matches, with the
paragraph the referee wrote about each. psmf.cz keeps the whole archive back to
2007 but links a team to none of its earlier selves — the `<` arrow on a team
page reaches one season back at best, and often not that; ours skips straight
over podzim 2025, which we certainly played. Nothing on the site answers "where
was this team in 2015?" either.

So the first pass builds that answer: for every season of all four competitions,
walk its division pages and write down which division each slug was in, into
`data/archive/<season>.json`. That is 3,849 requests once and 2.5 MB, after
which finding any team in any season is free.

The second pass reads team pages, one file per team under `data/hist`. It does
not read every season a team played: that is 15,600 pages for the main league
alone, and all the page ever shows is what happened the last time these two met.
A season in which none of this year's opponents was in the same division cannot
hold such a match, and the index above says which those are before a single
request — that cuts the walk to about a third. Each file records the seasons it
has actually been given and whether that is all of them (`seasons`, `complete`),
so an interrupted run resumes where it stopped, a re-run costs nothing, and
`--full` tops one team up to its whole past later. Ours was read that way: 9
seasons under the filter, then 331 matches over all 32 with `--full`.

A team is searched only within its own competition: the veteran leagues keep
their own archives, and a side that moved between them reads as two teams, which
is what the league's own slugs say. Four seasons in a row without it ends its
walk — teams do sit one out, and jaro 2021 did not happen at all.

The payload is the referee's write-up, under `Detaily utkání` on a finished
season's team page; the half-time score is there too. Both are written
home:away, which flips meaning every other line in a one-team history, so the
page turns them round to ours:theirs and says `doma`/`venku` beside them.

Two pieces of that reach the browser, and the split is the point. The balance
itself — `0–1–3` against Tohle není hokej? — is three numbers hung on the
fixture in teams.json, so the chips are in the table the moment it is drawn. The
matches behind them are a file per team under `docs/data/h-<hash>/`, fetched
only when a chip is opened and kept for the session: the league's write-ups are
29 MB and nobody reads more than the team they picked. Only the pairs that
actually meet this season are shipped, which turns that into 2.4 MB over 819
files — 2.9 kB each. 4,305 of the 10,214 fixtures have a balance to show.

The season being played is excluded when the balance is counted. Its own
fixtures are in the history file too, and without that they would come back as a
previous meeting on their own row.

This is not in the daily job. A head-to-head only changes when a season ends,
which is why it is in the new-season runbook below and nowhere else. The pause
defaults to a second: this walks thousands of pages of somebody else's small
site, and there is nowhere to be in a hurry to. The whole league was 3,849
index requests and 6,304 team pages, about three hours.

The cards show every photo in one square box. Left alone they run from 1.6:1 to
0.6:1 — a pitch is as tall as it is aimed — and a row had Aritma three times
Meteor's height. They are cropped, and the crop is centred on the measured
rectangle rather than the middle of the picture: at Hrabákova the pitch we play
is the top third of a parent field and centring frames the two we do not.
`focal()` in build_page.py works out where that rectangle sits by repeating the
framing `pitch_crop` used — both rectangles plus 12 m of padding, clipped to the
tile — and hands the browser an `object-position`. **That 12 m is written down in
two places**: change `pad_m` in measure_pitches.py and every card silently crops
off-centre.

The whole pitch always survives the crop. `focal()` returns the offset that
*centres the rectangle in the visible window* — `(c - side/2) / (dim - side)`,
not the rectangle's position in the picture, which is a different number — and
clamped, that contains the rectangle whenever it fits at all. Where it does not
fit, `focal()` returns None and the card falls back to `object-fit: contain`:
the photo is scaled down inside the square instead of being cut. One ground
needs that, Aritma, whose pitch is 54.9 m long in a frame 48 m wide; cropping it
square would take the goals off, and the goals are the point.

`.card figure` carries `min-height:0`, and must. It is a flex item, a flex
item's automatic minimum size is its content, and the content is the whole
photo — so `aspect-ratio` was quietly ignored for every picture taller than it
was wide, which was half of them, and only the landscape ones came out square.

The fixture table is seven columns, and was nine. Plocha went because the card
below repeats it; the programme chip moved into the ground cell, where it reads
as part of the ground rather than a column of its own; and the kick-off sits
under the date instead of beside it. The results column stands all season with a
dashed empty slot per unplayed match: it was left out until the first score
arrived, and a column that appears in October reads as a change rather than as
a promise. The opponent and ground cells are flex lines rather than inline text:
as inline they sat on the baseline at four different heights and broke between
any two of them. `width:max-content` makes the table ask for the width that
keeps each cell on one line; under 640px that is dropped so the badges fold —
but never the names, because "Orange / Predators B" over two ragged lines was
what looked broken, not a shirt and a balance on a line of their own
underneath. Both cells fold there whether they need to or not — the
name, then the badges under it — because most rows fold anyway and a column
that folds only sometimes looks worse than one that always does. The
table is ~695px on a phone and scrolls, which it always did.

Jersey colours come from each division's `dresy` page, in the league's own
words — "bílá, černá", "modro-žlutá", "tmavě modrá". `colours()` in
build_page.py turns them into swatches by matching stems, since the halves of a
compound are inflected. The comma matters: the league writes the shirt
first and the shorts after it, so "bílá, černá" is a white shirt over black
shorts, while a hyphen describes one two-tone shirt, "bílo-červená". Only the
shirt decides a clash — nobody is told apart by their shorts.

A clash is RGB distance under 120 of a possible 441: crude, but it makes the
calls people make on the pitch (navy against black, red against maroon). A
two-tone shirt gets a second look — white-red against white-blue-yellow share
their base but the second colour separates them, so that is not a clash, while
plain white against white-blue still is, having no second colour to save it.
Only away fixtures are flagged, because that is the side that changes.

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

### The history, once the new draw is out

```bash
./.venv/bin/python scrape_season.py                     # the new season first
./.venv/bin/python scrape_history.py --all --seasons 2  # the season just ended
./.venv/bin/python scrape_history.py --all              # then the new pairings
./.venv/bin/python build_page.py --no-images
```

In that order, and both `--all` runs are needed.

`--seasons N` forces a re-read of the N newest seasons *on the site*, whether or
not the files already have them, because a finished season's scores and
write-ups keep arriving for weeks after its last match. Two, not one: once the
new draw is up it is the newest season, so the one that just ended is second.
Nothing else in the tool re-reads a season it already holds.

The plain `--all` then reads whatever the *new* draw has made relevant. The
filter is "was one of this team's opponents that season in its division", so a
new fixture list asks about seasons no previous run had any reason to fetch.
Everything already on disk is skipped, so this is far cheaper than the first
time.

Three things make it cheap and none of them should be undone lightly:

* `data/archive/` is committed. Rebuilding it is ~3,900 requests for something
  that cannot change — a finished season's divisions are fixed. Only the new
  season's own index has to be built, which happens on its own.
* `data/hist/` is committed: 822 files, 66,000 matches, 29 MB. Deleting it means
  another three hours of somebody else's bandwidth.
* Teams are matched by psmf.cz's own slug. A club that renames itself gets a new
  slug and reads as a new team with no history — the site does the same, so
  there is nothing better available. Watch for it if a rivalry you expect comes
  up empty.

New teams in the league simply have no file; they get no chips, which is
correct. `build_page.py` warns about nothing here — a missing file is the normal
case for a side in its first season.

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

Astra Zahradní město (`ASTR1`, `ASTR2`) is futsal only, by the venue's own
note, and no Hanspaulská fixture is played there. It is dropped for the same
reason as Děkanka hala and Slavia hala: this is a football league.

Every venue in the PSMF directory that the league plays on is measured, not
just the ones we play:
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
