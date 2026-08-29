#!/usr/bin/env python3
"""Every team's back catalogue, with the referee's write-up for each match.

psmf.cz keeps the whole archive back to 2007 but links a team to none of its
earlier selves: the `<` arrow on a team page reaches one season back at best,
and often not that -- ours skips straight over podzim 2025, which we certainly
played. Nothing on the site answers "where was this team in 2015?" either. So
the first pass builds that answer: for every season, walk its division pages and
write down which division each slug was in (data/archive/<season>.json). That is
about 3,700 requests once, after which finding any team in any season is free.

The second pass reads team pages. A played match there carries more than a
score: under `Detaily utkani` it has the half-time score, the referee's name,
and a paragraph he wrote about the game, which exists nowhere else on the site.
One file per team, recording which seasons it has been given, so an interrupted
run resumes where it stopped and a wider one tops it up.

Reading every team's whole past is 15,000 pages for the main league alone, and
all the page ever shows is what happened the last time these two met. So by
default only the seasons that can hold such a match are read -- the index above
already says which those are, before any request -- and `--full` reads the lot
for a team worth the pages.

A team is searched only within its own competition -- the veteran leagues keep
their own archives -- and four seasons in a row without it ends its walk. Teams
do sit one out, and jaro 2021 did not happen at all.

    ./.venv/bin/python scrape_history.py --all             # everyone
    ./.venv/bin/python scrape_history.py --slug zde-je-misto --full
    ./.venv/bin/python scrape_history.py --all --seasons 2  # re-read the season just ended
"""
from __future__ import annotations
import argparse, datetime, json, re, sys, time
from pathlib import Path

import scrape_psmf as S
import scrape_season as SS

BASE = S.BASE
DATA = Path(__file__).parent / "data"
ARCHIVE = DATA / "archive"        # <season>.json: slug -> where it played
HIST = DATA / "hist"              # <family>/<slug>.json: one team's past
FAMILIES = ("hanspaulska-liga", "veteranska-liga",
            "superveteranska-liga", "ultraveteranska-liga")
# Seasons a team can be missing from before we accept it was not there yet.
GAP = 4


def family_of(comp: str) -> str:
    """'2026-superveteranska-liga-podzim' -> 'superveteranska-liga'."""
    return comp.split("-", 1)[1].rsplit("-", 1)[0]


def label(season: str) -> str:
    return f"{season.rsplit('-', 1)[1]} {season[:4]}"


def newest_first(seasons):
    return sorted(seasons, key=lambda s: (int(s[:4]), s.endswith("podzim")),
                  reverse=True)


def all_seasons() -> dict[str, list[str]]:
    """Every season on the site, by competition, newest first."""
    html = S.get(f"{BASE}/souteze/")
    out: dict[str, list[str]] = {f: [] for f in FAMILIES}
    for s in set(re.findall(r'href="/souteze/(\d{4}-[a-z]+-liga-(?:jaro|podzim))/"', html)):
        if family_of(s) in out:
            out[family_of(s)].append(s)
    return {f: newest_first(v) for f, v in out.items()}


def season_index(season: str, pause: float) -> dict:
    """slug -> division for one season, cached.

    Only the division: a team page is always
    /souteze/<season>/<division>/tymy/<slug>/, so storing the URL would repeat
    the season and the slug on every one of 700 lines, 39 times a competition.

    The bare group headers ('1', '7') list no teams of their own; they cost a
    request each and are skipped by team_urls anyway.
    """
    path = ARCHIVE / f"{season}.json"
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    teams: dict[str, str] = {}
    divs = SS.division_slugs(season)
    time.sleep(pause)
    for d in divs:
        try:
            for _url, slug in SS.team_urls(season, d):
                teams[slug] = d
        except Exception as e:                       # noqa: BLE001
            print(f"    {season}/{d}: {e}", file=sys.stderr)
        time.sleep(pause)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(teams, ensure_ascii=False, indent=1), "utf-8")
    print(f"  {season}: {len(divs)} divisions, {len(teams)} teams", file=sys.stderr)
    return teams


def parse_date(text: str) -> str | None:
    m = re.search(r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{2,4})", text or "")
    if not m:
        return None
    y = int(m.group(3))
    return datetime.date(2000 + y if y < 100 else y,
                         int(m.group(2)), int(m.group(1))).isoformat()


def match_details(html: str) -> dict[str, dict]:
    """gameid -> half-time score, referee, and the referee's write-up.

    Only the part of the page below the `gameResults` anchor: the results table
    above it repeats every fixture, and the venue's other matches besides.
    """
    tail = html.split('name="gameResults"')[-1]
    parts = re.split(r'<div class="component__table-wrap" id="GameResultItem(\d+)">', tail)
    out = {}
    for gid, body in zip(parts[1::2], parts[2::2]):
        half = re.search(r'class="period-goals">\((\d+:\d+)\)', body)
        report = referee = ""
        row = re.search(r"Popis zápasu.*?</tr>\s*<tr>(.*?)</tr>", body, re.S)
        if row:
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S)
            if len(tds) >= 2:
                report, referee = S.strip_tags(tds[0]), S.strip_tags(tds[1])
        out[gid] = {"half": half.group(1) if half else "",
                    "report": report, "referee": referee}
    return out


def parse_season(html: str, slug: str) -> list[dict]:
    """One team page -> its matches, details folded in."""
    head = html.split('name="gameResults"')[0]
    det = match_details(html)
    out, seen = [], set()
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", head, re.S | re.I):
        code = re.search(r'href="/hriste/#([A-Z0-9]+)"', row)
        if not code:
            continue
        links = re.findall(r'href="/souteze/[^"]*/tymy/([^"/]+)/"[^>]*>(.*?)</a>', row, re.S)
        sides = [(s, S.strip_tags(n)) for s, n in links]
        if slug not in {s for s, _ in sides} or len(sides) != 2:
            continue                    # the venue's other matches that day
        cells = [S.strip_tags(c) for c in
                 re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        date = parse_date(next((c for c in cells if parse_date(c)), ""))
        key = (date, code.group(1))
        if key in seen:
            continue
        seen.add(key)
        home = sides[0][0] == slug
        opp = sides[1] if home else sides[0]
        score = cells[-1].strip() if cells and re.fullmatch(
            r"\d{1,2}:\d{1,2}", cells[-1].strip()) else ""
        gid = re.search(r'data-gameid="(\d+)"', row)
        d = det.get(gid.group(1) if gid else "", {})
        m = {"date": date, "venue": code.group(1),
             "opponent": opp[1], "opp_slug": opp[0], "home": home,
             "score": score, "half": d.get("half", ""),
             "referee": d.get("referee", ""), "report": d.get("report", "")}
        if score:
            h, a = (int(x) for x in score.split(":"))
            # The score is always written home:away; ours is whichever side we were.
            m["gf"], m["ga"] = (h, a) if home else (a, h)
            m["res"] = "W" if m["gf"] > m["ga"] else "L" if m["gf"] < m["ga"] else "D"
        out.append(m)
    return out


def seasons_played(slug: str, seasons: list[str], index: dict) -> list[str]:
    """The seasons a team appears in, newest first, stopping at a real gap.

    Once it has been absent for GAP seasons running it had simply not been
    founded yet, and without that the walk reaches 2007 for everybody.
    """
    played = [s for s in seasons if slug in index[s]]
    if not played:
        return []
    keep, missed = [], 0
    for s in seasons[seasons.index(played[0]):]:
        if slug in index[s]:
            keep.append(s)
            missed = 0
        else:
            missed += 1
            if missed >= GAP:
                break
    return keep


def worth_reading(slug: str, keep: list[str], index: dict,
                  opponents: list[str], current: str) -> list[str]:
    """Of those, the seasons that can hold a match against this year's opponents.

    Reading every team's whole past is 15,000 pages for the main league alone,
    and all the page ever shows is what happened the last time these two met. A
    season in which none of this year's opponents was in the same division
    cannot contain one of those matches, and the index already knows -- for
    free, before any request. It cuts the walk to a third.

    The season being played is left out as well: those are fixtures, not
    history, and half of them have not happened. `--seasons 1` folds them in
    once it is over.
    """
    return [s for s in keep if s != current
            and any(index[s].get(o) and index[s][o] == index[s][slug]
                    for o in opponents)]


def team_history(family: str, slug: str, read: list[str], played: list[str],
                 index: dict, pause: float, force=frozenset()) -> dict:
    """Read `read` seasons of one team and merge them into its file.

    The file records which seasons it has actually been given and whether that
    is all of them, so a later, wider run tops it up instead of starting over.
    Seasons already in it are skipped unless named in `force` -- which is what
    re-reading the season being played amounts to, its scores and the referees'
    write-ups still arriving weeks after the match.
    """
    path = HIST / family / f"{slug}.json"
    have = json.loads(path.read_text("utf-8")) if path.exists() else {}
    done = set(have.get("seasons", []))
    need = [s for s in read if s not in done or s in force]
    if not need:
        return have

    name, matches = have.get("team", ""), []
    for season in need:
        try:
            html = S.get(f"{BASE}/souteze/{season}/{index[season][slug]}/tymy/{slug}/")
        except Exception as e:                        # noqa: BLE001
            print(f"    {slug} {season}: {e}", file=sys.stderr)
            continue
        time.sleep(pause)
        title = re.search(r'class="component__title">(.*?)</h1>', html, re.S)
        if title:
            name = name or S.strip_tags(title.group(1))
        for m in parse_season(html, slug):
            m.update(season=season, label=label(season),
                     division=index[season][slug])
            matches.append(m)

    fresh = set(need)
    matches += [m for m in have.get("matches", []) if m["season"] not in fresh]
    matches.sort(key=lambda m: m["date"] or "", reverse=True)
    seasons = [s for s in played if s in done | fresh]
    out = {"slug": slug, "team": name, "family": family, "seasons": seasons,
           "complete": set(seasons) >= set(played), "matches": matches}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="every team in data/season.json")
    ap.add_argument("--slug", help="one team (with --family if it is a veteran side)")
    ap.add_argument("--family", default="hanspaulska-liga", choices=FAMILIES)
    ap.add_argument("--full", action="store_true",
                    help="every season a team played, not only the ones that can "
                         "hold a match against this year's opponents")
    # The N newest seasons on the site, re-read whether the files already hold
    # them or not: a finished season's scores and write-ups keep arriving for
    # weeks. Two, not one, once the new draw is up -- it is then the newest.
    ap.add_argument("--seasons", type=int, default=0,
                    help="also re-read the N newest seasons of the competition")
    # A second between requests, and each one takes about that again to come
    # back. This walks thousands of pages of somebody else's small site; there
    # is nowhere to be in a hurry to.
    ap.add_argument("--pause", type=float, default=1.0,
                    help="seconds between requests")
    ap.add_argument("--index-only", action="store_true",
                    help="build the season indexes and stop")
    args = ap.parse_args()

    if not (args.all or args.slug or args.index_only):
        ap.error("give --all, --slug or --index-only")

    season = json.loads((DATA / "season.json").read_text("utf-8"))
    # Opponents are named in a fixture, not linked. Within one competition the
    # names are unique, so that is enough to turn them back into slugs.
    by_name = {(family_of(t.get("comp", "")), t["name"]): t["slug"]
               for t in season["teams"]}
    wanted: dict[str, list[dict]] = {f: [] for f in FAMILIES}
    for t in season["teams"]:
        f = family_of(t.get("comp", ""))
        if f not in wanted:
            continue
        if args.slug and not (t["slug"] == args.slug and f == args.family):
            continue
        if not (args.all or args.slug):
            continue
        opps = [by_name.get((f, x["opponent"])) for x in t["fixtures"]]
        wanted[f].append({"slug": t["slug"], "name": t["name"], "comp": t["comp"],
                          "opps": [o for o in opps if o]})

    by_family = all_seasons()
    families = FAMILIES if args.index_only or args.all else (args.family,)

    # First pass: where everybody played, every season. Cached, so this is the
    # only part that costs anything on a second run.
    index: dict[str, dict] = {}
    for f in families:
        print(f"{f}: {len(by_family[f])} seasons", file=sys.stderr)
        for s in by_family[f]:
            index[s] = season_index(s, args.pause)
    if args.index_only:
        return

    # Second pass: one page per team per season worth reading.
    total = sum(len(v) for v in wanted.values())
    done = pages = 0
    for f in FAMILIES:
        for t in wanted[f]:
            played = seasons_played(t["slug"], by_family[f], index)
            read = played if args.full else worth_reading(
                t["slug"], played, index, t["opps"], t["comp"])
            force = by_family[f][:args.seasons] if args.seasons else []
            read = [s for s in played if s in set(read) | set(force)]
            h = team_history(f, t["slug"], read, played, index, args.pause,
                             force=set(force))
            done += 1
            pages += len(read)
            if done % 25 == 0 or done == total:
                print(f"  [{done}/{total}] {t['name']}: "
                      f"{len(h.get('matches', []))} matches over "
                      f"{len(h.get('seasons', []))} of {len(played)} seasons",
                      file=sys.stderr)

    files = sorted(HIST.rglob("*.json"))
    matches = sum(len(json.loads(p.read_text("utf-8"))["matches"]) for p in files)
    print(f"\n-> {HIST}: {len(files)} teams, {matches} matches, "
          f"{sum(p.stat().st_size for p in files)/1e6:.1f} MB", file=sys.stderr)


if __name__ == "__main__":
    main()
