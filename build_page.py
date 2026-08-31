#!/usr/bin/env python3
"""Build the published report -> docs/ (index.html, img/, data/).

The page used to be our eleven fixtures, rendered server-side. It now carries
every venue in the PSMF directory and every team's fixture list, and picks the
team in the browser. Three things worth knowing before editing:

* Everything renders client-side. Rendering the cards here instead would repeat
  each venue's markup wherever it appears -- once in the league grid, again for
  every team that plays there.
* The page is split three ways. index.html is the shell plus the 39 venue
  records, about 60 kB; the photos are files under docs/img, fetched lazily by
  the browser and cached between visits; the fixtures are docs/data/teams.*.json,
  about a megabyte, fetched once the pitches are on screen. It was one
  self-contained file until that meant 4.6 MB before anything could be shown.
  Both name themselves after a hash of their contents, so a URL changes exactly
  when its content does.
* A consequence: opening docs/index.html over file:// leaves the picker empty,
  because fetch has no origin. Serve it -- `python3 -m http.server -d docs`.
"""
import argparse, hashlib, json, re, shutil, sys
from datetime import date
from pathlib import Path

from pyproj import Transformer

# Deliberately not importing measure_pitches: it pulls in opencv, and a
# results-only rebuild (--no-images) has no pictures to make. The one thing
# needed from it is four lines of arithmetic, repeated here.
TO_WGS = Transformer.from_crs("EPSG:5514", "EPSG:4326", always_xy=True)


def px_to_lonlat(pt, geo):
    return TO_WGS.transform(geo["x0"] + pt[0] * geo["res"],
                            geo["y1"] - pt[1] * geo["res"])


ap = argparse.ArgumentParser()
ap.add_argument("--no-images", action="store_true",
                help="reuse the photos already in docs/img (a results-only rebuild)")
ARGS = ap.parse_args()

ROOT = Path(__file__).parent
ms = json.loads((ROOT / "out/measurements.json").read_text("utf-8"))
ov = json.loads((ROOT / "data/overrides.json").read_text("utf-8"))
venues = json.loads((ROOT / "data/venues.json").read_text("utf-8"))
season_path = ROOT / "data/season.json"
season = json.loads(season_path.read_text("utf-8")) if season_path.exists() else {"teams": []}

IMG_W, IMG_Q = 900, 78        # served as files now, so they can afford to be better
OUT = ROOT / "docs"


def digest(data):
    return hashlib.sha1(data).hexdigest()[:8]


def write_jpeg(src, code, width=IMG_W, q=IMG_Q):
    """Write one venue photo into docs/img and return its URL.

    The name carries a hash of the file's own contents -- MOTO1.4f2a9c31.jpg --
    so a re-measured pitch gets a new URL and an unchanged one keeps its old
    name and stays in the reader's cache. A `?v=` stamp did the same job less
    well: dated, it expired every photo whenever the date rolled over, and some
    caches ignore the query string entirely.
    """
    if ARGS.no_images:
        found = sorted((OUT / "img").glob(f"{code}.*.jpg"))
        return f"img/{found[0].name}" if found else ""

    import cv2                       # only a full rebuild needs opencv
    img = cv2.imread(str(src))
    if img is None:
        return ""
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    if not ok:
        return ""
    data = buf.tobytes()
    name = f"{code}.{digest(data)}.jpg"
    (OUT / "img").mkdir(parents=True, exist_ok=True)
    for stale in list((OUT / "img").glob(f"{code}.*.jpg")) + [OUT / "img" / f"{code}.jpg"]:
        if stale.name != name and stale.exists():
            stale.unlink()          # includes the old un-hashed name
    (OUT / "img" / name).write_bytes(data)
    return f"img/{name}"


# ---------------------------------------------------------------- jerseys
# The league writes jersey colours in Czech words -- "bila, cerna",
# "modro-zluta", "tmave modra" -- so they have to be turned into something a
# swatch can show. Stems, because the compound halves are inflected:
# "modro-bila" is modra + bila.
COLOUR_STEMS = [
    ("bíl", "#F2F2F0"), ("čern", "#1D1D1D"), ("modr", "#2062C4"), ("žlut", "#F2C200"),
    ("červen", "#D32C2C"), ("zelen", "#2E8B3D"), ("oranžov", "#EF7D1A"),
    ("růžov", "#E75AA0"), ("fialov", "#7B4FB5"), ("šed", "#9096A0"),
    ("zlat", "#C9A227"), ("rud", "#B01B1B"), ("vínov", "#7B1E3A"), ("bordó", "#7B1E3A"),
    ("hněd", "#7A5230"), ("tyrkys", "#1FB6B0"), ("limetk", "#A8D420"),
    ("mentol", "#8FE3C4"), ("losos", "#F08A70"), ("pistáci", "#A7C957"),
    ("maskáč", "#6B7A4B"),
]


def _shade(hexstr, factor):
    r, g, b = (int(hexstr[i:i + 2], 16) for i in (1, 3, 5))
    if factor < 1:                                    # tmavě
        r, g, b = (int(v * factor) for v in (r, g, b))
    else:                                             # světle
        m = factor - 1
        r, g, b = (int(v + (255 - v) * m) for v in (r, g, b))
    return f"#{r:02X}{g:02X}{b:02X}"


def colours(text, shirt_only=False):
    """Czech colour wording -> the hex swatches to draw, in the order written.

    The league writes the shirt first and the shorts after a comma -- "bílá,
    černá" is a white shirt over black shorts -- while a hyphen describes one
    two-tone shirt: "bílo-červená". Only the shirt decides whether two sides can
    be told apart, so `shirt_only` stops at the first comma.
    """
    out = []
    parts = re.split(r"[,/]| a ", (text or "").lower())
    for part in (parts[:1] if shirt_only else parts):
        part = part.strip()
        if not part:
            continue
        factor = 1.0
        for word, f in (("tmavě ", 0.62), ("tmavo", 0.62), ("světle ", 1.45)):
            if part.startswith(word):
                part, factor = part[len(word):], f
        for piece in part.split("-"):
            piece = piece.strip()
            hexs = next((h for stem, h in COLOUR_STEMS if piece.startswith(stem)), None)
            if hexs:
                h = _shade(hexs, factor) if factor != 1.0 else hexs
                if h not in out:      # "bílo-zelená, zelená" is two colours, not three
                    out.append(h)
    return out[:3]


def boots(code):
    """Short Czech label, its CSS class, and the venue's own wording."""
    fw = (venues.get(code, {}) or {}).get("footwear") or {}
    lis, ag = fw.get("lisovky", "unknown"), fw.get("ag", "unknown")
    if lis == "allowed":
        label, cls = "lisovky OK", "lisovky"
    elif lis == "forbidden":
        label, cls = ("jen turfy", "turf") if ag == "forbidden" else ("bez lisovek", "no")
    else:
        label, cls = "", ""
    return label, cls, fw.get("text", "")


# --------------------------------------------------------------------- venues
def focal(cand, geo, cx, cy):
    """How to fit one photo into the square box the cards use.

    Returns the `object-position` percentages for a `cover` crop, or None when
    that crop cannot hold the whole measured rectangle -- Aritma's pitch is
    54.9 m long in a frame only 48 m wide, so a square of it has to cut the
    goals off, and the card scales the photo down instead.

    The percentages are not the rectangle's position in the picture: with
    `cover`, p% aligns the image's p% point with the box's, so what is wanted is
    the offset that centres the rectangle in the visible window, `(c - L/2) /
    (dim - L)`. Clamped, that is guaranteed to contain the rectangle whenever it
    fits at all.

    The framing repeats `pitch_crop`'s -- both rectangles, 12 m of padding,
    clipped to the tile. Those 12 m live in two files: change `pad_m` there and
    every card here crops off-centre, quietly.
    """
    pad = 12.0 / geo["res"]
    size = geo.get("size", 4000)
    pts = cand["rect_px"] + cand["play_rect_px"]
    x0 = max(min(p[0] for p in pts) - pad, 0)
    y0 = max(min(p[1] for p in pts) - pad, 0)
    x1 = min(max(p[0] for p in pts) + pad, size)
    y1 = min(max(p[1] for p in pts) + pad, size)
    w, h = x1 - x0, y1 - y0
    side = min(w, h)                      # what a square box shows of it
    play = cand["play_rect_px"]
    if (max(p[0] for p in play) - min(p[0] for p in play) > side
            or max(p[1] for p in play) - min(p[1] for p in play) > side):
        return None
    def pos(c, dim):
        return 50 if dim <= side else round(
            100 * min(max((c - side / 2) / (dim - side), 0), 1))
    return [pos(cx - x0, w), pos(cy - y0, h)]


V = {}
for code, m in ms.items():
    if code.startswith("_"):
        continue
    c = (m.get("candidates") or [None])[0]
    if not c:
        continue
    v = m.get("venue", {})
    label, cls, text = boots(code)
    l, w = round(c["play_l_m"]), round(c["play_w_m"])
    # the centre of the pitch we drew, not of the parent field: on a ground with
    # four of them, that is the difference between finding it and hunting
    pts = c["play_rect_px"]
    cx, cy = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    lon, lat = px_to_lonlat((cx, cy), m["geo"])
    V[code] = {
        "code": code, "venue": v.get("name", code), "l": l, "w": w, "area": l * w,
        "exact": f'{c["play_l_m"]} x {c["play_w_m"]}',
        "kind": c.get("kind", ""), "capture": m.get("geo", {}).get("capture", "?"),
        "boots": label, "bootsClass": cls, "bootsText": text,
        "lat": round(lat, 6), "lon": round(lon, 6),
        "addr": (venues.get(code, {}) or {}).get("address", ""),
        "note": (ov.get(code) or {}).get("note", ""),
        "img": write_jpeg(ROOT / f"out/{code}_pitch1.png", code),
        "fp": focal(c, m["geo"], cx, cy),
    }
    if v.get("training"):
        V.pop(code)          # measured for our own comparison, not a PSMF ground

play = V
smallest = min(play.values(), key=lambda x: x["area"])
largest = max(play.values(), key=lambda x: x["area"])

def family_of(comp):
    """'2026-superveteranska-liga-podzim' -> 'superveteranska-liga'."""
    return comp.split("-", 1)[1].rsplit("-", 1)[0] if comp else ""


# -------------------------------------------------------------------- careers
# psmf.cz keeps no description of a team: no founding date, no history, nothing
# on the page but the season you are looking at. The one biography the league
# does keep is data/archive -- which division every slug was in, every season --
# so the page writes the paragraph out of that. It costs no requests: the
# archive was built for finding teams in the first place.
ARCHIVE = ROOT / "data/archive"
seen_seasons: dict[str, list[str]] = {}
where: dict[str, dict] = {}
for src in sorted(ARCHIVE.glob("*.json")):
    where[src.stem] = json.loads(src.read_text("utf-8"))
    seen_seasons.setdefault(family_of(src.stem), []).append(src.stem)
for f in seen_seasons:
    seen_seasons[f].sort(key=lambda x: (int(x[:4]), x.endswith("podzim")), reverse=True)

CAREER_GAP = 4          # seasons out before we call it a different team, as in the scraper

# Where everyone finished, division by division, from scrape_tables.py. The team
# pages never carry a table; this is the only record of a placing.
TABLES = ROOT / "data/tables"
standings = {p.stem: json.loads(p.read_text("utf-8")) for p in TABLES.glob("*.json")}


def season_code(s):
    """'2010-hanspaulska-liga-podzim' -> 'p2010'. Three characters saved 45 kB."""
    return ("p" if s.endswith("podzim") else "j") + s[:4]


def career(slug, comp):
    """Every season this team appears in, newest first, stopping at a real gap."""
    order = seen_seasons.get(family_of(comp), [])
    present = [x for x in order if slug in where[x]]
    if not present:
        return []
    out, missed = [], 0
    for x in order[order.index(present[0]):]:
        if slug in where[x]:
            out.append((x, where[x][slug]))
            missed = 0
        else:
            missed += 1
            if missed >= CAREER_GAP:
                break
    return out


def hi_now(c):
    """The level of the season being played."""
    m = re.match(r"(\d+)", c[0][1])
    return int(m.group(1)) if m else 0


def placings(slug, comp):
    """[season code, league, place, out of] for every season with a table.

    A season not yet played has a table too -- everyone on nought -- so a place
    only counts once somebody has kicked a ball.
    """
    out = []
    for season, div in career(slug, comp):
        for row in standings.get(season, {}).get(div, []):
            if row[1] == slug and int(row[2]) > 0:
                out.append([season_code(season), int(re.match(r"(\d+)", div).group(1)),
                            row[0], len(standings[season][div])])
    return out


def line(slug, comp):
    """Every season, oldest first: where they played and how it finished.

    [code, division, place, out of, played, W, D, L, "gf:ga", points], with the
    place 0 where no table has been read or none was played. The chart's line is
    drawn from the division, which is always known; the dots and the readout
    come from the rest, which is not.
    """
    out = []
    for season, div in reversed(career(slug, comp)):
        rec = [season_code(season), div, 0, 0]
        for row in standings.get(season, {}).get(div, []):
            if row[1] == slug and int(row[2]) > 0:
                rec = [season_code(season), div, row[0],
                       len(standings[season][div])] + row[2:]
        out.append(rec)
    return out


def bio(slug, comp):
    """What can be said about a team without asking psmf.cz anything."""
    c = career(slug, comp)
    if not c:
        return None
    order = seen_seasons[family_of(comp)]
    lvl = {}
    for x, div in c:
        m = re.match(r"(\d+)", div)
        if m:
            lvl.setdefault(int(m.group(1)), x)      # newest season at that level
    if not lvl:
        return None
    hi, lo = min(lvl), max(lvl)
    out = {"n": len(c), "od": season_code(c[-1][0])}
    if len(c) > 1:
        was = re.match(r"(\d+)", c[1][1])
        if was and int(was.group(1)) != hi_now(c):
            out["pv"] = int(was.group(1))
    # How high they got, judged by the league first and the place within it
    # second: fourth in the 6th is a better season than third in the 7th, and
    # ranking on the place alone said otherwise. Where no table has been read
    # the sentence falls back to naming the league and nothing else.
    got = placings(slug, comp)
    if got:
        best = min(got, key=lambda g: (g[1], g[2]))
        worst = max(got, key=lambda g: (g[1], g[2]))
        out["top"] = best[1:] + best[:1]
        out["bot"] = worst[1:] + worst[:1]
        won = [g for g in got if g[2] == 1]
        if won:
            out["won"] = [len(won), won[0][0]]
    else:
        out["hi"] = [hi, season_code(lvl[hi])]
        if lo != hi:
            out["lo"] = [lo, season_code(lvl[lo])]
    # The archive starts in 2007. A team already in it then has been here longer
    # than we can say, and "since 2007" would be a guess. Both of these are
    # written only when true: false is twelve bytes nine hundred times over.
    if c[-1][0] == order[-1]:
        out["cap"] = 1
    if order.index(c[-1][0]) - order.index(c[0][0]) + 1 != len(c):
        out["gap"] = 1
    return out


# ---------------------------------------------------------------------- teams
# Division names repeat across competitions -- there is a 3-B in three of them --
# so the label carries the competition. The main league keeps a bare division,
# which is what people call it and what already-shared links contain.
COMP_TAG = (("superveteranska", "Super"), ("ultraveteranska", "Ultra"),
            ("veteranska", "Vet"))


def div_label(comp, division):
    for key, tag in COMP_TAG:
        if key in (comp or ""):
            return f"{tag} {division.upper()}"
    return division.upper()


teams = []
for t in season.get("teams", []):
    fx = [{"r": f["round"], "d": f["date"], "t": f["time"], "c": f["venue_code"],
           "o": f["opponent"], "h": f["home"], "s": f.get("score", ""),
           "of": bool(f.get("official"))}
          for f in t["fixtures"]]
    if fx:
        teams.append({"name": t["name"], "sl": t.get("slug", ""),
                      "div": div_label(t.get("comp"), t["division"]), "fx": fx,
                      "bio": bio(t.get("slug", ""), t.get("comp", "")),
                      "kit": t.get("colours", ""),
                      "sw": colours(t.get("colours", "")),               # badge
                      "sh": colours(t.get("colours", ""), True)})        # shirt
teams.sort(key=lambda t: (t["name"].lower(), t["div"]))

# No team is selected on load. The page is for the league, so it opens on the
# whole directory rather than on whoever built it.
# Venues stay in the page: 39 short records, and the grid is the first thing a
# reader sees. The teams are a megabyte and nobody needs them until they pick
# one, so they are fetched after the first paint.
(OUT / "data").mkdir(parents=True, exist_ok=True)


def publish(stem, payload):
    """Write docs/data/<stem>.<hash>.json and return its filename.

    Keeps the previous file as well as the current one. GitHub Pages serves
    index.html with a short cache, so for a few minutes after a build someone
    can still be holding the old page -- which asks for the old name. One spare
    file turns a 404 into a hit; older ones are no use to anybody.
    """
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    name = f"{stem}.{digest(data)}.json"
    (OUT / "data" / name).write_bytes(data)
    keep = sorted((OUT / "data").glob(f"{stem}.*.json"),
                  key=lambda f: f.stat().st_mtime, reverse=True)[:2]
    for stale in (OUT / "data").glob(f"{stem}.*.json"):
        if stale not in keep:
            stale.unlink()
    return name


# -------------------------------------------------------------------- history
# What happened last time these two met, from data/hist -- one file per team,
# every season it has played, with the referee's write-up for each match.
#
# Two pieces go to the browser. The balance itself (3 numbers) rides in the
# fixture, so the chips are there the moment the table is: they are what a
# reader looks at. The matches behind them are a file per team, fetched only
# when a chip is opened, because the whole league's write-ups are 30 MB and
# nobody reads more than one team's.
HIST_SRC = ROOT / "data/hist"
HIST_DIR = ""


def squad(matches, comp):
    """Sixteen years of a team in one block, when the line-ups were kept.

    `scrape_history.py --detail` keeps who played, who scored and who the
    referee called the best on the day. That is the only place any of it exists
    once a season's page rolls over -- psmf.cz has no career page for anybody.
    Only teams scraped that way get this; for the rest it is simply absent.
    """
    played = [m for m in matches if m.get("score") and m.get("line") is not None]
    if len(played) < 5:
        return None
    w = d = l = gf = ga = 0
    app, goals, best, cap, gk = {}, {}, {}, {}, {}
    first, last = {}, {}
    for m in sorted(played, key=lambda m: m["date"] or ""):
        f, a = m["gf"], m["ga"]
        gf += f
        ga += a
        w += f > a
        d += f == a
        l += f < a
        for pl in m["line"]:
            n = pl["n"]
            app[n] = app.get(n, 0) + 1
            best[n] = best.get(n, 0) + bool(pl.get("best"))
            cap[n] = cap.get(n, 0) + bool(pl.get("cap"))
            # The name before the dash is the keeper. Outfield players stand in
            # often enough that this is a count, not a label on a person.
            gk[n] = gk.get(n, 0) + bool(pl.get("gk"))
            first.setdefault(n, m["label"])
            last[n] = m["label"]
        for g in m.get("goals", []):
            goals[g["n"]] = goals.get(g["n"], 0) + len(g["m"])

    def extreme(pick):
        m = pick(played, key=lambda m: (m["gf"] - m["ga"], m["gf"]))
        return {"s": f'{m["gf"]}:{m["ga"]}', "o": m["opponent"], "l": m["label"]}

    return {
        "n": len(played), "w": w, "d": d, "l": l, "gf": gf, "ga": ga,
        "big": extreme(max), "bad": extreme(min),
        # name, matches, goals, man of the match, in goal, as captain,
        # first season, last season
        "p": [[n, app[n], goals.get(n, 0), best[n], gk[n], cap[n], first[n], last[n]]
              for n in sorted(app, key=lambda n: (-app[n], -goals.get(n, 0)))],
    }


if HIST_SRC.exists():
    # Opponents are named in a fixture, not linked, so the name is what keys
    # everything below. Within one competition they are unique -- checked here
    # rather than assumed, because a collision would silently attach one team's
    # history to another's row.
    by_name = {}
    for t in season.get("teams", []):
        key = (family_of(t.get("comp")), t["name"])
        assert key not in by_name, f"two teams named {key}"
        by_name[key] = t["slug"]

    # `teams` is sorted by name and drops anyone with no fixtures, so it cannot
    # be walked alongside season["teams"]; the slug is what joins them.
    rec_by_slug = {r["sl"]: r for r in teams if r["sl"]}
    files, met = {}, 0
    for t in season.get("teams", []):
        rec = rec_by_slug.get(t["slug"])
        if rec is None:
            continue
        fam = family_of(t.get("comp"))
        src = HIST_SRC / fam / f"{t['slug']}.json"
        if not src.exists():
            continue
        hist = json.loads(src.read_text("utf-8"))
        sq = squad(hist["matches"], t.get("comp")) if hist.get("detail") else None
        past = {}
        for m in hist["matches"]:
            # The season being played is not history: its own fixtures would
            # otherwise come back as a previous meeting on their own row.
            if m.get("score") and m["season"] != t.get("comp"):
                past.setdefault(m["opp_slug"], []).append(m)
        out = {}
        for fx, f in zip(t["fixtures"], rec["fx"]):
            ms = past.get(by_name.get((fam, fx["opponent"]), ""), [])
            if not ms:
                continue
            w = sum(1 for m in ms if m["res"] == "W")
            d = sum(1 for m in ms if m["res"] == "D")
            f["hh"] = [w, d, len(ms) - w - d]
            out[fx["opponent"]] = [
                {"d": m["date"], "l": m["label"], "v": m["venue"], "h": m["home"],
                 "s": m["score"], "hf": m["half"], "r": m["res"],
                 "ref": m["referee"], "w": m["report"]} for m in ms]
        cr = line(t["slug"], t.get("comp", ""))
        if out or sq or len(cr) > 1:
            body = {"t": t["name"], "o": out}
            if len(cr) > 1:
                body["cr"] = cr
            if sq:
                # It rides in the same file as the head-to-heads, fetched on the
                # same request, because a team that has one usually has both --
                # and one file per team is already the shape that scales.
                body["sq"] = sq
                rec["sq"] = 1
            files[t["slug"]] = json.dumps(body, ensure_ascii=False,
                                          separators=(",", ":")).encode()
            met += len(out)

    if files:
        # The directory is named after everything in it, for the same reason the
        # other files are: the page asks for a URL that changes when and only
        # when its contents do. The previous one stays for the reader still
        # holding the previous index.html.
        HIST_DIR = "h-" + digest(b"".join(files[k] for k in sorted(files)))
        room = OUT / "data" / HIST_DIR
        room.mkdir(parents=True, exist_ok=True)
        for slug, payload in files.items():
            (room / f"{slug}.json").write_bytes(payload)
        keep = sorted((OUT / "data").glob("h-*"),
                      key=lambda p: p.stat().st_mtime, reverse=True)[:2]
        for stale in (OUT / "data").glob("h-*"):
            if stale not in keep and stale.is_dir():
                shutil.rmtree(stale)
        print(f"   {len(files)} teams carry a head-to-head, {met} pairings, "
              f"{sum(len(v) for v in files.values())/1e6:.1f} MB", file=sys.stderr)


# Written last: the history pass above hangs a balance on the fixtures that
# have one, and that has to be in the file the browser fetches.
TEAMS_FILE = publish("teams", {"teams": teams})

blob = json.dumps({"venues": V}, ensure_ascii=False,
                  separators=(",", ":")).replace("<", "\\u003c")

# Applied before the page paints, so a stored choice does not arrive as a flash
# of the other theme. Kept apart from the main script, which runs at the end.
EARLY_JS = """
try {
  var t = localStorage.getItem('psmf-theme');
  if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
} catch (e) { }
"""

CSS = """
:root {
  --ground:#F6F7F3; --surface:#FFFFFF; --sunk:#EDEFE8;
  --ink:#161A15; --muted:#5B655A; --faint:#8B948A;
  --rule:#DDE1D7; --accent:#8A6A00; --mark:#E0B400;
  --home:#2F6B4F; --away:#7A4A2C;
  --shadow:0 1px 2px rgba(20,26,18,.05),0 8px 24px -16px rgba(20,26,18,.28);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground:#0F120E; --surface:#171B15; --sunk:#1E231C;
    --ink:#E9EDE5; --muted:#9AA396; --faint:#6E776C;
    --rule:#2A3027; --accent:#E9C34A; --mark:#F2CE55;
    --home:#7BC49B; --away:#DDA277;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 28px -18px rgba(0,0,0,.8);
  }
}
:root[data-theme="dark"] {
  --ground:#0F120E; --surface:#171B15; --sunk:#1E231C;
  --ink:#E9EDE5; --muted:#9AA396; --faint:#6E776C;
  --rule:#2A3027; --accent:#E9C34A; --mark:#F2CE55;
  --home:#7BC49B; --away:#DDA277;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 28px -18px rgba(0,0,0,.8);
}
* { box-sizing:border-box; }
body {
  margin:0; background:var(--ground); color:var(--ink);
  font:400 16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap { max-width:1440px; margin:0 auto; padding:clamp(28px,5vw,64px) clamp(18px,4vw,36px) 96px; }
.eyebrow {
  font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  letter-spacing:.18em; text-transform:uppercase; color:var(--accent); margin:0 0 14px;
}
h1 { font-size:clamp(30px,5vw,46px); line-height:1.06; letter-spacing:-.022em;
  font-weight:680; margin:0 0 14px; text-wrap:balance; }
.lede { max-width:64ch; color:var(--muted); font-size:17px; margin:0 0 8px; }
.rule { height:1px; background:var(--rule); margin:34px 0 28px; border:0; }
.stats { display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); margin-bottom:8px; }
.stat { background:var(--surface); border:1px solid var(--rule); border-radius:3px; padding:16px 18px; }
/* A balance is one number, not three: "112-28-161" broken across two lines
   reads as two different figures. It shrinks to fit instead. */
.stat b { display:block; font:600 26px/1.1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; letter-spacing:-.02em; white-space:nowrap; }
.stat b.long { font-size:clamp(17px, 4.4vw, 22px); }
.stat span { display:block; margin-top:6px; font-size:12px; letter-spacing:.08em;
  text-transform:uppercase; color:var(--faint); }
h2 { font-size:13px; letter-spacing:.14em; text-transform:uppercase; color:var(--faint);
  font-weight:600; margin:0 0 16px; }
.pick { background:var(--surface); border:1px solid var(--rule); border-radius:3px;
  padding:18px 20px; display:flex; gap:14px; align-items:center; flex-wrap:wrap;
  box-shadow:var(--shadow); }
.pick label { font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  letter-spacing:.14em; text-transform:uppercase; color:var(--faint); }
.pick input { flex:1 1 260px; min-width:0; font:inherit; font-size:16px; padding:9px 12px;
  color:var(--ink); background:var(--ground); border:1px solid var(--rule); border-radius:3px; }
.pick input:focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
.pick input:disabled { opacity:.6; cursor:progress; }
.pick .who { font-size:13px; color:var(--faint); }
.combo { position:relative; flex:1 1 260px; min-width:0; }
.combo input { width:100%; padding-right:38px; }
.clear { position:absolute; right:6px; top:50%; transform:translateY(-50%);
  width:26px; height:26px; display:grid; place-items:center; padding:0;
  border:0; border-radius:3px; background:none; color:var(--faint);
  font:400 20px/1 system-ui,sans-serif; cursor:pointer; }
.clear:hover { background:var(--sunk); color:var(--ink); }
.clear[hidden] { display:none; }
.top { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }
.theme { font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.1em;
  text-transform:uppercase; color:var(--muted); background:var(--surface);
  border:1px solid var(--rule); border-radius:3px; padding:8px 11px; cursor:pointer;
  white-space:nowrap; flex:none; }
.theme:hover { color:var(--ink); border-color:var(--muted); }
.h2row { display:flex; justify-content:space-between; align-items:center; gap:16px;
  flex-wrap:wrap; margin-bottom:16px; }
.h2row h2 { margin:0; }
.ics { font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.08em;
  text-transform:uppercase; color:var(--muted); background:var(--surface);
  border:1px solid var(--rule); border-radius:3px; padding:8px 11px; cursor:pointer;
  white-space:nowrap; flex:none; }
.ics:hover { color:var(--ink); border-color:var(--muted); }
.sugg { position:absolute; z-index:20; left:0; right:0; top:calc(100% + 4px);
  max-height:320px; overflow-y:auto; background:var(--surface);
  border:1px solid var(--rule); border-radius:3px; box-shadow:var(--shadow); padding:4px; }
.sugg[hidden] { display:none; }
.sugg button { display:block; width:100%; text-align:left; font:inherit; font-size:15px;
  padding:7px 10px; border:0; border-radius:2px; background:none; color:var(--ink); cursor:pointer; }
.sugg button:hover, .sugg button[aria-selected="true"] { background:var(--sunk); }
.sugg button span { color:var(--faint); font-size:13px; margin-left:6px; }
.sugg .none { padding:8px 10px; color:var(--faint); font-size:14px; }
.scroll { overflow-x:auto; border:1px solid var(--rule); border-radius:3px; background:var(--surface); }
table { border-collapse:collapse; width:100%; min-width:580px; font-size:14.5px; }
th { text-align:left; font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  letter-spacing:.12em; text-transform:uppercase; color:var(--faint);
  padding:13px 14px; border-bottom:1px solid var(--rule); white-space:nowrap; }
td { padding:11px 12px; border-bottom:1px solid var(--rule); vertical-align:middle; }
tbody tr:last-child td { border-bottom:0; }
tbody tr:hover { background:var(--sunk); }
.num, .dim { font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; text-align:right; white-space:nowrap; }
.dim { text-align:left; font-weight:600; }
.date { white-space:nowrap; }
/* The kick-off under the date rather than beside it: two short lines instead of
   one long one, and the column stops being the widest thing in the table. */
.date .t { display:block; color:var(--faint); font-size:13px; margin-top:2px; }
/* max-content so the table asks for the width that keeps each cell on one
   line, max-width so it still folds rather than overflow when the screen is a
   phone and the column cannot have it. */
.cell { display:flex; align-items:center; flex-wrap:wrap; gap:4px 8px;
  width:max-content; max-width:100%; }
.cell .kit, .cell .clash, .cell .h2h, .cell .more, .cell .pin.lead { margin:0; }
/* The pin belongs to the name, not beside it: as its own flex item it was the
   thing that fitted when the name did not, and sat alone on a line above it. */
.gname { display:inline-flex; align-items:center; gap:2px; white-space:nowrap; }
.oname { min-width:0; }
/* On a phone the table is scrolled sideways whatever we do, so width is worth
   more than a tidy single line: the cells fold again and the padding comes
   down, which is the difference between reaching the ground column and not. */
@media (max-width:640px) {
  th { padding:11px 9px; }
  td { padding:10px 9px; }
  .cell { width:auto; }
  /* The cell folds, but never inside a name: "Orange / Predators B" over two
     ragged lines was the thing that looked broken, not the shirt and the
     balance sitting on a line of their own underneath it. */
  .oname, .gname { white-space:nowrap; }
  /* Both cells break the same way every row: the name, then the badges under
     it. Most rows fold there anyway -- only the short names fit beside their
     shirt -- and a column that folds only sometimes reads worse than one that
     always does. */
  .oname, .ground .gname { flex:1 0 100%; }
}
code { font:600 11.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace; color:var(--muted);
  background:var(--sunk); padding:2px 5px; border-radius:2px; }
/* Stretch, not start: with the photos all one shape the only thing left making
   a row ragged is how much text a card carries, and a card is happier with a
   little space under its last line than the row is with a step in it. */
.grid { display:grid; gap:20px; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); }
.card { background:var(--surface); border:1px solid var(--rule); border-radius:3px;
  overflow:hidden; box-shadow:var(--shadow); display:flex; flex-direction:column; }
/* One box for every photo. Left to themselves they run from 1.6:1 to 0.6:1 --
   a pitch is as tall as it is aimed -- and a row of cards had Aritma at three
   times Meteor's height. Cropped rather than letterboxed, around the measured
   rectangle rather than the middle: at Hrabákova the pitch is the top third of
   a parent field, and centring would frame the two we do not play on. */
.card figure { margin:0; background:var(--sunk); border-bottom:1px solid var(--rule);
  aspect-ratio:1/1; min-height:0; }
.card img { display:block; width:100%; height:100%; object-fit:cover; }
/* Aritma's pitch is longer than its photo is wide, so a square of it cannot
   contain the goals. That one is scaled down to fit rather than cropped: the
   whole pitch is the thing the card is for. */
.card img.whole { object-fit:contain; }
.card .body { padding:16px 18px 18px; display:flex; flex-direction:column; gap:9px; }
.ch { display:flex; justify-content:space-between; align-items:baseline; gap:10px; flex-wrap:wrap; }
.ch h3 { margin:0; font-size:15.5px; font-weight:640; letter-spacing:-.01em;
  display:flex; align-items:center; gap:7px; }
.ch h3 .pin { margin:0; }
.ch .d { margin:0; font:600 15px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; color:var(--accent); white-space:nowrap; }
.bar { position:relative; height:20px; background:var(--sunk); border-radius:2px;
  display:flex; align-items:center; }
.bar i { position:absolute; inset:0 auto 0 0; background:var(--mark); opacity:.42; border-radius:2px; }
.bar span { position:relative; margin-left:8px; font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; color:var(--ink); }
.fx { margin:4px 0 0; font-size:12.5px; color:var(--muted); }
.nt { margin:2px 0 0; font-size:12px; line-height:1.45; color:var(--faint); }
.bio { margin:-6px 0 16px; font-size:13.5px; line-height:1.55; color:var(--muted);
  max-width:78ch; }
.career { width:100%; height:auto; display:block; margin:8px 0 4px; }
.career .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
/* Painted into the chart, not beside it: stroked in the page's own background
   so a label crossing the line is still readable and the line is not cut.
   The size is in user units, which the viewBox scales down with everything
   else -- so on a phone, where the chart renders at about 0.6, it has to be
   set larger to come out the same. */
.career .lab { font-size:11px; paint-order:stroke; stroke:var(--ground);
  stroke-width:3px; stroke-linejoin:round; }
@media (max-width:640px) { .career .lab { font-size:18px; stroke-width:4px; } }
.legend { display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:var(--faint);
  margin:0 0 2px; }
.legend i { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:5px; }
/* Not .pick -- that is the team picker's box, and this inherited its border. */
.crpick { margin:2px 0 10px; font:600 13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; color:var(--ink); min-height:20px; }
.career .hit { cursor:pointer; }
/* Only inside the career block. Three dense things stacked -- chart, cards,
   squad -- and at the spacing the rest of the page uses they read as one wall.
   Scoped to #past so the team's own summary cards keep their own rhythm. */
#past .stats { margin:32px 0 10px; }
#past .bio { margin:26px 0 12px; }
.boots { font:600 10.5px/17px ui-monospace,SFMono-Regular,Menlo,monospace;
  letter-spacing:.03em; padding:0 6px; border-radius:2px; border:1px solid currentColor;
  white-space:nowrap; }
.boots.lisovky { color:var(--home); }
.boots.no { color:var(--mark); }
.boots.turf { color:var(--away); }
.conf { font:600 10px/16px ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.06em;
  text-transform:uppercase; color:var(--faint); }
.conf.low { color:var(--away); }
.meta { margin:2px 0 0; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.kit { display:inline-flex; vertical-align:-2px; margin-left:6px; border-radius:2px;
  overflow:hidden; border:1px solid var(--rule); height:13px; }
.kit i { display:block; width:9px; height:100%; }
h2 .kit { height:15px; }
h2 .kit i { width:11px; }
.more { font:600 11px/17px ui-monospace,SFMono-Regular,Menlo,monospace; color:var(--muted);
  background:var(--sunk); border:1px solid var(--rule); border-radius:2px;
  padding:0 7px; cursor:pointer; }
.more:hover, .more.open { color:var(--ink); border-color:var(--muted); }
dialog#prog { border:0; padding:0; background:none; max-width:min(560px, 94vw); width:100%; }
dialog#prog::backdrop { background:rgba(0,0,0,.5); }
.progbox { background:var(--surface); color:var(--ink); border:1px solid var(--rule);
  border-radius:4px; box-shadow:var(--shadow); padding:18px 20px 20px; }
.progbox header { display:flex; justify-content:space-between; align-items:baseline;
  gap:12px; margin-bottom:14px; }
.progbox h3 { margin:0; font-size:15px; font-weight:640; }
.progbox .x { border:0; background:none; color:var(--faint); font:400 24px/1 system-ui,sans-serif;
  cursor:pointer; padding:0 2px; }
.progbox .x:hover { color:var(--ink); }
.programme { list-style:none; margin:0; padding:0; display:grid; gap:10px; }
.programme li { display:flex; flex-wrap:wrap; gap:4px 10px; align-items:baseline;
  font-size:14.5px; padding-bottom:9px; border-bottom:1px solid var(--rule); }
.programme li:last-child { border-bottom:0; padding-bottom:0; }
.programme li.self { color:var(--accent); font-weight:600; }
.programme .who { flex:1 1 220px; min-width:0; }
.programme .meta2 { display:flex; gap:8px; align-items:baseline; margin-left:auto; }
.programme b { font:600 13.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; }
.programme i { font-style:normal; font-size:12px; color:var(--faint); white-space:nowrap; }
.h2h { font:600 11px/17px ui-monospace,SFMono-Regular,Menlo,monospace; color:var(--muted);
  background:var(--sunk); border:1px solid var(--rule); border-radius:2px;
  padding:0 7px; margin-left:8px; cursor:pointer; white-space:nowrap; }
.h2h:hover { color:var(--ink); border-color:var(--muted); }
.hsum { margin:-6px 0 14px; font-size:13px; color:var(--faint); }
.hist { list-style:none; margin:0; padding:0; display:grid; gap:14px;
  max-height:min(62vh, 640px); overflow-y:auto; }
.hist li { padding-bottom:12px; border-bottom:1px solid var(--rule); }
.hist li:last-child { border-bottom:0; padding-bottom:0; }
.hline { display:flex; flex-wrap:wrap; gap:4px 10px; align-items:baseline; font-size:14.5px; }
.hist .who { flex:1 1 140px; min-width:0; }
.hist .hf { font:400 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace; color:var(--faint); }
.hist .meta2 { display:flex; gap:8px; align-items:baseline; margin-left:auto; }
.hist i { font-style:normal; font-size:12px; color:var(--faint); white-space:nowrap; }
.hist .rep { margin:6px 0 0; font-size:13.5px; line-height:1.5; color:var(--muted); }
.hist .ref { margin:3px 0 0; font-size:12px; color:var(--faint); }
.programme a.tlink { color:inherit; text-decoration:none; border-bottom:1px solid var(--rule); }
.programme a.tlink:hover { color:var(--accent); border-color:currentColor; }
td a.tlink { color:inherit; text-decoration:none; border-bottom:1px solid var(--rule); }
td a.tlink:hover { color:var(--accent); border-color:currentColor; }
.res { font:600 12.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; padding:2px 6px; border-radius:2px;
  background:var(--sunk); color:var(--muted); white-space:nowrap; }
.res.win { color:var(--home); }
.res.loss { color:var(--away); }
.res.draw { color:var(--muted); }
.res.prov { opacity:.65; font-style:italic; }
.res.pend { color:var(--faint); background:transparent; border:1px dashed var(--rule); }
.role { font:600 10.5px/17px ui-monospace,SFMono-Regular,Menlo,monospace;
  letter-spacing:.03em; padding:0 6px; border-radius:2px; white-space:nowrap;
  color:var(--faint); border:1px solid var(--rule); }
.clash { font:600 10.5px/17px ui-monospace,SFMono-Regular,Menlo,monospace;
  letter-spacing:.03em; padding:0 6px; border-radius:2px; white-space:nowrap;
  color:var(--away); border:1px solid currentColor; margin-left:8px; }
tr.warn td { background:color-mix(in srgb, var(--away) 9%, transparent); }
.pin { display:inline-flex; vertical-align:-3px; margin-left:5px; color:var(--faint); }
/* leading the venue column, so the pins line up down the table */
.pin.lead { margin:0 7px 0 0; }
.pin:hover { color:var(--accent); }
.empty { color:var(--faint); font-size:14px; }
.loading { display:flex; align-items:center; gap:12px; color:var(--faint); font-size:15px;
  padding:28px 0; }
.loading[hidden] { display:none; }
.sp { width:18px; height:18px; flex:none; border-radius:50%;
  border:2px solid var(--rule); border-top-color:var(--accent);
  animation:spin .8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion:reduce) { .sp { animation-duration:2.4s; } }
footer { margin-top:46px; padding-top:20px; border-top:1px solid var(--rule);
  font-size:12.5px; color:var(--faint); }
a { color:var(--accent); }
a:focus-visible, tr:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
@media (prefers-reduced-motion:reduce) { * { animation:none!important; transition:none!important; } }
"""

JS = r"""
const D = JSON.parse(document.getElementById('psmf-data').textContent);
D.teams = [];
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const mx = Math.max(...Object.values(D.venues).map(v => v.area));

function bootsTag(v) {
  return v.boots ? `<span class="boots ${v.bootsClass}">${esc(v.boots)}</span>` : '';
}

// Where a tap on the coordinates should land. Android and iOS hand them to
// whatever navigation app is installed; a desktop has no such handler, so it
// gets mapy.com, which is the one people here actually use.
const ua = navigator.userAgent || '';
const isAndroid = /Android/i.test(ua);
const isIOS = /iPad|iPhone|iPod/i.test(ua) ||
  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
function mapHref(v) {
  const q = encodeURIComponent(v.venue + ' ' + v.code);
  if (isAndroid) return `geo:${v.lat},${v.lon}?q=${v.lat},${v.lon}(${q})`;
  if (isIOS) return `https://maps.apple.com/?ll=${v.lat},${v.lon}&q=${q}`;
  return `https://mapy.com/zakladni?source=coor&id=${v.lon},${v.lat}` +
         `&x=${v.lon}&y=${v.lat}&z=18`;
}
const PIN = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">' +
  '<path fill="currentColor" d="M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 0 0-7-7z' +
  'm0 9.6A2.6 2.6 0 1 1 12 6.4a2.6 2.6 0 0 1 0 5.2z"/></svg>';

function mapLink(v, cls) {
  const t = `Otevřít ${esc(v.venue)} v mapě`;
  return `<a class="pin${cls ? ' ' + cls : ''}" href="${mapHref(v)}" target="_blank"
    rel="noopener noreferrer" title="${t}" aria-label="${t}">${PIN}</a>`;
}

function card(v, sub) {
  const kind = v.kind.indexOf('section') === 0
    ? `hřiště ${v.kind.split('_')[1]} ze ${v.kind.split('_')[3]}` : 'celé hřiště';
  return `<article class="card">
    <figure><img src="${v.img}" alt="Ortofoto hřiště ${esc(v.venue)} se zakresleným obdélníkem"
      loading="lazy"${v.fp ? ` style="object-position:${v.fp[0]}% ${v.fp[1]}%"` : ' class="whole"'}></figure>
    <div class="body">
      <header class="ch">
        <h3>${esc(v.venue)} <code>${esc(v.code)}</code>${mapLink(v)}</h3>
        <p class="d">${v.l} &times; ${v.w} m</p>
      </header>
      <div class="bar"><i style="width:${(100 * v.area / mx).toFixed(1)}%"></i><span>${v.area} m&sup2;</span></div>
      ${sub || ''}
      ${v.boots ? `<p class="meta">${bootsTag(v)}</p>` : ''}
      <p class="nt">${kind} &middot; ${esc(v.exact)} m${v.bootsText ? ' &middot; ' + esc(v.bootsText) : ''}</p>
    </div></article>`;
}

// PSMF writes the score home:away, and the row already says which we were, so
// it is shown as written; the colour carries the outcome.
function outcome(f) {
  if (!f.s) return null;
  const p = f.s.split(':').map(Number);
  if (p.length !== 2 || p.some(isNaN)) return null;
  const [us, them] = f.h ? [p[0], p[1]] : [p[1], p[0]];
  return us > them ? 'win' : us < them ? 'loss' : 'draw';
}
function resultTag(f) {
  const o = outcome(f);
  // An empty slot rather than an empty cell: the column is there all season and
  // a dash says the score is coming, where nothing at all reads as a mistake.
  if (!o) return '<span class="res pend" title="Zatím se nehrálo">&ndash;</span>';
  // A provisional score is the one a player phoned in; the referee's may differ.
  return f.of
    ? `<span class="res ${o}">${esc(f.s)}</span>`
    : `<span class="res ${o} prov" title="Předběžný výsledek, ještě není oficiální">${esc(f.s)}*</span>`;
}

function kit(sw, kitText) {
  if (!sw || !sw.length) return '';
  return `<span class="kit" title="${esc(kitText)}">` +
    sw.map(c => `<i style="background:${c}"></i>`).join('') + '</span>';
}

// Two sides clash when a glance does not separate the shirts. Shorts are left
// out of it -- they are the part after the comma, and nobody is told apart by
// their shorts.
//
// Distance in plain RGB, under 120 of a possible 441: crude, but it makes the
// calls people make on the pitch, navy against black and red against maroon.
// A two-tone shirt gets a second look: white-red against white-blue-yellow
// share their base, but the second colour separates them at any distance, so
// that is not a clash. A plain shirt has no second colour to save it, so white
// against white-blue still is.
function rgb(h) {
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}
function apart(p, q) {
  const [x, y] = [rgb(p), rgb(q)];
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]) >= 120;
}
function clashes(a, b) {
  if (!a || !b || !a.length || !b.length) return false;
  if (apart(a[0], b[0])) return false;
  if (a.length > 1 && b.length > 1 && apart(a[1], b[1])) return false;
  return true;
}
// Opponents are named, not linked, so match them by name; a name shared across
// divisions is ambiguous, and an ambiguous kit is worse than none.
const kitByName = new Map();

// ---- what else is on at the same ground ------------------------------------
// Built here rather than shipped: every match is already in the blob twice,
// once from each side, so the index costs a pass over the fixtures instead of
// another 400 kB of JSON. Grouping is by venue name, which puts Pražačka 1-3
// and Mikulova 1-4 together and keeps Běchovice 2 apart from SC Běchovice --
// same name, one ground; different name, different areál.
const nameToIdx = new Map();
const minutes = t => {
  const m = /(\d{1,2}):(\d{2})/.exec(t || '');
  return m ? +m[1] * 60 + +m[2] : 0;
};
const ground = c => (D.venues[c] ? D.venues[c].venue : c);

const programme = new Map();          // "ground|date" -> [match]

// Everything derived from the team list, built once it has arrived. The page
// renders its pitches before this runs.
function indexTeams() {
  keys = D.teams.map(t => fold(label(t)));
  D.teams.forEach((t, i) => {
    const lower = t.name.toLowerCase();
    nameToIdx.set(lower, nameToIdx.has(lower) ? null : i);
    kitByName.set(lower, kitByName.has(lower) ? null : t);
  });
  const seen = new Set();
  D.teams.forEach(t => t.fx.forEach(f => {
    const home = f.h ? t.name : f.o, away = f.h ? f.o : t.name;
    const id = `${f.d}|${f.t}|${f.c}|${home}|${away}`;
    if (seen.has(id)) return;
    seen.add(id);
    const k = `${ground(f.c)}|${f.d}`;
    if (!programme.has(k)) programme.set(k, []);
    programme.get(k).push({ tm: f.t, c: f.c, home, away, div: t.div, id, s: f.s, of: f.of });
  }));
  // Kickoff first, then pitch: at Pražačka three matches start at 19:30 and
  // without the second key they land in whatever order the team walk produced,
  // so P3 could sit above P1. Numeric collation keeps MIKU10 after MIKU4.
  programme.forEach(list => list.sort((a, b) =>
    minutes(a.tm) - minutes(b.tm) || a.c.localeCompare(b.c, 'cs', { numeric: true })));
}

function teamLink(name) {
  const i = nameToIdx.get((name || '').toLowerCase());
  return (i === undefined || i === null)
    ? esc(name) : `<a href="#" class="tlink" data-i="${i}">${esc(name)}</a>`;
}

// A dialog rather than a row inside the table: the table carries a 720px
// minimum and scrolls sideways on a phone, and a nested row inherits that, so
// the programme ended up needing a horizontal scroll of its own. The dialog is
// free of the table and can wrap.
function programmeChip(f, t) {
  const list = programme.get(`${ground(f.c)}|${f.d}`) || [];
  if (list.length < 2) return '';
  const mine = `${f.d}|${f.t}|${f.c}|${f.h ? t.name : f.o}|${f.h ? f.o : t.name}`;
  return `<button type="button" class="more" data-date="${esc(f.d)}" data-code="${esc(f.c)}"
    data-mine="${esc(mine)}" title="Co se ještě hraje na tomto hřišti">+${list.length - 1}</button>`;
}

function openProgramme(date, code, mine) {
  const list = programme.get(`${ground(code)}|${date}`) || [];
  const items = list.map(mm => {
    const self = mm.id === mine;
    return `<li${self ? ' class="self"' : ''}>
      <b>${esc(mm.tm)}</b>
      <span class="who">${self ? esc(mm.home) + ' – ' + esc(mm.away)
                               : teamLink(mm.home) + ' – ' + teamLink(mm.away)}</span>
      <span class="meta2">${mm.s ? `<span class="res${mm.of ? '' : ' prov'}"${mm.of ? ''
        : ' title="Předběžný výsledek"'}>${esc(mm.s)}${mm.of ? '' : '*'}</span>` : ''}
        <i>${esc(mm.div)}</i><code>${esc(mm.c)}</code></span></li>`;
  }).join('');
  const dlg = document.getElementById('prog');
  dlg.setAttribute('aria-label', 'Program na hřišti');
  dlg.innerHTML = `<div class="progbox">
      <header><h3>${esc(ground(code))} &middot; ${esc(date)}</h3>
        <button type="button" class="x" value="cancel" aria-label="Zavřít">&times;</button></header>
      <ul class="programme">${items}</ul>
    </div>`;
  if (dlg.showModal) dlg.showModal(); else dlg.setAttribute('open', '');
}

// ---- what happened last time -----------------------------------------------
// The balance itself rides in the fixture, so the chips are drawn with the
// table. The matches behind them are a file per team, fetched the first time
// one is opened: the league's write-ups run to 30 MB and nobody reads more
// than the team they picked.
const histCache = new Map();          // team slug -> promise of its meetings

function histFor(t) {
  if (!histCache.has(t.sl)) {
    histCache.set(t.sl, fetch(`${HIST_DIR}/${t.sl}.json`)
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }));
  }
  return histCache.get(t.sl);
}

// The score as psmf.cz writes it is home:away. In a history read from one
// team's side that flips meaning every other line, so it is turned round to
// ours:theirs and the row says which side we were.
const ourWay = s => s.split(':').reverse().join(':');

function tally(list) {
  const t = { w: 0, d: 0, l: 0, gf: 0, ga: 0 };
  list.forEach(m => {
    const p = (m.h ? m.s : ourWay(m.s)).split(':').map(Number);
    t.gf += p[0]; t.ga += p[1];
    if (m.r === 'W') t.w++; else if (m.r === 'L') t.l++; else t.d++;
  });
  return t;
}

// "2026-06-16" -> "16. 6. 2026"
const dmy = d => {
  const p = /(\d{4})-(\d{2})-(\d{2})/.exec(d || '');
  return p ? `${+p[3]}. ${+p[2]}. ${p[1]}` : (d || '');
};

// ---- the only biography the league keeps ------------------------------------
// psmf.cz has no description of a team: no founding date, no history, nothing
// on its page but the season you are looking at. What the league does record is
// which division everyone was in, every season back to 2007, and that is enough
// to say how long a team has been here and how far it has travelled.
const SEASON = { p: 'podzim', j: 'jaro' };
const seasonName = c => `${SEASON[c[0]]} ${c.slice(1)}`;
const seasonFrom = c => `${c[0] === 'p' ? 'podzimu' : 'jara'} ${c.slice(1)}`;
// 1 ligu, 2-4 ligy, 5+ lig -- and "o ligu" rather than "o 1 ligu".
const leagues = n => n === 1 ? 'o ligu' : `o ${n} ${n < 5 ? 'ligy' : 'lig'}`;

function bioLine(t) {
  const b = t.bio;
  if (!b) return '';
  const said = [b.n === 1 ? 'V soutěži je letos poprvé.'
    : `Hraje ${b.cap ? 'od jara 2007 nebo dřív' : 'od ' + seasonFrom(b.od)}${
        b.gap ? ', s přestávkou' : ''}, letos ${b.n}. sezonu.`];
  // The season cited is the most recent one at that level, so it has to say so
  // -- "6. liga (podzim 2025)" reads as the only time they were there.
  const when = c => c === NOW_SEASON ? 'letos' : 'naposledy ' + seasonName(c);
  // League first, place second: fourth in the 6th is a better season than third
  // in the 7th, and the league is named so nobody has to take that on trust.
  const fin = g => `${g[1]}. z ${g[2]} v ${g[0]}. lize (${seasonName(g[3])})`;
  if (b.top) {
    said.push(b.top[3] === b.bot[3] ? `Skončil ${fin(b.top)}.`
      : `Nejvýš skončil ${fin(b.top)}, nejníž ${fin(b.bot)}.`);
    if (b.won) {
      said.push(b.won[0] === 1 ? `Skupinu vyhrál jednou (${seasonName(b.won[1])}).`
        : `Skupinu vyhrál ${b.won[0]}&times;, naposledy ${seasonName(b.won[1])}.`);
    }
  } else if (b.n > 1) {
    said.push(b.lo
      ? `Nejvýš ${b.hi[0]}. liga (${when(b.hi[1])}), nejníž ${b.lo[0]}. liga (${when(b.lo[1])}).`
      : `Celou dobu v ${b.hi[0]}. lize.`);
  }
  if (b.pv) {
    // "7-G", "Vet 3-B", "Ultra 1-A" -- the tag carries no digits, so the first
    // number in the label is always the league.
    const m = /(\d+)/.exec(t.div);
    const d = m ? b.pv - +m[1] : 0;
    if (d) said.push(`Letos ${leagues(Math.abs(d))} ${d > 0 ? 'výš' : 'níž'} než loni.`);
  }
  return `<p class="bio">${said.join(' ')}</p>`;
}

function h2hChip(f) {
  if (!HIST_DIR || !f.hh) return '';
  return `<button type="button" class="h2h" data-opp="${esc(f.o)}"
    title="Vzájemné zápasy — výhry, remízy, prohry">${f.hh[0]}\u2013${f.hh[1]}\u2013${f.hh[2]}</button>`;
}

function histBox(title, inner) {
  return `<div class="progbox">
      <header><h3>${title}</h3>
        <button type="button" class="x" value="cancel" aria-label="Zavřít">&times;</button></header>
      ${inner}
    </div>`;
}

// ---- sixteen years in one block ---------------------------------------------
// Only for teams scraped with --detail: the line-ups, the scorers and the
// referee's man of the match. It arrives in the same file as the head-to-heads
// and is drawn once it does, so the fixtures are never waiting on it.
// ---- where a team has been ---------------------------------------------------
// "7-g" -> 7, and "Vet 3-B" would do the same: the tag carries no digits.
const level = d => +/(\d+)/.exec(d)[1];

// One season as the readout under the chart. Everything the division table had.
function seasonText(c) {
  const [code, div, place, of, pz, w, dr, l, score, pts] = c;
  const where = `${seasonName(code)} · ${div.toUpperCase()}`;
  return place
    ? `${where} · ${place}. z ${of} · ${pz} zápasů · ${w}\u2013${dr}\u2013${l} · ${score} · ${pts} b.`
    : `${where} · ${code === NOW_SEASON ? 'zatím bez tabulky' : 'bez tabulky'}`;
}

// The line is the league, season by season, 1 at the top; the dots are where
// they finished in it. The league is always known -- it is in data/archive --
// so the line is unbroken even where no table was read and the dot is hollow.
function careerLine(cr) {
  const W = 660, H = 186, L = 24, T = 18, B = 26;
  const lvls = cr.map(c => level(c[1]));
  const lo = Math.min(...lvls), hi = Math.max(...lvls), span = hi - lo;
  const x = i => L + i * (W - L - 8) / Math.max(1, cr.length - 1);
  const y = l => span ? T + (l - lo) * (H - T - B) / span : (T + H - B) / 2;
  const grid = [];
  for (let l = lo; l <= hi; l++) {
    grid.push(`<line x1="0" y1="${y(l).toFixed(1)}" x2="${W}" y2="${y(l).toFixed(1)}"
      stroke="var(--rule)"/><text x="0" y="${(y(l) - 7).toFixed(1)}"
      fill="var(--faint)" class="mono lab">${l}. liga</text>`);
  }
  const path = cr.map((c, i) =>
    `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(level(c[1])).toFixed(1)}`).join(' ');
  const dots = cr.map((c, i) => {
    const lvl = level(c[1]), place = c[2], of = c[3];
    const col = !place ? '' : place === 1 ? 'var(--accent)' : place <= 3 ? 'var(--home)'
      : place === of ? 'var(--away)' : 'var(--muted)';
    const cx = x(i).toFixed(1), cy = y(lvl).toFixed(1), t = esc(seasonText(c));
    // A second, invisible circle carries the pointer: a 4.5px dot is nothing to
    // aim at with a thumb, and the readout has to work by tap as well as hover.
    return `<circle cx="${cx}" cy="${cy}" r="${place ? 4.5 : 3}"
        fill="${place ? col : 'var(--surface)'}"${place ? '' :
        ' stroke="var(--muted)" stroke-width="1.5"'}></circle>
      <circle class="hit" cx="${cx}" cy="${cy}" r="13" fill="transparent"
        data-t="${t}"><title>${t}</title></circle>`;
  }).join('');
  // Six or so year labels, evenly spaced, whatever the length of the career, and
  // sitting on the chart itself rather than in a strip under it. They are drawn
  // before the line and stroked in the page's own background, so where the line
  // runs along the floor the label stays readable and the line stays unbroken.
  const step = Math.max(1, Math.ceil(cr.length / 7));
  const ticks = cr.map((c, i) => i % step ? '' :
    `<text x="${x(i).toFixed(1)}" y="${H - 4}" fill="var(--faint)"
      text-anchor="middle" class="mono lab">${c[0].slice(1)}</text>`).join('');
  return `<svg class="career" viewBox="0 0 ${W} ${H}" role="img"
      aria-label="Ligová úroveň a umístění po sezonách">${grid.join('')}${ticks}
      <path d="${path}" fill="none" stroke="var(--muted)" stroke-width="1.5" opacity=".55"/>
      ${dots}</svg>
    <p class="crpick" id="crpick">${esc(seasonText(
      [...cr].reverse().find(c => c[2]) || cr[cr.length - 1]))}</p>
    <p class="legend"><span><i style="background:var(--accent)"></i>vyhráli skupinu</span>
      <span><i style="background:var(--home)"></i>do třetího místa</span>
      <span><i style="background:var(--away)"></i>poslední</span>
      <span><i style="background:var(--muted)"></i>jinde</span></p>
    <p class="nt">Každý bod je sezona &mdash; najeďte na něj nebo na něj klepněte.${cr.some(c => !c[2] && c[0] !== NOW_SEASON)
      ? ' Za jaro 2020 PSMF žádné tabulky nezveřejnil a ten ročník se nepostupovalo ani nesestupovalo.'
      : ''}</p>`;
}

function squadBlock(sq, name) {
  // Captaincy is a tag rather than a column: it is one or two people for years
  // at a time, and a column of blanks says less than a word beside a name.
  const rows = sq.p.map(([n, ap, g, b, gk, cap, from, to]) => `<tr>
    <td><div class="cell"><span class="oname">${esc(n)}</span>${
      cap >= 5 && cap * 5 >= ap ? '<span class="role">kapitán</span>' : ''}</div></td>
    <td class="num">${ap}</td><td class="num">${g || ''}</td><td class="num">${b || ''}</td>
    <td class="num">${gk || ''}</td>
    <td class="dim">${esc(from === to ? from : from + ' – ' + to)}</td></tr>`).join('');
  const ex = (x, what) =>
    `<div class="stat"><b>${esc(x.s)}</b><span>${what} &middot; ${esc(x.o)}, ${esc(x.l)}</span></div>`;
  return `<div class="stats">
      <div class="stat"><b>${sq.n}</b><span>Odehraných zápasů</span></div>
      <div class="stat"><b class="long">${sq.w}&ndash;${sq.d}&ndash;${sq.l}</b><span>Bilance</span></div>
      <div class="stat"><b>${sq.gf}:${sq.ga}</b><span>Skóre</span></div>
      ${ex(sq.big, 'Nejvyšší výhra')}${ex(sq.bad, 'Nejvyšší prohra')}
    </div>
    <p class="bio">${sq.p.length} hráčů v sestavách, které rozhodčí zapsali.
      Hvězda je zápas, ve kterém rozhodčí označil hráče za nejlepšího na hřišti.</p>
    <div class="scroll"><table>
      <thead><tr><th>Hráč</th><th>Zápasů</th><th>Gólů</th>
      <th title="kolikrát ho rozhodčí označil za nejlepšího hráče zápasu">Hvězda</th>
      <th title="zápasy, ve kterých chytal">V bráně</th>
      <th>Sezony</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
}

function openHistory(t, name) {
  const dlg = document.getElementById('prog');
  const title = `${esc(t.name)} &ndash; ${esc(name)}`;
  dlg.setAttribute('aria-label', 'Vzájemné zápasy');
  dlg.innerHTML = histBox(title,
    '<p class="loading"><span class="sp" aria-hidden="true"></span>Načítám zápasy&hellip;</p>');
  if (dlg.showModal) dlg.showModal(); else dlg.setAttribute('open', '');
  histFor(t).then(data => {
    const list = (data.o || {})[name] || [];
    const r = tally(list);
    const items = list.map(m => {
      const cls = m.r === 'W' ? 'win' : m.r === 'L' ? 'loss' : 'draw';
      const half = m.hf ? (m.h ? m.hf : ourWay(m.hf)) : '';
      return `<li>
        <div class="hline"><span class="res ${cls}">${esc(m.h ? m.s : ourWay(m.s))}</span>
          ${half ? `<span class="hf">(${esc(half)})</span>` : ''}
          <span class="who">${m.h ? 'doma' : 'venku'} &middot; ${esc(m.l)}</span>
          <span class="meta2"><i>${esc(dmy(m.d))}</i><code>${esc(m.v)}</code></span></div>
        ${m.w ? `<p class="rep">${esc(m.w)}</p>` : ''}
        ${m.ref ? `<p class="ref">${esc(m.ref)}</p>` : ''}</li>`;
    }).join('');
    dlg.innerHTML = histBox(title,
      `<p class="hsum">${list.length}&times; &middot; ${r.w}&ndash;${r.d}&ndash;${r.l}
         &middot; skóre ${r.gf}:${r.ga} &middot; skóre je vždy z pohledu ${esc(t.name)}</p>
       <ul class="hist">${items}</ul>`);
  }).catch(err => {
    console.error('history:', err);
    dlg.innerHTML = histBox(title, '<p class="empty">Vzájemné zápasy se nepodařilo načíst.</p>');
  });
}

// ---- calendar export -------------------------------------------------------
// Times are written without a zone, on purpose. Every match is in Prague, and a
// floating time means 19:15 stays 19:15 whatever the calendar's own zone is and
// across the October clock change, which a UTC stamp would get wrong by an hour
// for half the season.
const SLOT_MIN = 75;                 // the league's slot: 19:15, 20:30, 21:45...

function icsEscape(s) {
  return String(s).replace(/\\/g, '\\\\').replace(/[;,]/g, m => '\\' + m)
    .replace(/\r?\n/g, '\\n');
}
// RFC 5545 wants lines folded at 75 octets, continued with a leading space.
function icsFold(line) {
  // Count octets, not characters: every Czech diacritic is two of them, and
  // counting characters left a third of the lines over the limit.
  const enc = new TextEncoder();
  if (enc.encode(line).length <= 73) return line;
  const out = [];
  let cur = '', n = 0;
  for (const ch of line) {
    const b = enc.encode(ch).length;
    if (n + b > 73) { out.push(cur); cur = ''; n = 0; }
    cur += ch; n += b;
  }
  out.push(cur);
  return out.join('\r\n ');            // a continuation is 1 + 73 octets
}

// A UID must stay the same across exports, so re-importing updates an event
// rather than duplicating it -- and must be plain ASCII to survive the trip.
function asciiId(s) {
  return String(s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

function icsDate(d, t) {
  // "Čt 1.10.26" + "20:30" -> 20261001T203000
  const m = /(\d{1,2})\.(\d{1,2})\.(\d{2,4})/.exec(d || '');
  const hm = /(\d{1,2}):(\d{2})/.exec(t || '');
  if (!m || !hm) return null;
  const yr = m[3].length === 2 ? 2000 + +m[3] : +m[3];
  const p = n => String(n).padStart(2, '0');
  return { start: new Date(yr, +m[2] - 1, +m[1], +hm[1], +hm[2]),
           fmt(dt) { return `${dt.getFullYear()}${p(dt.getMonth() + 1)}${p(dt.getDate())}` +
                            `T${p(dt.getHours())}${p(dt.getMinutes())}00`; } };
}

function icsFor(t) {
  const now = new Date();
  const p = n => String(n).padStart(2, '0');
  const stamp = `${now.getUTCFullYear()}${p(now.getUTCMonth() + 1)}${p(now.getUTCDate())}` +
    `T${p(now.getUTCHours())}${p(now.getUTCMinutes())}${p(now.getUTCSeconds())}Z`;
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0',
    'PRODID:-//psmf-pitches//Rozpis zapasu//CS', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
    `X-WR-CALNAME:${icsEscape(t.name + ' — PSMF podzim 2026')}`];

  t.fx.forEach(f => {
    const when = icsDate(f.d, f.t);
    if (!when) return;
    const end = new Date(when.start.getTime() + SLOT_MIN * 60000);
    const v = D.venues[f.c];
    const opp = kitByName.get((f.o || '').toLowerCase());
    const warn = !f.h && opp && clashes(t.sh, opp.sh);
    const title = f.h ? `${t.name} – ${f.o}` : `${f.o} – ${t.name}`;
    const desc = [
      `${f.r}. kolo, ${f.h ? 'doma' : 'venku'}`,
      v ? `Hřiště ${v.l} × ${v.w} m (${v.area} m²)` : null,
      v && v.boots ? (v.bootsText || `Obuv: ${v.boots}`) : null,
      warn ? 'Barvy dresů se kryjí a hrajeme venku — do trik.' : null,
      opp && opp.kit ? `Dres soupeře: ${opp.kit}` : null,
      v ? `Mapa: ${mapHref(v)}` : null,
    ].filter(Boolean).join('\n');

    lines.push('BEGIN:VEVENT',
      `UID:${asciiId(`${f.r}-${f.c}-${f.d}-${t.name}`)}@psmf-pitches`,
      `DTSTAMP:${stamp}`,
      `DTSTART:${when.fmt(when.start)}`,
      `DTEND:${when.fmt(end)}`,
      `SUMMARY:${icsEscape(title)}`,
      `LOCATION:${icsEscape(v ? [v.venue, v.addr].filter(Boolean).join(', ') : f.c)}`,
      `DESCRIPTION:${icsEscape(desc)}`,
      'END:VEVENT');
  });
  lines.push('END:VCALENDAR');
  return lines.map(icsFold).join('\r\n') + '\r\n';
}

function downloadIcs(t) {
  const name = 'psmf-' + t.name.toLowerCase().normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '') + '-podzim-2026.ics';
  const blob = new Blob([icsFor(t)], { type: 'text/calendar;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

let shown = null;                     // what renderTeam last drew

function renderTeam(i) {
  shown = i;
  const host = document.getElementById('team');
  const t = i == null ? null : D.teams[i];
  document.getElementById('all-head').textContent =
    t ? 'Všechna hřiště v adresáři · od největšího' : 'Všechna hřiště · od největšího';
  if (!t) { host.innerHTML = ''; return; }

  let warnings = 0;
  const rows = t.fx.map(f => {
    const v = D.venues[f.c];
    const opp = kitByName.get((f.o || '').toLowerCase());
    // we change when the colours clash and we are the visiting side
    const warn = !f.h && opp && clashes(t.sh, opp.sh);
    if (warn) warnings++;
    // Both of these are a row of small things -- name, shirt, balance, warning;
    // pin, ground, code, programme -- and laid out as inline text they sat on
    // the baseline at four different heights and wrapped between any two of
    // them. A flex line keeps them on one centre and breaks only where it must.
    return `<tr${warn ? ' class="warn"' : ''}>
      <td class="num">${f.r}</td>
      <td class="date">${esc(f.d)}<span class="t">${esc(f.t)}</span></td>
      <td class="num">${resultTag(f)}</td>
      <td><div class="cell"><span class="oname">${teamLink(f.o)}</span>${
        opp ? kit(opp.sw, opp.kit) : ''}${h2hChip(f)}${warn
        ? '<span class="clash" title="Barvy se kryjí a hrajeme venku">do trik</span>' : ''}</div></td>
      <td><div class="cell ground"><span class="gname">${v ? mapLink(v, 'lead') : ''}${
        v ? esc(v.venue) : ''}</span><code>${esc(f.c)}</code>${programmeChip(f, t)}</div></td>
      <td class="dim">${v ? v.l + ' &times; ' + v.w : '<span class="conf">nezměřeno</span>'}</td>
      <td>${v ? bootsTag(v) : ''}</td>
    </tr>`;
  }).join('');

  const codes = [];
  t.fx.forEach(f => { if (D.venues[f.c] && !codes.includes(f.c)) codes.push(f.c); });
  codes.sort((a, b) => D.venues[b].area - D.venues[a].area);
  const cards = codes.map(c => {
    const at = t.fx.filter(f => f.c === c)
      .map(f => `${f.r}. kolo ${f.h ? 'doma' : 'venku'} s ${esc(f.o)}`).join(', ');
    return card(D.venues[c], `<p class="fx">${at}</p>`);
  }).join('');

  const prov = t.fx.filter(f => f.s && !f.of).length;
  const met = new Set(t.fx.filter(f => f.hh).map(f => f.o)).size;
  let w = 0, d = 0, l = 0;
  t.fx.forEach(f => { const o = outcome(f); if (o === 'win') w++; else if (o === 'draw') d++; else if (o === 'loss') l++; });
  const played = w + d + l;
  const areas = codes.map(c => D.venues[c].area);
  const missing = t.fx.filter(f => !D.venues[f.c]).length;
  const ratio = areas.length ? (Math.max(...areas) / Math.min(...areas)).toFixed(1) + '×' : '—';
  // The fixtures first. The numbers above them are about the grounds, so they
  // belong with the grounds -- and they were the first thing a reader saw after
  // picking a team, which is not what anybody picked a team for.
  host.innerHTML = `
    <hr class="rule">
    <div class="h2row">
      <h2>${esc(t.name)}${kit(t.sw, t.kit)} &middot; ${esc(t.div)} &middot; rozpis zápasů</h2>
      <button type="button" class="ics" id="ics">Stáhnout do kalendáře (.ics)</button>
    </div>
    ${bioLine(t)}
    <div class="scroll"><table>
      <thead><tr><th>K</th><th>Datum</th><th>Výsledek</th>
      <th>Soupeř</th><th>Hřiště</th><th>Rozměr</th><th>Obuv</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    ${prov ? `<p class="nt">${prov}&times; je výsledek označený hvězdičkou předběžný — hlásí ho hráč a rozhodčí ho ještě může opravit.</p>` : ''}
    ${met ? `<p class="nt">S ${met} z nich se tento tým už potkal — číslo u jména je vzájemná bilance z minulých sezon, po kliknutí se rozbalí výsledky a co k nim napsal rozhodčí.</p>` : ''}
    ${warnings ? `<p class="nt">${warnings}&times; se barvy dresů kryjí se soupeřem a hrajeme venku — jdeme do trik.</p>` : ''}
    ${missing ? `<p class="nt">${missing}&times; se hraje na hřišti bez měření — hala, nebo kód, který adresář PSMF nevede.</p>` : ''}
    <div id="past"></div>
    <hr class="rule">
    <div class="stats">
      <div class="stat"><b>${t.fx.length}</b><span>Zápasů</span></div>
      ${played ? `<div class="stat"><b class="long">${w}&ndash;${d}&ndash;${l}</b><span>Bilance</span></div>` : ''}
      <div class="stat"><b>${codes.length}</b><span>Různých hřišť</span></div>
      <div class="stat"><b>${areas.length ? Math.min(...areas) + ' m²' : '—'}</b><span>Nejmenší</span></div>
      <div class="stat"><b>${areas.length ? Math.max(...areas) + ' m²' : '—'}</b><span>Největší</span></div>
      <div class="stat"><b>${ratio}</b><span>Největší ÷ nejmenší</span></div>
    </div>
    <h2>Hřiště tohoto týmu &middot; od největšího</h2>
    <div class="grid">${cards || '<p class="empty">Pro tento tým nejsou změřená hřiště.</p>'}</div>`;
  const btn = document.getElementById('ics');
  if (btn) btn.addEventListener('click', () => downloadIcs(t));

  // The career line and the squad live in the same fetched file, so they are
  // drawn together, after the fixtures are already on screen.
  if (t.sq || t.bio) {
    const box = document.getElementById('past');
    histFor(t).then(data => {
      if (shown !== i || (!data.cr && !data.sq)) return;
      box.innerHTML = `<hr class="rule"><h2>${esc(t.name)} &middot; ${
        data.sq ? 'co je zapsáno' : 'kudy prošel ligou'}</h2>`
        + (data.cr ? careerLine(data.cr) : '')
        + (data.sq ? squadBlock(data.sq, t.name) : '');
    }).catch(err => console.error('career:', err));
  }
}

// Bound once, to the container rather than to what is in it: renderTeam runs
// again on every pick, and a listener added there would stack up a copy per
// team looked at -- and then open the dialog twice, which throws the second
// time. #team is in the page from the start, so this can sit outside.
const crShow = e => {
  const hit = e.target.closest ? e.target.closest('.hit') : null;
  const box = document.getElementById('crpick');
  if (hit && box) box.textContent = hit.dataset.t;
};
document.getElementById('team').addEventListener('mouseover', crShow);
document.getElementById('team').addEventListener('touchstart', crShow, { passive: true });

document.getElementById('team').addEventListener('click', e => {
  if (e.target.closest && e.target.closest('.hit')) { crShow(e); return; }
  const more = e.target.closest('.more');
  if (more) {
    openProgramme(more.dataset.date, more.dataset.code, more.dataset.mine);
    return;
  }
  const past = e.target.closest('.h2h');
  if (past && shown !== null) { openHistory(D.teams[shown], past.dataset.opp); return; }
  const link = e.target.closest('.tlink');
  if (link) {
    e.preventDefault();
    const i = Number(link.dataset.i);
    showTeam(i);
    setParam(D.teams[i], true);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
});

function renderAll() {
  document.getElementById('all').innerHTML = Object.values(D.venues)
    .sort((a, b) => b.area - a.area).map(v => card(v, '')).join('');
}

// ---- theme: system by default, with an explicit choice remembered.
const THEMES = [
  ['auto',  'motiv: systém'],
  ['light', 'motiv: světlý'],
  ['dark',  'motiv: tmavý'],
];
const themeBtn = document.getElementById('theme');
let themeIdx = 0;
try {
  const stored = localStorage.getItem('psmf-theme');
  const n = THEMES.findIndex(t => t[0] === stored);
  if (n > 0) themeIdx = n;
} catch (e) { }

function applyTheme() {
  const [name, text] = THEMES[themeIdx];
  const root = document.documentElement;
  if (name === 'auto') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', name);
  themeBtn.textContent = text;
  try {
    if (name === 'auto') localStorage.removeItem('psmf-theme');
    else localStorage.setItem('psmf-theme', name);
  } catch (e) { /* private window, blocked storage: the toggle still works */ }
}
themeBtn.addEventListener('click', () => {
  themeIdx = (themeIdx + 1) % THEMES.length;
  applyTheme();
});
applyTheme();

const input = document.getElementById('team-input');
const sugg = document.getElementById('sugg');
const clearBtn = document.getElementById('clear');
const label = t => `${t.name} (${t.div})`;
// Fold case and diacritics: nobody types Pražačka with the háček when hunting.
const fold = s => String(s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
let keys = [];

// A datalist looked like the obvious control and is not: Chrome and Edge
// suppress it whenever the input carries autocomplete="off", and with 720
// entries the native list is a scroll rather than a search. This is a plain
// filtered listbox, so what it does is the same in every browser.
let matches = [], active = -1;

function closeList() {
  sugg.hidden = true; sugg.innerHTML = ''; matches = []; active = -1;
  input.setAttribute('aria-expanded', 'false');
}

function openList(q) {
  const f = fold(q);
  matches = f ? D.teams.map((t, i) => i).filter(i => keys[i].indexOf(f) >= 0) : [];
  if (!matches.length) {
    sugg.innerHTML = f ? '<p class="none">Žádný tým neodpovídá.</p>' : '';
    sugg.hidden = !f;
    input.setAttribute('aria-expanded', String(!!f));
    return;
  }
  const shown = matches.slice(0, 40);
  sugg.innerHTML = shown.map((i, n) => {
    const t = D.teams[i];
    return `<button type="button" role="option" data-i="${i}" aria-selected="${n === 0}">` +
           `${esc(t.name)}<span>${esc(t.div)}</span></button>`;
  }).join('') + (matches.length > shown.length
    ? `<p class="none">…a dalších ${matches.length - shown.length}</p>` : '');
  matches = shown;
  active = 0;
  sugg.hidden = false;
  input.setAttribute('aria-expanded', 'true');
}

function showClear() { clearBtn.hidden = !input.value; }

function choose(i) {
  input.value = label(D.teams[i]);
  renderTeam(i);
  setParam(D.teams[i], true);
  closeList();
  showClear();
  // The tap that picks a team is a mousedown we preventDefault, so focus never
  // leaves the input and the phone keyboard stays up over the fixtures the tap
  // just asked for. Nothing more is being typed, so let it go.
  input.blur();
}

clearBtn.addEventListener('click', () => {
  input.value = '';
  renderTeam(null);
  // Replaced, not pushed: clearing is undoing a choice, not making one, and
  // pushing it means Back lands on the empty page you just left rather than on
  // the team you were reading before it.
  setParam(null, false);
  closeList();
  showClear();
  input.focus();
});

function highlight(n) {
  const btns = sugg.querySelectorAll('button');
  if (!btns.length) return;
  active = (n + btns.length) % btns.length;
  btns.forEach((b, k) => b.setAttribute('aria-selected', String(k === active)));
  btns[active].scrollIntoView({ block: 'nearest' });
}

sugg.addEventListener('mousedown', e => {          // before blur
  const b = e.target.closest('button');
  if (b) { e.preventDefault(); choose(Number(b.dataset.i)); }
});
input.addEventListener('input', () => {
  showClear();
  if (!input.value.trim()) { renderTeam(null); setParam(null, false); closeList(); return; }
  openList(input.value);
});
input.addEventListener('keydown', e => {
  if (sugg.hidden) { if (e.key === 'ArrowDown') openList(input.value); return; }
  if (e.key === 'ArrowDown') { e.preventDefault(); highlight(active + 1); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); highlight(active - 1); }
  else if (e.key === 'Enter') {
    const btns = sugg.querySelectorAll('button');
    if (btns.length && active >= 0) { e.preventDefault(); choose(Number(btns[active].dataset.i)); }
  } else if (e.key === 'Escape') closeList();
});
input.addEventListener('focus', () => { if (input.value.trim()) openList(input.value); });
input.addEventListener('blur', () => setTimeout(closeList, 120));

const lookup = v => {
  const f = fold(v);
  const i = keys.indexOf(f);
  if (i >= 0) return i;
  // Fall back to the bare name, so a link shared last season still opens on the
  // team after it has moved division -- but only when the name picks out one.
  const stripped = f.replace(/\s*\([^)]*\)\s*$/, '');
  const bare = D.teams.map((t, n) => n).filter(n => fold(D.teams[n].name) === stripped);
  return bare.length === 1 ? bare[0] : null;
};

// The chosen team lives in the URL, so a link shares the view rather than the
// page, and picking one is a history entry so Back returns to the team you were
// looking at. Clearing replaces instead: it undoes a choice rather than making
// one, and as an entry of its own it made Back go to the empty page you had just
// left. Typing to filter does not touch the URL at all.
function setParam(t, push) {
  try {
    const u = new URL(location.href);
    if (t) u.searchParams.set('team', label(t)); else u.searchParams.delete('team');
    if (u.href === location.href) return;
    if (push) history.pushState(null, '', u); else history.replaceState(null, '', u);
  } catch (e) { /* file:// and the like */ }
}

function showTeam(i) {
  input.value = i === null ? '' : label(D.teams[i]);
  renderTeam(i);
  closeList();
  showClear();
}

// Back and forward move between the teams you looked at.
window.addEventListener('popstate', () => {
  let i = null;
  try { i = lookup(new URLSearchParams(location.search).get('team') || ''); } catch (e) { }
  showTeam(i);
});

// Close the dialog on the X, on a click outside the panel, or on Escape (which
// <dialog> handles by itself). Team links inside it jump and close.
const dlg = document.getElementById('prog');
dlg.addEventListener('click', e => {
  const link = e.target.closest('.tlink');
  if (link) {
    e.preventDefault();
    const i = Number(link.dataset.i);
    dlg.close();
    showTeam(i);
    setParam(D.teams[i], true);
    window.scrollTo({ top: 0, behavior: 'smooth' });
    return;
  }
  if (e.target.closest('.x') || !e.target.closest('.progbox')) dlg.close();
});

// Parsing four megabytes of JSON and laying out thirty-nine cards takes a
// moment, and the script runs last, so without yielding first the browser never
// paints the spinner it is about to replace. Two frames guarantees one paint.
function boot() {
  renderAll();                       // the pitches: they are already in the page
  const load = document.getElementById('loading');
  if (load) load.hidden = true;
  loadTeams();
}

// The fixtures are a megabyte and nobody needs them until a team is picked, so
// they arrive after the pitches are on screen. Until then the picker says so
// rather than sitting there looking broken.
function loadTeams() {
  const who = document.querySelector('.pick .who');
  input.disabled = true;
  input.placeholder = 'Načítám týmy…';
  fetch(TEAMS_URL)
    .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(data => {
      D.teams = data.teams || [];
      indexTeams();
      input.disabled = false;
      input.placeholder = 'Začněte psát název týmu…';
      if (who) who.textContent = `${D.teams.length} týmů · odkaz na vybraný tým lze sdílet`;
      let start = null;
      try { start = lookup(new URLSearchParams(location.search).get('team') || ''); } catch (e) { }
      if (start !== null) { input.value = label(D.teams[start]); renderTeam(start); }
      showClear();
    })
    .catch(err => {
      input.placeholder = 'Rozpisy se nepodařilo načíst';
      if (who) who.textContent = 'Rozpisy se nenačetly — zkuste obnovit stránku.';
      console.error('teams.json:', err);
    });
}

if (window.requestAnimationFrame) {
  requestAnimationFrame(() => requestAnimationFrame(boot));
} else {
  boot();
}
"""

hist_dir = f'"data/{HIST_DIR}"' if HIST_DIR else "null"
# Which season the page is about, so a career can say "letos" instead of
# naming it. Every competition rolls over together, so one is enough.
now_season = season_code(seen_seasons["hanspaulska-liga"][0])

html = f"""<meta charset="utf-8">
<title>Rozpis, hřiště a vzájemné zápasy — PSMF</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Vyberte tým a uvidíte celou sezonu: kdy a kde hraje, jak velké to hřiště je, v čem se na něm smí hrát, jestli se kryjí dresy a jak to dopadlo, když jste se se soupeřem potkali naposledy. Hanspaulská i všechny tři veteránské soutěže.">
<style>{CSS}</style>
<script>{EARLY_JS}</script>

<div class="wrap">
<div class="top">
  <p class="eyebrow">PSMF &middot; Hanspaulsk&aacute;, veter&aacute;nsk&aacute;, super a ultra &middot; podzim 2026</p>
  <button type="button" class="theme" id="theme" aria-live="polite">motiv</button>
</div>
<h1>Celá sezona vašeho týmu na jedné stránce</h1>
<p class="lede">Vyberte tým a uvidíte jeho rozpis: kdy a kde se hraje, jak velké
to hřiště je a v čem se na něm smí hrát, jestli se kryjí dresy, co se tam hraje
před vámi a po vás — a jak to dopadlo, když jste se se soupeřem potkali
naposledy, i s tím, co k zápasu napsal rozhodčí. Hanspaulská a všechny tři
veteránské soutěže.</p>

<hr class="rule">
<div class="pick">
  <label for="team-input">Tým</label>
  <div class="combo">
    <input id="team-input" type="text" placeholder="Začněte psát název týmu&hellip;"
           role="combobox" aria-expanded="false" aria-autocomplete="list"
           aria-controls="sugg" spellcheck="false">
    <button type="button" class="clear" id="clear" hidden
            aria-label="Vymazat výběr týmu" title="Vymazat">&times;</button>
    <div class="sugg" id="sugg" role="listbox" hidden></div>
  </div>
  <span class="who">načítám rozpisy&hellip;</span>
</div>
<noscript><p class="lede" style="margin-top:18px">Výběr týmu probíhá v prohlížeči,
takže tahle část potřebuje JavaScript. Samotná měření jsou v souboru
<code>out/measurements.json</code> v repozitáři.</p></noscript>

<div id="team"></div>
<dialog id="prog" aria-label="Program na hřišti"></dialog>

<hr class="rule">
<h2 id="all-head">Všechna hřiště &middot; od největšího</h2>
<p class="lede" style="margin-bottom:18px">{len(play)} hřišť, každé proměřené
podle čar v ortofotomapě IPR Praha s rozlišením 5&nbsp;cm na pixel. Nejmenší z nich,
{smallest["venue"]}, by se do největšího ({largest["venue"]})
vešlo {largest["area"] / smallest["area"]:.1f}&times;.</p>
<div class="grid" id="all"></div>
<p class="loading" id="loading"><span class="sp" aria-hidden="true"></span>Načítám hřiště&hellip;</p>

<footer>
Podklad: ortofotomapa IPR Praha, 0,05&nbsp;m/px, EPSG:5514 (S-JTSK); snímkování vybráno
zvlášť pro každé hřiště. Rozpisy a souřadnice hřišť z <a href="https://www.psmf.cz/">psmf.cz</a>.
Každý obdélník je proložení skutečných čar a lze ho porovnat s fotkou vedle něj.
Vygenerováno {date.today().strftime("%-d. %-m. %Y")}.
</footer>
</div>

<script type="application/json" id="psmf-data">{blob}</script>
<script>const TEAMS_URL = "data/{TEAMS_FILE}";
const HIST_DIR = {hist_dir};
const NOW_SEASON = "{now_season}";</script>
<script>{JS}</script>
"""

out = ROOT / "docs/index.html"
out.parent.mkdir(exist_ok=True)
(out.parent / ".nojekyll").touch()
out.write_text(html, "utf-8")
print(f"{out}  {out.stat().st_size/1e6:.2f} MB  "
      f"({len(play)} venues, {len(teams)} teams)")
