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
import numpy as np

import measure_pitches as M

ROOT = Path(__file__).parent
ms = json.loads((ROOT / "out/measurements.json").read_text("utf-8"))
ov = json.loads((ROOT / "data/overrides.json").read_text("utf-8"))
venues = json.loads((ROOT / "data/venues.json").read_text("utf-8"))
season_path = ROOT / "data/season.json"
season = json.loads(season_path.read_text("utf-8")) if season_path.exists() else {"teams": []}

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
    pts = np.array(c["play_rect_px"], np.float32)
    lon, lat = M.px_to_lonlat((pts[:, 0].mean(), pts[:, 1].mean()), m["geo"])
    V[code] = {
        "code": code, "venue": v.get("name", code), "l": l, "w": w, "area": l * w,
        "exact": f'{c["play_l_m"]} x {c["play_w_m"]}',
        "kind": c.get("kind", ""), "capture": m.get("geo", {}).get("capture", "?"),
        "boots": label, "bootsClass": cls, "bootsText": text,
        "lat": round(lat, 6), "lon": round(lon, 6),
        "note": (ov.get(code) or {}).get("note", ""),
        "img": jpeg_uri(ROOT / f"out/{code}_pitch1.png"),
    }
    if v.get("training"):
        V.pop(code)          # measured for our own comparison, not a PSMF ground

play = V
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

# No team is selected on load. The page is for the league, so it opens on the
# whole directory rather than on whoever built it.
blob = json.dumps({"venues": V, "teams": teams},
                  ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")

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
.grid { display:grid; gap:20px; grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
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
.meta { margin:2px 0 0; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.pin { display:inline-flex; vertical-align:-3px; margin-left:5px; color:var(--faint); }
.pin:hover { color:var(--accent); }
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

function mapLink(v) {
  const t = `Otevřít ${esc(v.venue)} v mapě`;
  return `<a class="pin" href="${mapHref(v)}" target="_blank" rel="noopener noreferrer"
    title="${t}" aria-label="${t}">${PIN}</a>`;
}

function card(v, sub) {
  const kind = v.kind.indexOf('section') === 0
    ? `hřiště ${v.kind.split('_')[1]} ze ${v.kind.split('_')[3]}` : 'celé hřiště';
  return `<article class="card">
    <figure><img src="${v.img}" alt="Ortofoto hřiště ${esc(v.venue)} se zakresleným obdélníkem" loading="lazy"></figure>
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

function renderTeam(i) {
  const host = document.getElementById('team');
  const t = i == null ? null : D.teams[i];
  document.getElementById('all-head').textContent =
    t ? 'Všechna hřiště v adresáři · od největšího' : 'Všechna hřiště · od největšího';
  if (!t) { host.innerHTML = ''; return; }

  const rows = t.fx.map(f => {
    const v = D.venues[f.c];
    return `<tr>
      <td class="num">${f.r}</td>
      <td class="date">${esc(f.d)}<span class="t">${esc(f.t)}</span></td>
      <td>${esc(f.o)}</td>
      <td>${v ? esc(v.venue) : ''} <code>${esc(f.c)}</code></td>
      <td class="dim">${v ? v.l + ' &times; ' + v.w : '<span class="conf">nezměřeno</span>'}</td>
      <td class="num">${v ? v.area : ''}</td>
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

  const areas = codes.map(c => D.venues[c].area);
  const missing = t.fx.filter(f => !D.venues[f.c]).length;
  const ratio = areas.length ? (Math.max(...areas) / Math.min(...areas)).toFixed(1) + '×' : '—';
  host.innerHTML = `
    <hr class="rule">
    <div class="stats">
      <div class="stat"><b>${t.fx.length}</b><span>Zápasů</span></div>
      <div class="stat"><b>${codes.length}</b><span>Různých hřišť</span></div>
      <div class="stat"><b>${areas.length ? Math.min(...areas) + ' m²' : '—'}</b><span>Nejmenší</span></div>
      <div class="stat"><b>${areas.length ? Math.max(...areas) + ' m²' : '—'}</b><span>Největší</span></div>
      <div class="stat"><b>${ratio}</b><span>Největší ÷ nejmenší</span></div>
    </div>
    <hr class="rule">
    <h2>${esc(t.name)} &middot; ${esc(t.div)} &middot; rozpis zápasů</h2>
    <div class="scroll"><table>
      <thead><tr><th>K</th><th>Datum</th><th>Soupeř</th><th>Hřiště</th>
      <th>Rozměr</th><th>Plocha m&sup2;</th><th>Obuv</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    ${missing ? `<p class="nt">${missing}&times; se hraje na hřišti bez měření — hala, nebo kód, který adresář PSMF nevede.</p>` : ''}
    <hr class="rule">
    <h2>Hřiště tohoto týmu &middot; od největšího</h2>
    <div class="grid">${cards || '<p class="empty">Pro tento tým nejsou změřená hřiště.</p>'}</div>`;
}

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
const keys = D.teams.map(t => fold(label(t)));

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
  setParam(D.teams[i]);
  closeList();
  showClear();
}

clearBtn.addEventListener('click', () => {
  input.value = '';
  renderTeam(null);
  setParam(null);
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
  if (!input.value.trim()) { renderTeam(null); setParam(null); closeList(); return; }
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
// page. Written with replaceState: nothing here should become a back step.
function setParam(t) {
  try {
    const u = new URL(location.href);
    if (t) u.searchParams.set('team', label(t)); else u.searchParams.delete('team');
    history.replaceState(null, '', u);
  } catch (e) { /* file:// and the like */ }
}

renderAll();
let start = null;
try { start = lookup(new URLSearchParams(location.search).get('team') || ''); } catch (e) { }
if (start !== null) { input.value = label(D.teams[start]); renderTeam(start); }
else renderTeam(null);
showClear();
"""

html = f"""<title>Rozměry hřišť &mdash; PSMF Hanspaulsk&aacute; liga</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{CSS}</style>
<script>{EARLY_JS}</script>

<div class="wrap">
<div class="top">
  <p class="eyebrow">PSMF &middot; Hanspaulsk&aacute; liga &middot; {season.get("season", "").replace("-", " ")}</p>
  <button type="button" class="theme" id="theme" aria-live="polite">motiv</button>
</div>
<h1>Všechna hřiště v lize, změřená ze vzduchu</h1>
<p class="lede">Rozměry vyznačených hřišť na všech {len(play)} hřištích z adresáře
PSMF, proměřené podle čar v ortofotomapě IPR Praha s rozlišením 5&nbsp;cm na pixel.
Vyberte tým a uvidíte, na čem letos hraje.</p>

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
  <span class="who">{len(teams)} týmů &middot; odkaz na vybraný tým lze sdílet</span>
</div>
<noscript><p class="lede" style="margin-top:18px">Výběr týmu probíhá v prohlížeči,
takže tahle část potřebuje JavaScript. Samotná měření jsou v souboru
<code>out/measurements.json</code> v repozitáři.</p></noscript>

<div id="team"></div>

<hr class="rule">
<h2 id="all-head">Všechna hřiště &middot; od největšího</h2>
<p class="lede" style="margin-bottom:18px">{len(play)} hřišť. Nejmenší z nich,
{smallest["venue"]}, by se do největšího ({largest["venue"]})
vešlo {largest["area"] / smallest["area"]:.1f}&times;.</p>
<div class="grid" id="all"></div>

<footer>
Podklad: ortofotomapa IPR Praha, 0,05&nbsp;m/px, EPSG:5514 (S-JTSK); snímkování vybráno
zvlášť pro každé hřiště. Rozpisy a souřadnice hřišť z <a href="https://www.psmf.cz/">psmf.cz</a>.
Každý obdélník je proložení skutečných čar a lze ho porovnat s fotkou vedle něj.
Vygenerováno {date.today().strftime("%-d. %-m. %Y")}.
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
