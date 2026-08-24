#!/usr/bin/env python3
"""Scrape every team's fixtures for one PSMF season -> data/season.json.

`scrape_psmf.py` fetches one team, which is what our own table needs. This
fetches the lot, so the published page can answer for any team in the league.

The division pages carry only a window of the schedule, not the whole season,
so this walks division -> team and reads each team's own page. That is one
request per team, around 700 of them, which is why it runs sequentially with a
pause and identifies itself. Run it rarely -- fixtures change far more slowly
than once a day.

    ./.venv/bin/python scrape_season.py                    # current season
    ./.venv/bin/python scrape_season.py --season 2026-hanspaulska-liga-podzim
"""
from __future__ import annotations
import argparse, json, re, sys, time
from pathlib import Path

import requests

import scrape_psmf as S

BASE = S.BASE
DATA = Path(__file__).parent / "data"
SEASON = "2026-hanspaulska-liga-podzim"


def division_slugs(season: str) -> list[str]:
    """Division pages under a season. The bare group headers ('1', '2') list no
    teams of their own, but cost nothing to visit and are skipped by the team
    walk below."""
    html = S.get(f"{BASE}/souteze/{season}/")
    slugs = re.findall(rf'href="/souteze/{re.escape(season)}/([^"/]+)/"', html)
    return sorted(set(slugs))


def team_urls(season: str, division: str) -> list[tuple[str, str]]:
    html = S.get(f"{BASE}/souteze/{season}/{division}/")
    found = re.findall(
        rf'href="(/souteze/{re.escape(season)}/{re.escape(division)}/tymy/([^"/]+)/)"', html)
    return sorted(set(found))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=SEASON)
    ap.add_argument("--pause", type=float, default=0.4, help="seconds between requests")
    ap.add_argument("--limit", type=int, help="stop after N teams (for a dry run)")
    args = ap.parse_args()

    divisions = division_slugs(args.season)
    print(f"{args.season}: {len(divisions)} division pages", file=sys.stderr)

    seen_teams: dict[str, dict] = {}
    for i, div in enumerate(divisions, 1):
        try:
            urls = team_urls(args.season, div)
        except requests.HTTPError as e:
            print(f"  {div}: {e}", file=sys.stderr)
            continue
        for url, slug in urls:
            seen_teams.setdefault(slug, {"slug": slug, "url": url, "division": div})
        print(f"  [{i}/{len(divisions)}] {div}: {len(urls)} teams "
              f"({len(seen_teams)} total)", file=sys.stderr)
        time.sleep(args.pause)

    teams, failed = [], []
    items = list(seen_teams.values())[: args.limit]
    for i, t in enumerate(items, 1):
        try:
            name, fixtures = S.parse_fixtures(S.get(BASE + t["url"]))
        except Exception as e:                       # noqa: BLE001 - report and go on
            failed.append((t["slug"], str(e)))
            print(f"  [{i}/{len(items)}] {t['slug']}: FAILED {e}", file=sys.stderr)
            continue
        teams.append({**t, "name": name,
                      "fixtures": [{k: f[k] for k in
                                    ("round", "date", "time", "venue_code",
                                     "opponent", "home")}
                                   for f in fixtures]})
        if i % 25 == 0 or i == len(items):
            print(f"  [{i}/{len(items)}] {name}: {len(fixtures)} fixtures", file=sys.stderr)
        time.sleep(args.pause)

    out = {"season": args.season,
           "source": f"{BASE}/souteze/{args.season}/",
           "teams": sorted(teams, key=lambda t: S.slug(t["name"]))}
    path = DATA / "season.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    codes = {f["venue_code"] for t in teams for f in t["fixtures"]}
    print(f"\n-> {path}  {path.stat().st_size/1e6:.2f} MB\n"
          f"   {len(teams)} teams, "
          f"{sum(len(t['fixtures']) for t in teams)} fixtures, {len(codes)} venue codes",
          file=sys.stderr)
    if failed:
        print(f"   {len(failed)} teams failed: {failed[:5]}", file=sys.stderr)


if __name__ == "__main__":
    main()
