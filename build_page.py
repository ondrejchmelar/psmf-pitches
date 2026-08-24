#!/usr/bin/env python3
"""Build the self-contained HTML report -> docs/index.html.

The page used to be our eleven fixtures, rendered server-side. It now carries
every venue in the PSMF directory and every team's fixture list, and picks the
team in the browser. Two consequences worth knowing before editing:

* Everything renders client-side, from one JSON blob. Rendering the cards here
  instead would repeat each venue's data-URI image wherever it appears -- once
  in the league grid, again for every team that plays there -- and this file is
  mostly image bytes. In the blob each image is one string, used as often as
  needed.
* docs/ is what GitHub Pages serves, so the page is written straight there. It
  carries its imagery inline, so index.html on its own is the whole site.
"""
import base64, json
from datetime import date
from pathlib import Path

import cv2

ROOT = Path(__file__).parent
ms = json.loads((ROOT / "out/measurements.json").read_text("utf-8"))
ov = json.loads((ROOT / "data/overrides.json").read_text("utf-8"))
venues = json.loads((ROOT / "data/venues.json").read_text("utf-8"))
season_path = ROOT / "data/season.json"
season = json.loads(season_path.read_text("utf-8")) if season_path.exists() else {"teams": []}
ours = json.loads((ROOT / "data/fixtures.json").read_text("utf-8")).get("team", "")

IMG_W, IMG_Q = 720, 72        # 40-odd venues ride in this file; keep each light


def jpeg_uri(path, width=IMG_W, q=IMG_Q):
    img = cv2.imread(str(path))
    if img is None:
        return ""
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def boots(code):
    """Short label plus the venue's own wording, as make_table.py does it."""
    fw = (venues.get(code, {}) or {}).get("footwear") or {}
    lis, ag = fw.get("lisovky", "unknown"), fw.get("ag", "unknown")
    if lis == "allowed":
        label = "lisovky OK"
    elif lis == "forbidden":
        label = "turf only" if ag == "forbidden" else "no lisovky"
    else:
        label = ""
    return label, fw.get("text", "")


# --------------------------------------------------------------------- venues
V = {}
for code, m in ms.items():
    if code.startswith("_"):
        continue
    c = (m.get("candidates") or [None])[0]
    if not c:
        continue
    v = m.get("venue", {})
    edges = c.get("edge_strength") or []
    label, text = boots(code)
    l, w = round(c["play_l_m"]), round(c["play_w_m"])
    V[code] = {
        "code": code, "venue": v.get("name", code), "l": l, "w": w, "area": l * w,
        "exact": f'{c["play_l_m"]} x {c["play_w_m"]}',
        "kind": c.get("kind", ""), "capture": m.get("geo", {}).get("capture", "?"),
        # every edge backed by a clear line -> trust it; a weak edge means the
        # marking is faint there and the number is a best fit, not a reading
        "conf": ("high" if edges and min(edges) >= 4
                 else "medium" if edges and min(edges) >= 2 else "low"),
        "boots": label, "bootsText": text,
        "note": (ov.get(code) or {}).get("note", ""),
        "training": bool(v.get("training")),
        "img": jpeg_uri(ROOT / f"out/{code}_pitch1.png"),
    }

play = {k: x for k, x in V.items() if not x["training"]}
smallest = min(play.values(), key=lambda x: x["area"])
largest = max(play.values(), key=lambda x: x["area"])

# ---------------------------------------------------------------------- teams
teams = []
for t in season.get("teams", []):
    fx = [{"r": f["round"], "d": f["date"], "t": f["time"], "c": f["venue_code"],
           "o": f["opponent"], "h": f["home"]} for f in t["fixtures"]]
    if fx:
        teams.append({"name": t["name"], "div": t["division"].upper(), "fx": fx})
teams.sort(key=lambda t: (t["name"].lower(), t["div"]))
default = next((i for i, t in enumerate(teams) if t["name"] == ours), 0)

blob = json.dumps({"venues": V, "teams": teams, "default": default},
                  ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")

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
.wrap { max-width:1120px; margin:0 auto; padding:clamp(28px,5vw,64px) clamp(18px,4vw,36px) 96px; }
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
.stat b { display:block; font:600 26px/1.1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; letter-spacing:-.02em; }
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
.pick .who { font-size:13px; color:var(--faint); }
.scroll { overflow-x:auto; border:1px solid var(--rule); border-radius:3px; background:var(--surface); }
table { border-collapse:collapse; width:100%; min-width:720px; font-size:14.5px; }
th { text-align:left; font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  letter-spacing:.12em; text-transform:uppercase; color:var(--faint);
  padding:13px 14px; border-bottom:1px solid var(--rule); white-space:nowrap; }
td { padding:11px 14px; border-bottom:1px solid var(--rule); vertical-align:baseline; }
tbody tr:last-child td { border-bottom:0; }
tbody tr:hover { background:var(--sunk); }
.num, .dim { font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; text-align:right; white-space:nowrap; }
.dim { text-align:left; font-weight:600; }
.date { white-space:nowrap; }
.date .t { color:var(--faint); margin-left:7px; font-size:13px; }
code { font:600 11.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace; color:var(--muted);
  background:var(--sunk); padding:2px 5px; border-radius:2px; }
.grid { display:grid; gap:20px; grid-template-columns:repeat(auto-fill,minmax(340px,1fr));
  align-items:start; }
.card { background:var(--surface); border:1px solid var(--rule); border-radius:3px;
  overflow:hidden; box-shadow:var(--shadow); display:flex; flex-direction:column; }
.card figure { margin:0; background:var(--sunk); border-bottom:1px solid var(--rule); }
.card img { display:block; width:100%; height:auto; }
.card .body { padding:16px 18px 18px; display:flex; flex-direction:column; gap:9px; }
.ch { display:flex; justify-content:space-between; align-items:baseline; gap:10px; flex-wrap:wrap; }
.ch h3 { margin:0; font-size:15.5px; font-weight:640; letter-spacing:-.01em; }
.ch .d { margin:0; font:600 15px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; color:var(--accent); white-space:nowrap; }
.bar { position:relative; height:20px; background:var(--sunk); border-radius:2px;
  display:flex; align-items:center; }
.bar i { position:absolute; inset:0 auto 0 0; background:var(--mark); opacity:.42; border-radius:2px; }
.bar span { position:relative; margin-left:8px; font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; color:var(--ink); }
.fx { margin:4px 0 0; font-size:12.5px; color:var(--muted); }
.nt { margin:2px 0 0; font-size:12px; line-height:1.45; color:var(--faint); }
.boots { font:600 10.5px/17px ui-monospace,SFMono-Regular,Menlo,monospace;
  letter-spacing:.03em; padding:0 6px; border-radius:2px; border:1px solid currentColor;
  white-space:nowrap; }
.boots.lisovky { color:var(--home); }
.boots.no { color:var(--mark); }
.boots.turf { color:var(--away); }
.conf { font:600 10px/16px ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.06em;
  text-transform:uppercase; color:var(--faint); }
.conf.low { color:var(--away); }
.empty { color:var(--faint); font-size:14px; }
footer { margin-top:46px; padding-top:20px; border-top:1px solid var(--rule);
  font-size:12.5px; color:var(--faint); }
a { color:var(--accent); }
a:focus-visible, tr:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
@media (prefers-reduced-motion:reduce) { * { animation:none!important; transition:none!important; } }
"""

JS = r"""
const D = JSON.parse(document.getElementById('psmf-data').textContent);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const playable = Object.values(D.venues).filter(v => !v.training);
const mx = Math.max(...playable.map(v => v.area));

function card(v, sub) {
  return `<article class="card">
    <figure><img src="${v.img}" alt="Orthophoto of ${esc(v.venue)} with the measured rectangle drawn on" loading="lazy"></figure>
    <div class="body">
      <header class="ch">
        <h3>${esc(v.venue)} <code>${esc(v.code)}</code></h3>
        <p class="d">${v.l} &times; ${v.w} m</p>
      </header>
      <div class="bar"><i style="width:${(100 * v.area / mx).toFixed(1)}%"></i><span>${v.area} m&sup2;</span></div>
      ${sub || ''}
      ${v.bootsText ? `<p class="nt">${esc(v.bootsText)}</p>` : ''}
    </div></article>`;
}

function renderTeam(i) {
  const host = document.getElementById('team');
  const t = D.teams[i];
  if (!t) { host.innerHTML = ''; return; }

  const rows = t.fx.map(f => {
    const v = D.venues[f.c];
    return `<tr>
      <td class="num">${f.r}</td>
      <td class="date">${esc(f.d)}<span class="t">${esc(f.t)}</span></td>
      <td>${esc(f.o)}</td>
      <td>${v ? esc(v.venue) : ''} <code>${esc(f.c)}</code></td>
      <td class="dim">${v ? v.l + ' &times; ' + v.w : '<span class="conf">not measured</span>'}</td>
      <td class="num">${v ? v.area : ''}</td>
      <td>${v && v.boots ? `<span class="boots ${v.boots.split(' ')[0]}">${esc(v.boots)}</span>` : ''}</td>
    </tr>`;
  }).join('');

  const codes = [];
  t.fx.forEach(f => { if (D.venues[f.c] && !codes.includes(f.c)) codes.push(f.c); });
  codes.sort((a, b) => D.venues[b].area - D.venues[a].area);
  const cards = codes.map(c => {
    const at = t.fx.filter(f => f.c === c)
      .map(f => `R${f.r} ${f.h ? 'vs' : 'at'} ${esc(f.o)}`).join(', ');
    return card(D.venues[c], `<p class="fx">${at}</p>`);
  }).join('');

  const areas = codes.map(c => D.venues[c].area);
  const missing = t.fx.filter(f => !D.venues[f.c]).length;
  const ratio = areas.length ? (Math.max(...areas) / Math.min(...areas)).toFixed(1) + '×' : '—';
  host.innerHTML = `
    <hr class="rule">
    <div class="stats">
      <div class="stat"><b>${t.fx.length}</b><span>Fixtures</span></div>
      <div class="stat"><b>${codes.length}</b><span>Distinct pitches</span></div>
      <div class="stat"><b>${areas.length ? Math.min(...areas) + ' m²' : '—'}</b><span>Smallest</span></div>
      <div class="stat"><b>${areas.length ? Math.max(...areas) + ' m²' : '—'}</b><span>Largest</span></div>
      <div class="stat"><b>${ratio}</b><span>Largest ÷ smallest</span></div>
    </div>
    <hr class="rule">
    <h2>${esc(t.name)} &middot; ${esc(t.div)} &middot; season fixtures</h2>
    <div class="scroll"><table>
      <thead><tr><th>R</th><th>Date</th><th>Opponent</th><th>Venue</th>
      <th>Pitch size</th><th>Area m&sup2;</th><th>Boots</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    ${missing ? `<p class="nt">${missing} fixture${missing > 1 ? 's' : ''} at a ground with no measurement — an indoor hall, or a code the PSMF ground directory does not carry.</p>` : ''}
    <hr class="rule">
    <h2>Their pitches &middot; largest to smallest</h2>
    <div class="grid">${cards || '<p class="empty">No measured pitches for this team.</p>'}</div>`;
}

function renderAll() {
  document.getElementById('all').innerHTML =
    playable.slice().sort((a, b) => b.area - a.area).map(v => card(v,
      `<p class="fx">${v.kind.indexOf('section') === 0
        ? esc(v.kind.replace(/_/g, ' ')) : 'Whole pitch'} &middot; ${esc(v.exact)} m<span
        class="conf ${v.conf}"> &middot; ${v.conf} confidence</span></p>`)).join('');
  const t = Object.values(D.venues).find(v => v.training);
  if (t) document.getElementById('training').innerHTML =
    card(t, '<p class="fx">Training pitch &mdash; not a PSMF venue</p>');
}

const input = document.getElementById('team-input');
const label = t => `${t.name} (${t.div})`;
const key = s => s.trim().toLowerCase();
// Match the datalist label, but also a bare team name typed without its
// division: several teams share a name across divisions, so that only counts
// when it picks out exactly one.
const byLabel = new Map(D.teams.map((t, i) => [key(label(t)), i]));
const byBare = new Map();
D.teams.forEach((t, i) => {
  const k = key(t.name);
  byBare.set(k, byBare.has(k) ? null : i);
});
document.getElementById('teams').innerHTML =
  D.teams.map(t => `<option value="${esc(label(t))}"></option>`).join('');
input.addEventListener('input', () => {
  const k = key(input.value);
  const i = byLabel.has(k) ? byLabel.get(k) : byBare.get(k);
  if (i !== undefined && i !== null) renderTeam(i);
});
renderAll();
if (D.teams.length) {
  input.value = label(D.teams[D.default]);
  renderTeam(D.default);
}
"""

html = f"""<title>Pitch dimensions &mdash; PSMF Hanspaulsk&aacute; liga</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{CSS}</style>

<div class="wrap">
<p class="eyebrow">PSMF &middot; Hanspaulsk&aacute; liga &middot; {season.get("season", "").replace("-", " ")}</p>
<h1>Every pitch in the league, measured from the air</h1>
<p class="lede">Painted pitch dimensions for all {len(play)} grounds in the PSMF
directory, fitted to the markings in IPR Praha orthophoto imagery at 5&nbsp;cm per
pixel. Pick a team to see the pitches it plays on this season.</p>

<hr class="rule">
<div class="pick">
  <label for="team-input">Team</label>
  <input id="team-input" list="teams" placeholder="Start typing a team name&hellip;"
         autocomplete="off" spellcheck="false">
  <datalist id="teams"></datalist>
  <span class="who">{len(teams)} teams</span>
</div>
<noscript><p class="lede" style="margin-top:18px">Picking a team happens in the
browser, so that part needs JavaScript. The measurements themselves are in
<code>out/measurements.json</code> in the repository.</p></noscript>

<div id="team"></div>

<hr class="rule">
<h2>Every pitch in the directory &middot; largest to smallest</h2>
<p class="lede" style="margin-bottom:18px">{len(play)} grounds. {smallest["venue"]}
&mdash; the smallest &mdash; would fit inside {largest["venue"]}
{largest["area"] / smallest["area"]:.1f} times over.</p>
<div class="grid" id="all"></div>

<hr class="rule">
<h2>Our training pitch, for scale</h2>
<div class="grid" id="training"></div>

<footer>
Imagery: IPR Praha orthophoto archive, 0.05&nbsp;m/px, EPSG:5514 (S-JTSK); capture chosen per venue.
Fixtures and venue coordinates scraped from <a href="https://www.psmf.cz/">psmf.cz</a>.
Every rectangle is a fit to the paint and can be checked against the photo beside it;
expect about &plusmn;0.5&nbsp;m where confidence is high.
Generated {date.today().strftime("%-d %B %Y")}.
</footer>
</div>

<script type="application/json" id="psmf-data">{blob}</script>
<script>{JS}</script>
"""

out = ROOT / "docs/index.html"
out.parent.mkdir(exist_ok=True)
(out.parent / ".nojekyll").touch()
out.write_text(html, "utf-8")
print(f"{out}  {out.stat().st_size/1e6:.2f} MB  "
      f"({len(play)} venues, {len(teams)} teams)")
