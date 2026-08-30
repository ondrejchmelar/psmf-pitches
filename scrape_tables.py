#!/usr/bin/env python3
"""Final standings for every division of every season -> data/tables/.

The team pages give fixtures and results; they never give a table. Where a team
finished, and on how many points, is only on the division page -- and there
behind an AJAX call, `?cmd=tables&...&type=final`, which answers with the whole
group in one request. Twelve teams a request is what makes this affordable at
all: the same coverage from team pages would be twelve times the crawl.

Most of the query is derivable -- `league` is the number in the division slug,
`group_id` the position of its letter -- but `competition` and `season` are
internal ids that are not. Veteran spring 2026 is season=10, super-veteran the
same spring is season=21. So each season is probed once, on one division page,
and the ids read off the link the page itself would have called.

One file per season, so an interrupted run resumes and a finished season is
never asked for twice.

    ./.venv/bin/python scrape_tables.py                  # everything not yet done
    ./.venv/bin/python scrape_tables.py --season 2026-hanspaulska-liga-jaro
"""
from __future__ import annotations
import argparse, json, re, sys, time
from pathlib import Path

import scrape_psmf as S

DATA = Path(__file__).parent / "data"
ARCHIVE = DATA / "archive"
OUT = DATA / "tables"


def newest_first(seasons):
    return sorted(seasons, key=lambda s: (int(s[:4]), s.endswith("podzim")), reverse=True)


def divisions(season: str) -> list[str]:
    """The real divisions of a season, from the archive index we already have.

    A bare group header ('7') lists no teams and has no table; only the lettered
    groups do, and the archive records exactly which of those existed.
    """
    path = ARCHIVE / f"{season}.json"
    if not path.exists():
        return []
    seen = set(json.loads(path.read_text("utf-8")).values())
    return sorted(d for d in seen if re.fullmatch(r"\d+-[a-z]", d))


def probe(season: str, div: str, pause: float) -> dict | None:
    """competition/year/season ids, read off the division page's own AJAX link."""
    html = S.get(f"{S.BASE}/souteze/{season}/{div}/")
    time.sleep(pause)
    m = re.search(r'data-url="[^"]*(cmd=tables[^"]*type=final)"', html)
    if not m:
        return None
    q = dict(p.split("=", 1) for p in m.group(1).split("&") if "=" in p)
    return {k: q[k] for k in ("competition", "year", "season") if k in q}


def table(season: str, div: str, ids: dict, pause: float) -> list:
    """One division's final standing: place, team, played, W, D, L, score, points."""
    lvl, letter = div.split("-")
    q = (f"cmd=tables&competition={ids['competition']}&year={ids['year']}"
         f"&season={ids['season']}&league={lvl}"
         f"&group_id={ord(letter) - 96}&type=final")
    body = S.get(f"{S.BASE}/souteze/{season}/{div}/?{q}")
    time.sleep(pause)
    # Some of these AJAX commands answer with the fragment, others wrap it in
    # {"html": ...}. Which one is not a property of the command, so ask the body.
    html = json.loads(body).get("html", "") if body.lstrip().startswith("{") else body
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        link = re.search(r'href="/souteze/[^"]*/tymy/([^"/]+)/"', row)
        if not link:
            continue                       # the heading row
        cells = [S.strip_tags(c) for c in
                 re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        nums = [c for c in cells if re.fullmatch(r"-?\d+|\d+:\d+|\d+\.", c)]
        if len(nums) < 6:
            continue
        place = int(nums[0].rstrip("."))
        rows.append([place, link.group(1)] + nums[1:])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", help="just this one")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("--redo", action="store_true", help="re-read seasons already done")
    args = ap.parse_args()

    seasons = ([args.season] if args.season
               else newest_first(p.stem for p in ARCHIVE.glob("*.json")))
    OUT.mkdir(parents=True, exist_ok=True)
    done = teams = 0
    for season in seasons:
        path = OUT / f"{season}.json"
        if path.exists() and not args.redo:
            continue
        divs = divisions(season)
        if not divs:
            print(f"  {season}: no divisions in the archive", file=sys.stderr)
            continue
        try:
            ids = probe(season, divs[0], args.pause)
        except Exception as e:                        # noqa: BLE001
            print(f"  {season}: {e}", file=sys.stderr)
            continue
        if not ids:
            print(f"  {season}: no table link on {divs[0]}", file=sys.stderr)
            continue
        out = {}
        for d in divs:
            try:
                rows = table(season, d, ids, args.pause)
            except Exception as e:                    # noqa: BLE001
                print(f"    {season}/{d}: {e}", file=sys.stderr)
                continue
            if rows:
                out[d] = rows
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
        done += 1
        teams += sum(len(v) for v in out.values())
        print(f"  {season:34s} {len(out):2d}/{len(divs)} divisions, "
              f"{sum(len(v) for v in out.values())} places", file=sys.stderr)

    files = sorted(OUT.glob("*.json"))
    print(f"\n-> {OUT}: {len(files)} seasons, "
          f"{sum(p.stat().st_size for p in files)/1e6:.1f} MB", file=sys.stderr)


if __name__ == "__main__":
    main()
