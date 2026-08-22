#!/usr/bin/env python3
"""Build a self-contained HTML page from the measurements + annotated crops."""
import base64, io, json
from pathlib import Path
import cv2

ROOT = Path(__file__).parent
rows = json.loads((ROOT / "out/table.json").read_text("utf-8"))
ms = json.loads((ROOT / "out/measurements.json").read_text("utf-8"))
ov = json.loads((ROOT / "data/overrides.json").read_text("utf-8"))


def jpeg_uri(path, width=900, q=76):
    img = cv2.imread(str(path))
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


seen, pitches = set(), []
for r in rows:
    if r["code"] in seen:
        continue
    seen.add(r["code"])
    c = ms[r["code"]]["candidates"][0]
    fixtures = [x for x in rows if x["code"] == r["code"]]
    pitches.append({**r, "cand": c, "img": jpeg_uri(ROOT / f'out/{r["code"]}_pitch1.png'),
                    "fixtures": fixtures})
pitches.sort(key=lambda p: -p["area"])
mx = max(p["area"] for p in pitches)

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

trs = []
for r in rows:
    trs.append(f'''<tr>
<td class="num">{r["round"]}</td>
<td class="date">{esc(r["date"])}<span class="t">{esc(r["time"])}</span></td>
<td>{esc(r["opponent"])}</td>
<td>{esc(r["venue"])} <code>{esc(r["code"])}</code></td>
<td class="dim">{r["l"]} &times; {r["w"]}</td>
<td class="num">{r["area"]}</td>
</tr>''')

cards = []
for p in pitches:
    c = p["cand"]
    fx = ", ".join(f'R{f["round"]} {"vs" if f["home"] else "at"} {esc(f["opponent"])}'
                   for f in p["fixtures"])
    cards.append(f'''<article class="card">
  <figure><img src="{p["img"]}" alt="Orthophoto of {esc(p["venue"])} with the measured rectangle drawn on" loading="lazy"></figure>
  <div class="body">
    <header class="ch">
      <h3>{esc(p["venue"])} <code>{esc(p["code"])}</code></h3>
      <p class="d">{p["l"]} &times; {p["w"]} m</p>
    </header>
    <div class="bar"><i style="width:{100*p["area"]/mx:.1f}%"></i><span>{p["area"]} m&sup2;</span></div>
    <p class="fx">{fx}</p>
  </div>
</article>''')

html = f'''<title>Pitch dimensions &mdash; 7-G podzim 2026</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{
  --ground:#F6F7F3; --surface:#FFFFFF; --sunk:#EDEFE8;
  --ink:#161A15; --muted:#5B655A; --faint:#8B948A;
  --rule:#DDE1D7; --accent:#8A6A00; --mark:#E0B400;
  --home:#2F6B4F; --away:#7A4A2C;
  --shadow:0 1px 2px rgba(20,26,18,.05),0 8px 24px -16px rgba(20,26,18,.28);
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --ground:#0F120E; --surface:#171B15; --sunk:#1E231C;
    --ink:#E9EDE5; --muted:#9AA396; --faint:#6E776C;
    --rule:#2A3027; --accent:#E9C34A; --mark:#F2CE55;
    --home:#7BC49B; --away:#DDA277;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 28px -18px rgba(0,0,0,.8);
  }}
}}
:root[data-theme="dark"] {{
  --ground:#0F120E; --surface:#171B15; --sunk:#1E231C;
  --ink:#E9EDE5; --muted:#9AA396; --faint:#6E776C;
  --rule:#2A3027; --accent:#E9C34A; --mark:#F2CE55;
  --home:#7BC49B; --away:#DDA277;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 28px -18px rgba(0,0,0,.8);
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; background:var(--ground); color:var(--ink);
  font:400 16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;
}}
.wrap {{ max-width:1120px; margin:0 auto; padding:clamp(28px,5vw,64px) clamp(18px,4vw,36px) 96px; }}
.eyebrow {{
  font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  letter-spacing:.18em; text-transform:uppercase; color:var(--accent); margin:0 0 14px;
}}
h1 {{ font-size:clamp(30px,5vw,46px); line-height:1.06; letter-spacing:-.022em;
  font-weight:680; margin:0 0 14px; text-wrap:balance; }}
.lede {{ max-width:64ch; color:var(--muted); font-size:17px; margin:0 0 8px; }}
.rule {{ height:1px; background:var(--rule); margin:34px 0 28px; border:0; }}
.stats {{ display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); margin-bottom:8px; }}
.stat {{ background:var(--surface); border:1px solid var(--rule); border-radius:3px; padding:16px 18px; }}
.stat b {{ display:block; font:600 26px/1.1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; letter-spacing:-.02em; }}
.stat span {{ display:block; margin-top:6px; font-size:12px; letter-spacing:.08em;
  text-transform:uppercase; color:var(--faint); }}
h2 {{ font-size:13px; letter-spacing:.14em; text-transform:uppercase; color:var(--faint);
  font-weight:600; margin:0 0 16px; }}
.scroll {{ overflow-x:auto; border:1px solid var(--rule); border-radius:3px; background:var(--surface); }}
table {{ border-collapse:collapse; width:100%; min-width:720px; font-size:14.5px; }}
th {{ text-align:left; font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  letter-spacing:.12em; text-transform:uppercase; color:var(--faint);
  padding:13px 14px; border-bottom:1px solid var(--rule); white-space:nowrap; }}
td {{ padding:11px 14px; border-bottom:1px solid var(--rule); vertical-align:baseline; }}
tbody tr:last-child td {{ border-bottom:0; }}
tbody tr:hover {{ background:var(--sunk); }}
.num, .dim {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; text-align:right; white-space:nowrap; }}
.dim {{ text-align:left; font-weight:600; }}
.date {{ white-space:nowrap; }}
.date .t {{ color:var(--faint); margin-left:7px; font-size:13px; }}
code {{ font:600 11.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace; color:var(--muted);
  background:var(--sunk); padding:2px 5px; border-radius:2px; }}
.grid {{ display:grid; gap:20px; grid-template-columns:repeat(auto-fill,minmax(340px,1fr));
  align-items:start; }}
.card {{ background:var(--surface); border:1px solid var(--rule); border-radius:3px;
  overflow:hidden; box-shadow:var(--shadow); display:flex; flex-direction:column; }}
.card figure {{ margin:0; background:var(--sunk); border-bottom:1px solid var(--rule); }}
.card img {{ display:block; width:100%; height:auto; }}
.card .body {{ padding:16px 18px 18px; display:flex; flex-direction:column; gap:9px; }}
.ch {{ display:flex; justify-content:space-between; align-items:baseline; gap:10px; flex-wrap:wrap; }}
.ch h3 {{ margin:0; font-size:15.5px; font-weight:640; letter-spacing:-.01em; }}
.ch .d {{ margin:0; font:600 15px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; color:var(--accent); white-space:nowrap; }}
.bar {{ position:relative; height:20px; background:var(--sunk); border-radius:2px;
  display:flex; align-items:center; }}
.bar i {{ position:absolute; inset:0 auto 0 0; background:var(--mark); opacity:.42; border-radius:2px; }}
.bar span {{ position:relative; margin-left:8px; font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums; color:var(--ink); }}
.kv {{ display:flex; justify-content:space-between; gap:12px; font-size:13px;
  border-top:1px solid var(--rule); padding-top:7px; }}
.kv span {{ color:var(--faint); }}
.kv b {{ font-weight:600; font-variant-numeric:tabular-nums; text-align:right; }}
.fx {{ margin:4px 0 0; font-size:12.5px; color:var(--muted); }}
footer {{ margin-top:46px; padding-top:20px; border-top:1px solid var(--rule);
  font-size:12.5px; color:var(--faint); }}
a {{ color:var(--accent); }}
a:focus-visible, tr:focus-visible {{ outline:2px solid var(--accent); outline-offset:2px; }}
@media (prefers-reduced-motion:reduce) {{ * {{ animation:none!important; transition:none!important; }} }}
</style>

<div class="wrap">
<p class="eyebrow">PSMF &middot; Hanspaulsk&aacute; liga 7-G &middot; podzim 2026</p>
<h1>Every pitch we play this season, measured from the air</h1>
<p class="lede">Painted pitch dimensions for all 11 fixtures of
<b>Zde je m&iacute;sto&nbsp;&hellip;</b>, fitted to the markings in IPR Praha orthophoto imagery
at 5&nbsp;cm per pixel.</p>

<hr class="rule">
<div class="stats">
  <div class="stat"><b>11</b><span>Fixtures</span></div>
  <div class="stat"><b>10</b><span>Distinct pitches</span></div>
  <div class="stat"><b>924 m&sup2;</b><span>Smallest &middot; Hanspaulka</span></div>
  <div class="stat"><b>1550 m&sup2;</b><span>Largest &middot; Motorlet</span></div>
  <div class="stat"><b>1.7&times;</b><span>Largest &divide; smallest</span></div>
</div>

<hr class="rule">
<h2>Season fixtures</h2>
<div class="scroll"><table>
<thead><tr><th>R</th><th>Date</th><th>Opponent</th><th>Venue</th>
<th>Painted pitch L &times; W</th><th>Area m&sup2;</th></tr></thead>
<tbody>
{chr(10).join(trs)}
</tbody></table></div>

<hr class="rule">
<h2>Pitch by pitch &middot; largest to smallest</h2>
<div class="grid">
{chr(10).join(cards)}
</div>

<footer>
Imagery: IPR Praha orthophoto archive, 0.05&nbsp;m/px, EPSG:5514 (S-JTSK); capture chosen per venue.
Fixtures and venue coordinates scraped from psmf.cz. Generated 21 August 2026.
</footer>
</div>
'''
out = ROOT / "out/pitches.html"
out.write_text(html, "utf-8")
print(f"{out}  {out.stat().st_size/1e6:.2f} MB")
