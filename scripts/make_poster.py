#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["cairosvg"]
# ///
"""Generate the shareable findings poster (SVG + PNG) from the survey stats.

All numbers are read from findings/stats.json / survey.json — never hand-typed —
so the graphic can't drift from the data.
"""
from __future__ import annotations
import json, html
from pathlib import Path
import cairosvg

ROOT = Path(__file__).resolve().parent.parent
st = json.loads((ROOT / "findings/stats.json").read_text())
rows = json.loads((ROOT / "findings/survey.json").read_text())["rows"]

N = st["n"]; USERS = st["actual_openrouter_users"]
KL = st["safety_class"]
AT_RISK = KL.get("at_risk", 0); HANDLED = KL.get("handled", 0)
NONUSERS = KL.get("not_on_result_path", 0) + KL.get("no_usage_found", 0)
CRIT = st["critical_route"]; HIGH = st["severity"].get("high", 0)
FINDINGS = st["impacted"]["total_findings"]
PCT = st["at_risk_pct_of_critical_route"]   # headline: of repos where OR feeds a result
PCT_USERS = st["at_risk_pct_of_users"]      # secondary: of repos with any call site
FREQ = st["mistake_freq"]

TAX = {
 "M1":("Unpinned quantization","high"),"M2":("Silent parameter dropping","high"),
 "M3":("Probabilistic provider routing","high"),"M4":("No provenance logging","high"),
 "M5":("Data-policy left open","med"),"M6":("Model version drift","med"),
 "M7":("seed → determinism assumption","med"),"M8":("Cross-provider comparison confound","high"),
 "M9":("Judge on unconstrained route","high"),"M10":("No reporting","med"),
 "M11":("Silent backend mixing","med"),"M12":("Cheap/degraded route chosen","med"),
}

# palette (dark "console")
C = dict(bg="#0d1219", panel="#161d27", border="#28313d", ink="#e7edf5",
         muted="#97a3b6", faint="#6b7789", accent="#6fa0e6",
         safe="#46c08a", med="#e0ab4d", high="#e37363")
SHORT = {"M1":"Unpinned quantization","M2":"Silent param dropping","M3":"Probabilistic routing",
 "M4":"No provenance logging","M5":"Data-policy left open","M6":"Model version drift",
 "M7":"seed → determinism","M8":"Comparison confound","M9":"Unconstrained judge",
 "M10":"No reporting","M11":"Silent backend mixing","M12":"Cheap route chosen"}
MONO="DejaVu Sans Mono, monospace"; SANS="DejaVu Sans, sans-serif"
W, H = 1200, 1500
def e(s): return html.escape(str(s), quote=True)

def wrap(text, maxc):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur)+len(w)+1 <= maxc: cur = (cur+" "+w).strip()
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines

S = []
def add(x): S.append(x)
def text(x,y,s,size,fill=C["ink"],font=SANS,weight="normal",anchor="start",spacing=None,op=1):
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    add(f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}"{ls} opacity="{op}">{e(s)}</text>')
def multiline(x,y,lines,size,lh,**kw):
    for i,ln in enumerate(lines): text(x, y+i*lh, ln, size, **kw)
    return y + len(lines)*lh

add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
add(f'<rect width="{W}" height="{H}" fill="{C["bg"]}"/>')
# subtle top hairline accent
add(f'<rect x="0" y="0" width="{W}" height="4" fill="{C["accent"]}" opacity="0.9"/>')

M = 72
# eyebrow
add(f'<rect x="{M}" y="52" width="30" height="3" fill="{C["accent"]}"/>')
text(M+42, 60, "PROVIDER ROUTING INSPECTOR", 20, C["accent"], MONO, "bold", spacing="3")
text(W-M, 60, "openrouter reliability audit", 17, C["faint"], MONO, anchor="end")

# hero
text(M, 210, f"{PCT}%", 150, C["high"], MONO, "bold")
hx = M + 300
htxt = wrap(f"of the {CRIT} influential AI-research repos whose OpenRouter output reaches a "
            f"published result leave a silent corruption channel open.", 42)
multiline(hx, 128, htxt, 33, 42, fill=C["ink"], weight="bold")

# subline
sub = wrap("OpenRouter serves “a model” from whichever provider is cheapest-and-up — at any "
           "quantization down to int4, silently dropping sampling params it can’t honor. Two "
           "identical requests can come back as different weights.", 82)
y = multiline(M, 300, sub, 22, 32, fill=C["muted"])

# stat tiles
tiles = [(f"{AT_RISK}/{CRIT}", f"at risk, of the {CRIT} whose output reaches a result", C["high"]),
         (str(FINDINGS), "specific claims / figures possibly affected", C["high"]),
         (str(HIGH), "carry a high-severity gap", C["med"]),
         (str(HANDLED), "uses it properly — the only one", C["safe"])]
ty = 432; th = 140; gap = 18; tw = (W - 2*M - 3*gap) / 4
for i,(num,lab,col) in enumerate(tiles):
    tx = M + i*(tw+gap)
    lines = wrap(lab, 22)
    if len(lines) > 3:
        raise SystemExit(f"tile label overflows its box ({len(lines)} lines > 3): {lab!r}")
    add(f'<rect x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="12" fill="{C["panel"]}" stroke="{C["border"]}"/>')
    add(f'<rect x="{tx}" y="{ty}" width="4" height="{th}" rx="2" fill="{col}"/>')
    text(tx+22, ty+66, num, 46, col, MONO, "bold")
    multiline(tx+22, ty+92, lines, 15.5, 19, fill=C["muted"])

# mistake bars
by = ty + th + 60
add(f'<rect x="{M}" y="{by-34}" width="26" height="3" fill="{C["accent"]}"/>')
text(M+38, by-26, "WHICH MISTAKES SHOW UP  ·  repos exhibiting each (of %d)" % N, 18, C["muted"], MONO, "bold", spacing="1")
top = list(FREQ.items())[:8]
maxc = max(c for _,c in top)
bx = M + 320                 # bar track start x
bw = W - M - bx - 60         # track width
rowh = 46
for i,(m,c) in enumerate(top):
    ry = by + 16 + i*rowh
    name,sev = SHORT[m], TAX[m][1]
    col = C[sev]
    text(M, ry+21, m, 18, C["faint"], MONO, "bold")
    text(M+52, ry+21, name, 19, C["ink"], SANS)
    add(f'<rect x="{bx}" y="{ry+4}" width="{bw}" height="22" rx="5" fill="{C["panel"]}"/>')
    fillw = max(8, bw * c / maxc)
    add(f'<rect x="{bx}" y="{ry+4}" width="{fillw:.1f}" height="22" rx="5" fill="{col}"/>')
    text(bx+bw+16, ry+22, str(c), 21, C["ink"], MONO, "bold")
# legend
ly = by + 16 + len(top)*rowh + 6
add(f'<rect x="{M}" y="{ly}" width="13" height="13" rx="3" fill="{C["high"]}"/>')
text(M+20, ly+12, "High — can distort a result", 16, C["muted"], SANS)
add(f'<rect x="{M+300}" y="{ly}" width="13" height="13" rx="3" fill="{C["med"]}"/>')
text(M+320, ly+12, "Medium — reproducibility / leakage / disclosure", 16, C["muted"], SANS)

# caveat box
cy = ly + 44
ch = 150
add(f'<rect x="{M}" y="{cy}" width="{W-2*M}" height="{ch}" rx="12" fill="{C["panel"]}" stroke="{C["border"]}"/>')
add(f'<rect x="{M}" y="{cy}" width="4" height="{ch}" rx="2" fill="{C["accent"]}"/>')
text(M+24, cy+34, "READ THIS CORRECTLY", 15, C["accent"], MONO, "bold", spacing="1.5")
cav = wrap("“At risk” = a known corruption channel left open and uncontrolled — not proof any published "
           f"number is wrong. Of {N} repos surveyed, {USERS} contain an OpenRouter call site and {CRIT} put its "
           f"output on a result path; the {NONUSERS} that never do are excluded rather than counted as "
           "successes. Only ONE repo both uses OpenRouter for real results and controls for it.", 96)
multiline(M+24, cy+62, cav, 18, 26, fill=C["muted"])

# the fix panel
fxy = cy + ch + 34; fxh = 150
add(f'<rect x="{M}" y="{fxy}" width="{W-2*M}" height="{fxh}" rx="12" fill="{C["panel"]}" stroke="{C["border"]}"/>')
add(f'<rect x="{M}" y="{fxy}" width="4" height="{fxh}" rx="2" fill="{C["safe"]}"/>')
text(M+24, fxy+34, "THE FIX  ·  ~5 MINUTES", 15, C["safe"], MONO, "bold", spacing="1.5")
text(M+24, fxy+70, 'provider = { "only": ["<provider/quant-you-validated>"],   # e.g. "cerebras/fp16"', 17, C["ink"], MONO)
# x-offset in place of leading spaces: SVG collapses whitespace, so indent geometrically
text(M+24+13*10.2, fxy+96, '"allow_fallbacks": false,  "require_parameters": true }', 17, C["ink"], MONO)
text(M+24, fxy+126, "→ then log which provider actually served each call. Now anyone can reproduce you.", 17, C["safe"], MONO)

# footer
text(M, H-70, "SOURCES  NeurIPS · ICML · ICLR · ACL · NAACL · Nature · UK AISI · METR · Redwood · Palisade · LessWrong",
     15, C["faint"], MONO, spacing="0.5")
text(M, H-40, "importance-first · audit + adversarial verify per repo", 15, C["muted"], MONO)
text(W-M, H-40, "github.com/AMindToThink/openrouter_reliable_research_search", 15, C["accent"], MONO, anchor="end")

add('</svg>')
svg = "\n".join(S)
out_svg = ROOT / "image/openrouter_findings.svg"
out_png = ROOT / "image/openrouter_findings.png"
out_svg.write_text(svg)
cairosvg.svg2png(bytestring=svg.encode(), write_to=str(out_png), output_width=W*2, output_height=H*2)
print(f"wrote {out_svg.relative_to(ROOT)} and {out_png.relative_to(ROOT)} (2x = {W*2}x{H*2})")
print(f"numbers: {PCT}% at risk ({AT_RISK}/{CRIT} on a result path; {PCT_USERS}% of {USERS} with any call site), "
      f"{FINDINGS} findings, {HIGH} high-sev, {HANDLED} handled, {NONUSERS} non-users of {N} surveyed")
