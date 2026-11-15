"""docs/proof-card.png (1200x675): the shareable proof card. Every value is read from results.json; the site's dark palette.
    python scripts/render_proof_card.py            (needs Chrome or Edge for the screenshot; set CHROME_PATH to override)"""
import html, json, os, pathlib, shutil, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parent.parent
r = json.loads((ROOT / "results.json").read_text(encoding="utf8"))

sw = r["store_swap"]
graph = sw["backends"][sw["reference"]]["ac1"]["point"]                  # GhostWalk's own accuracy in the same run as the vector-search store
vec = sw["backends"]["pgvector"]["ac1"]["point"]
vec_ci = sw["backends"]["pgvector"]["ac1"]["ci95"]
graph_ci = sw["backends"][sw["reference"]]["ac1"]["ci95"]
off = r["paired"]["ac1"]["ghostwalk - learning_off"]
best = r["headline"]["gain_vs_best"]
hy = sw["backends"].get("hydradb")
if hy:
    lat, lat_label = hy["verdict_ms_p95"], "HydraDB p95 verdict"
else:
    lat, lat_label = r["ops"]["ghostwalk"]["verdict_ms_p95"], "in-memory p95 verdict"
n = r["meta"]["companies"]
pts = lambda x: f"{x * 100:+.1f} pts".replace("-", "−")
ms = lambda x: f"{x:.1f} ms" if x < 10 else f"{x:.0f} ms"

series = r["learning_curve"]["series"]
W, H, L, B, T = 560, 230, 38, 24, 8
allv = [p["ac1"] for k in ("ghostwalk", "placebo") for p in series[k]] + [p["ci95"][1] for p in series["ghostwalk"]] + [p["ci95"][0] for p in series["ghostwalk"]]
lo, hi = max(0, min(allv) - 0.03), min(1, max(allv) + 0.03)
nb = len(series["ghostwalk"])
x = lambda i: L + i * (W - L - 8) / (nb - 1)
y = lambda v: T + (hi - v) * (H - T - B) / (hi - lo)
line = lambda k: " ".join(f"{'L' if i else 'M'}{x(i):.1f},{y(p['ac1']):.1f}" for i, p in enumerate(series[k]))
sg = series["ghostwalk"]
band = " ".join(f"{'L' if i else 'M'}{x(i):.1f},{y(p['ci95'][1]):.1f}" for i, p in enumerate(sg)) + " " + " ".join(f"L{x(i):.1f},{y(p['ci95'][0]):.1f}" for i, p in reversed(list(enumerate(sg)))) + " Z"
grid = "".join(f'<line x1="{L}" x2="{W-8}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="rgba(255,255,255,.08)"/><text x="{L-8}" y="{y(v)+4:.1f}" text-anchor="end" font-size="11" fill="#8F8E9A" font-family="Geist Mono, monospace">{v:.1f}</text>'
               for v in [round(lo + (hi - lo) * k / 3, 2) for k in range(4)])
xt = "".join(f'<text x="{x(i):.1f}" y="{H-6}" text-anchor="middle" font-size="11" fill="#8F8E9A" font-family="Geist Mono, monospace">{series["ghostwalk"][i]["from"]}</text>' for i in range(0, nb, 3))

page = f"""<!doctype html><html><head><meta charset="utf-8"><link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
html,body{{margin:0;width:1200px;height:675px;background:#09090E;color:#F6F5F1;font-family:'Geist',system-ui,sans-serif;overflow:hidden}}
.card{{box-sizing:border-box;width:1200px;height:675px;padding:44px 56px;display:flex;flex-direction:column;background:radial-gradient(60% 50% at 85% 0%,rgba(142,118,255,.16),transparent 70%),#09090E}}
.mono{{font-family:'Geist Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}}
.logo{{font-size:22px;font-weight:600}} .logo b{{color:#8E76FF;font-weight:600}}
.big{{display:flex;align-items:baseline;gap:22px;margin-top:6px}}
.num{{font-size:112px;line-height:1;font-weight:600;letter-spacing:-.04em}}
.vs{{font-size:30px;color:#A6A5B1}} .vec{{font-size:64px;font-weight:600;color:#8F8E9A}}
.sub{{font-size:22px;color:#DAD9E2;margin-top:6px}}
.row{{display:flex;gap:40px;margin-top:22px;flex:1}}
.stat{{border-top:1px solid rgba(255,255,255,.12);padding-top:12px;margin-bottom:14px}}
.stat .v{{font-size:34px;font-weight:600}} .stat .l{{font-size:14px;color:#A6A5B1}} .stat .n{{font-size:12px;color:#8F8E9A;margin-top:2px}}
.foot{{font-size:16px;color:#8F8E9A;display:flex;justify-content:space-between;border-top:1px solid rgba(255,255,255,.08);padding-top:14px}}
</style></head><body><div class="card">
<div class="logo mono">ghost<b>walk</b></div>
<div class="big"><span class="num mono" style="color:#AC9BFF">{graph*100:.1f}%</span><span class="vs">vs</span><span class="vec mono">{vec*100:.1f}%</span></div>
<div class="sub">graph walk vs vector search over postmortems: top-1 root cause on held-out incidents</div>
<div class="mono" style="color:#8F8E9A;font-size:15px;margin-top:4px">95% CI {graph_ci[0]:.3f}–{graph_ci[1]:.3f} vs {vec_ci[0]:.3f}–{vec_ci[1]:.3f}</div>
<div class="row">
 <div style="flex:none"><svg width="{W}" height="{H}" viewBox="0 0 {W} {H}">{grid}{xt}
   <path d="{band}" fill="#8E76FF" opacity=".16"/><path d="{line('placebo')}" fill="none" stroke="#8F8E9A" stroke-width="2" stroke-dasharray="5 4"/>
   <path d="{line('ghostwalk')}" fill="none" stroke="#8E76FF" stroke-width="3.2"/></svg>
   <div class="mono" style="font-size:12px;color:#8F8E9A;display:flex;gap:18px;margin-top:2px"><span style="color:#AC9BFF">━ GhostWalk, 95% band</span><span>╌ random postmortems (placebo)</span><span style="margin-left:auto">incident number</span></div></div>
 <div style="flex:1;display:flex;flex-direction:column;justify-content:center">
  <div class="stat"><div class="v mono">{pts(off['point'])}</div><div class="l">vs learning off</div><div class="n mono">95% CI {pts(off['ci95'][0])} to {pts(off['ci95'][1])}</div></div>
  <div class="stat"><div class="v mono">{pts(best['point'])}</div><div class="l">vs best baseline ({html.escape(best['baseline'])})</div><div class="n mono">95% CI {pts(best['ci95'][0])} to {pts(best['ci95'][1])}</div></div>
  <div class="stat"><div class="v mono">{ms(lat)}</div><div class="l">{lat_label}</div></div>
 </div></div>
<div class="foot"><span>{n} unseen companies · 95% CIs · reproducible</span><span class="mono">make eval</span></div>
</div></body></html>"""

out = ROOT / "docs" / "proof-card.png"
out.parent.mkdir(exist_ok=True)
chrome = os.environ.get("CHROME_PATH") or next((c for c in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                                                             shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chrome")) if c and pathlib.Path(c).exists()), None)
if not chrome:
    sys.exit("no Chrome/Edge found: set CHROME_PATH")
with tempfile.TemporaryDirectory() as d:
    f = pathlib.Path(d) / "card.html"
    f.write_text(page, encoding="utf8")
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1200,675", "--force-device-scale-factor=1",
                    "--virtual-time-budget=6000", f"--screenshot={out}", f.as_uri()], check=True, capture_output=True)
print("wrote", out)
