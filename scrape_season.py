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
# The veteran leagues play the same grounds, so they cost only their fixtures.
# Futsal is left out: it is played indoors, in halls no orthophoto can measure.
ALSO = ("2026-veteranska-liga-podzim",
        "2026-superveteranska-liga-podzim",
        "2026-ultraveteranska-liga-podzim")


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


def dress_colours(season: str, division: str) -> dict[str, str]:
    """Team -> jersey colour, from a division's `dresy` page.

    One table, `Tym | Barva dresu`, in the league's own words: "bila, cerna",
    "modro-zluta", "tmave modra". Kept as written and parsed for display later,
    because the wording is the thing a referee reads off the team sheet.
    """
    html = S.get(f"{BASE}/souteze/{season}/{division}/dresy/")
    out = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = [S.strip_tags(c) for c in
                 re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        cells = [c for c in cells if c]
        if len(cells) >= 2 and cells[0].lower() != "tým":
            out[S.slug(cells[0])] = cells[1]
    return out


def add_colours(pause: float) -> None:
    """Fold jersey colours into an existing data/season.json."""
    path = DATA / "season.json"
    data = json.loads(path.read_text("utf-8"))
    by_div: dict[tuple[str, str], dict] = {}
    hit = 0
    for t in data["teams"]:
        key = (t.get("comp", SEASON), t["division"])
        if key not in by_div:
            try:
                by_div[key] = dress_colours(*key)
            except Exception as e:                   # noqa: BLE001
                print(f"  {key}: {e}", file=sys.stderr)
                by_div[key] = {}
            time.sleep(pause)
        c = by_div[key].get(S.slug(t["name"]))
        if c:
            t["colours"] = c
            hit += 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    print(f"-> {path}: colours for {hit} of {len(data['teams'])} teams", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=SEASON)
    ap.add_argument("--pause", type=float, default=0.4, help="seconds between requests")
    ap.add_argument("--limit", type=int, help="stop after N teams (for a dry run)")
    ap.add_argument("--no-veterans", action="store_true",
                    help="only the main league, skip the veteran competitions")
    ap.add_argument("--colours-only", action="store_true",
                    help="only refresh jersey colours in an existing season.json")
    args = ap.parse_args()

    if args.colours_only:
        add_colours(args.pause)
        return

    comps = [args.season] + ([] if args.no_veterans else list(ALSO))
    seen_teams: dict[tuple[str, str], dict] = {}
    for comp in comps:
        divisions = division_slugs(comp)
        print(f"{comp}: {len(divisions)} division pages", file=sys.stderr)
        for i, div in enumerate(divisions, 1):
            try:
                urls = team_urls(comp, div)
            except requests.HTTPError as e:
                print(f"  {div}: {e}", file=sys.stderr)
                continue
            for url, slug in urls:
                seen_teams.setdefault((comp, slug),
                                      {"slug": slug, "url": url, "division": div,
                                       "comp": comp})
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

    out = {"season": args.season, "competitions": comps,
           "source": f"{BASE}/souteze/{args.season}/",
           "teams": sorted(teams, key=lambda t: (S.slug(t["name"]), t["comp"]))}
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
