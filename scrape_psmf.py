#!/usr/bin/env python3
"""Scrape PSMF fixtures for a team + the PSMF venue (hriste) directory.

Outputs data/fixtures.json and data/venues.json.
"""
import argparse, json, re, sys, unicodedata
from pathlib import Path
from urllib.parse import unquote
import requests

BASE = "https://www.psmf.cz"
HDRS = {"User-Agent": "psmf-pitch-measure/1.0 (personal league prep)"}
DATA = Path(__file__).parent / "data"


def get(url: str) -> str:
    r = requests.get(url, headers=HDRS, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&quot;", '"').replace("&#39;", "'")
          .replace("&lt;", "<").replace("&gt;", ">"))
    return re.sub(r"[ \t]+", " ", s).strip()


def parse_venues(html: str) -> dict:
    """The /hriste/ page is one big table: name | <a name=CODE href=mapy.cz?q=GPS:lat lon> | address+notes."""
    venues = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)
        if len(cells) < 3:
            continue
        name, mid, info = cells[0], cells[1], cells[2]
        for anchor in re.finditer(
            r'<a\s+name="([^"]+)"\s+href="([^"]*mapy\.cz[^"]*)"', mid, re.I
        ):
            code, href = anchor.group(1).strip(), unquote(anchor.group(2))
            coords = re.search(r"(\d{2}\.\d+)\D+(\d{2}\.\d+)", href)
            if not coords:
                continue
            lat, lon = float(coords.group(1)), float(coords.group(2))
            text = strip_tags(info)
            venues[code] = {
                "code": code,
                "name": strip_tags(name),
                "lat": lat,
                "lon": lon,
                "address": text.split("\n")[0].strip(),
                "notes": text,
                "surface": classify_surface(text),
                "footwear": parse_footwear(text),
            }
    return venues


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s


def classify_surface(text: str) -> str:
    t = norm(text)
    if "umela" in t or "umt" in t:
        return "artificial"
    if "skvara" in t or "antuka" in t:
        return "gravel/clay"
    if "prirodni" in t or "trava" in t:
        return "grass"
    return "unknown"


def slug(s: str) -> str:
    """Comparison key for team names: no diacritics, no punctuation."""
    return re.sub(r"[^a-z0-9]+", "", norm(s))


def parse_footwear(notes: str) -> dict:
    """Read the venue's `Obuv:` line into a boot rule.

    PSMF writes it two ways: "kopacky povoleny i s lisovanymi koliky" (studs of
    any kind fine) or a list of what is allowed followed by what is "zakazany".
    Both mention lisovky, so presence alone says nothing -- what decides it is
    whether lisovky sits nearer the permission or the prohibition. Same for AG,
    which Mecholupy bans alongside lisovky while others allow.
    """
    line = next((l.strip() for l in notes.split("\n")
                 if norm(l).startswith("obuv")), "")
    if not line:
        return {"text": "", "lisovky": "unknown", "ag": "unknown", "summary": ""}
    t = unicodedata.normalize("NFKD", line.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))

    def verdict(term):
        hit = re.search(term, t)
        if not hit:
            return "unknown"
        here = hit.start()
        allow = [m.start() for m in re.finditer(r"povolen", t)]
        deny = [m.start() for m in re.finditer(r"zakazan", t)]
        if not deny:
            return "allowed" if allow else "unknown"
        if not allow:
            return "forbidden"
        return ("forbidden" if min(abs(here - d) for d in deny)
                <= min(abs(here - a) for a in allow) else "allowed")

    lisovky, ag = verdict(r"lisov"), verdict(r"\bag\b")
    if lisovky == "allowed":
        summary = "lisovky OK"
    elif ag == "forbidden":
        summary = "turf / indoor only"
    elif ag == "allowed":
        summary = "AG or turf, no lisovky"
    else:
        summary = "no lisovky"
    return {"text": line, "lisovky": lisovky, "ag": ag, "summary": summary}


def parse_fixtures(html: str) -> tuple[str, list]:
    team = strip_tags(re.search(r'class="component__title">(.*?)</h1>', html, re.S).group(1))
    tkey = slug(team)
    fixtures, seen = [], set()
    # rows look like: ... <a href="/souteze/.../tymy/<slug>/">Opponent</a> ... <a href="/hriste/#CODE">CODE</a>
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        code_m = re.search(r'href="/hriste/#([A-Z0-9]+)"', row)
        if not code_m:
            continue
        cells = [strip_tags(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        opp_links = re.findall(r'href="(/souteze/[^"]*/tymy/[^"]+/)"[^>]*>(.*?)</a>', row, re.S)
        date = next((c for c in cells if re.search(r"\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4}", c)), "")
        time = next((c for c in cells if re.fullmatch(r"\d{1,2}[:.]\d{2}", c.strip())), "")
        opp_names = [strip_tags(t) for _, t in opp_links]
        if tkey not in {slug(o) for o in opp_names}:
            continue  # other teams' matches also listed on this venue/day
        rnd = next((int(c.rstrip(".")) for c in cells if re.fullmatch(r"\d{1,2}\.", c.strip())), None)
        # A played match ends the row with its score, home:away. Taken from the
        # end rather than by pattern: "1:10" is indistinguishable from a kick-off
        # time, and the time always comes first in the row.
        score = cells[-1].strip() if cells and re.fullmatch(
            r"\d{1,2}:\d{1,2}", cells[-1].strip()) else ""
        key = (date, time, code_m.group(1))
        if key in seen:
            continue
        seen.add(key)
        fixtures.append({
            "round": rnd if rnd is not None else len(fixtures) + 1,
            "date": date,
            "time": time,
            "venue_code": code_m.group(1),
            "opponents": opp_names,
            "opponent": next((o for o in opp_names if slug(o) != tkey), ""),
            "home": bool(opp_names) and slug(opp_names[0]) == tkey,
            "score": score,
            "raw_cells": cells,
        })
    return team, fixtures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("team_url", nargs="?",
        default=f"{BASE}/souteze/2026-hanspaulska-liga-podzim/7-g/tymy/zde-je-misto/")
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)
    team_html = get(args.team_url)
    team, fixtures = parse_fixtures(team_html)
    venues = parse_venues(get(f"{BASE}/hriste/"))

    used = [f["venue_code"] for f in fixtures]
    missing = sorted({c for c in used if c not in venues})
    if missing:
        print(f"WARNING: no venue-directory entry for {missing}", file=sys.stderr)

    (DATA / "fixtures.json").write_text(json.dumps(
        {"team": team, "url": args.team_url, "fixtures": fixtures}, ensure_ascii=False, indent=2), "utf-8")
    (DATA / "venues.json").write_text(json.dumps(venues, ensure_ascii=False, indent=2), "utf-8")
    print(f"team={team!r}  fixtures={len(fixtures)}  venue_dir={len(venues)}  "
          f"distinct_venues={len(set(used))}")
    for f in fixtures:
        v = venues.get(f["venue_code"], {})
        print(f'  R{f["round"]:>2} {f["date"]:<16} {f["time"]:<6} {f["venue_code"]:<6} '
              f'{v.get("name","?"):<28} {" vs ".join(f["opponents"])}')


if __name__ == "__main__":
    main()
