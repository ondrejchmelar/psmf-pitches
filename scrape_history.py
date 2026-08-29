#!/usr/bin/env python3
"""Our own back catalogue: every past match, with the referee's write-up.

psmf.cz keeps the whole archive back to 2007, but nothing in it links a team
to its earlier selves. The `<` arrow on a team page points only at the season
immediately before, and only sometimes -- ours skips over podzim 2025, which we
certainly played. So a team is found the only way the site allows: by walking a
season's division pages until its slug turns up.

That is 68 requests per season done blindly, which is why `find_team` starts
from the division we were in last season and works outwards. Teams move by a
division or two, so the hit usually comes within a handful of requests. The
answer is cached in data/history_index.json; past seasons never change.

A played match carries more than a score. Under `Detaily utkani` each one has
the half-time score, the referee's name, and a paragraph of his own describing
the game -- which is the interesting part, and exists nowhere else.

    ./.venv/bin/python scrape_history.py             # our team, all the way back
    ./.venv/bin/python scrape_history.py --seasons 1 # only this one, merged in
    ./.venv/bin/python scrape_history.py --slug tohle-neni-hokej
"""
from __future__ import annotations
import argparse, datetime, json, re, sys, time
from pathlib import Path

import scrape_psmf as S

BASE = S.BASE
DATA = Path(__file__).parent / "data"
INDEX = DATA / "history_index.json"
SLUG = "zde-je-misto"
START = "2026-hanspaulska-liga-podzim"
START_DIV = "7-g"
# Seasons a team can be missing from before we accept it did not exist yet.
# Teams do sit one out, so a single gap is not the end of the history.
GAP = 4


def seasons() -> list[str]:
    """Every Hanspaulska season on the site, newest first."""
    html = S.get(f"{BASE}/souteze/")
    found = set(re.findall(r'href="/souteze/(\d{4}-hanspaulska-liga-(?:jaro|podzim))/"', html))
    return sorted(found, key=lambda s: (int(s[:4]), s.endswith("podzim")), reverse=True)


def label(season: str) -> str:
    return f"{season.rsplit('-', 1)[1]} {season[:4]}"


def div_key(d: str) -> tuple[int, int]:
    """'7-g' -> (7, 6). Bare group headers ('7') sort as their own level."""
    m = re.match(r"(\d+)(?:-([a-z]))?$", d)
    if not m:
        return (99, 0)
    return (int(m.group(1)), ord(m.group(2)) - ord("a") if m.group(2) else -1)


def find_team(season: str, slug: str, near: str, pause: float) -> dict | None:
    """The team's page in this season, or None. Searches outwards from `near`."""
    import scrape_season as SS
    divs = [d for d in SS.division_slugs(season) if re.match(r"\d+-[a-z]$", d)]
    time.sleep(pause)
    lvl, let = div_key(near)
    divs.sort(key=lambda d: (abs(div_key(d)[0] - lvl), abs(div_key(d)[1] - let)))
    for i, d in enumerate(divs, 1):
        try:
            urls = SS.team_urls(season, d)
        except Exception as e:                       # noqa: BLE001
            print(f"    {d}: {e}", file=sys.stderr)
            continue
        time.sleep(pause)
        for url, s in urls:
            if s == slug:
                print(f"  {label(season):14s} {d:5s} (after {i} division pages)", file=sys.stderr)
                return {"division": d, "url": url}
    print(f"  {label(season):14s} not found in {len(divs)} divisions", file=sys.stderr)
    return None


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default=SLUG)
    ap.add_argument("--from-season", default=START)
    ap.add_argument("--division", default=START_DIV, help="where the team is now")
    ap.add_argument("--gap", type=int, default=GAP)
    ap.add_argument("--seasons", type=int, default=0,
                    help="only the N newest seasons, merged into the existing file")
    ap.add_argument("--pause", type=float, default=0.35)
    ap.add_argument("--out", default="history.json")
    args = ap.parse_args()

    index = json.loads(INDEX.read_text("utf-8")) if INDEX.exists() else {}
    known = index.setdefault(args.slug, {})
    known.setdefault(args.from_season, {"division": args.division,
                                        "url": f"/souteze/{args.from_season}/{args.division}"
                                               f"/tymy/{args.slug}/"})

    all_seasons = seasons()
    start = all_seasons.index(args.from_season)
    near, missed, found = args.division, 0, []
    for season in all_seasons[start:]:
        hit = known.get(season)
        if hit is None:
            hit = find_team(season, args.slug, near, args.pause)
            known[season] = hit
            INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
        if not hit:
            missed += 1
            if missed >= args.gap:
                print(f"  stopping: {missed} seasons in a row without them", file=sys.stderr)
                break
            continue
        missed = 0
        near = hit["division"]
        found.append((season, hit))
        if args.seasons and len(found) >= args.seasons:
            break

    team, matches = "", []
    for season, hit in found:
        html = S.get(BASE + hit["url"])
        time.sleep(args.pause)
        title = re.search(r'class="component__title">(.*?)</h1>', html, re.S)
        team = team or S.strip_tags(title.group(1))
        got = parse_season(html, args.slug)
        for m in got:
            m.update(season=season, label=label(season), division=hit["division"])
        played = sum(1 for m in got if m.get("score"))
        reports = sum(1 for m in got if m.get("report"))
        print(f"  {label(season):14s} {hit['division']:5s} {len(got):2d} zápasů, "
              f"{played} se skóre, {reports} s popisem", file=sys.stderr)
        matches += got

    # A partial run keeps what it did not look at. Past seasons do not change,
    # so the daily job re-reads only the current one -- where a score can still
    # arrive, and the referee's write-up usually does a few days after that.
    path = DATA / args.out
    seasons_out = [{"season": s, "label": label(s), **h} for s, h in found]
    if args.seasons and path.exists():
        old_data = json.loads(path.read_text("utf-8"))
        fresh = {s for s, _ in found}
        matches += [m for m in old_data.get("matches", []) if m["season"] not in fresh]
        seasons_out += [s for s in old_data.get("seasons", []) if s["season"] not in fresh]
        seasons_out.sort(key=lambda s: (int(s["season"][:4]),
                                        s["season"].endswith("podzim")), reverse=True)
        team = team or old_data.get("team", "")

    matches.sort(key=lambda m: m["date"] or "", reverse=True)
    out = {"team": team, "slug": args.slug,
           "seasons": seasons_out, "matches": matches}
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print(f"\n-> {path}  {path.stat().st_size/1e3:.0f} kB\n"
          f"   {team}: {len(matches)} matches over {len(seasons_out)} seasons, "
          f"{sum(1 for m in matches if m.get('report'))} with a write-up", file=sys.stderr)


if __name__ == "__main__":
    main()
