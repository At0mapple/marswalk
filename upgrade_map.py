"""
upgrade_map.py  --  one-time patch for build_map.py (v2: compact on-map HUD, hover pop-up, smooth animation)

Put it next to build_map.py, run it once, then run build_map.py.
It saves build_map_backup.py first. Do NOT paste this code into build_map.py.
"""
import shutil
import sys

SRC = "build_map.py"
with open(SRC, encoding="utf-8") as f:
    text = f.read()

PATCHES = []

# ============================ PYTHON SIDE (build_map.py) ============================
PATCHES.append(("pack temperature (python)",
r'''route_slopes = slope_deg[path[:, 0], path[:, 1]]''',
r'''route_slopes = slope_deg[path[:, 0], path[:, 1]]
t_min, t_range = float(temperature_c.min()), float(np.ptp(temperature_c)) or 1.0
temp_packed = np.clip(np.round((temperature_c - t_min) / t_range * 255), 0, 255).astype("u1")'''))

PATCHES.append(("send temperature to page",
r'''"elev": pack(elev_packed), "elevMin": elev_min, "elevRange": elev_range, "slope": pack(slope_packed),''',
r'''"elev": pack(elev_packed), "elevMin": elev_min, "elevRange": elev_range, "slope": pack(slope_packed),
    "temp": pack(temp_packed), "tempMin": t_min, "tempRange": t_range,'''))

# ================================ CSS ================================
PATCHES.append(("css",
r'''</style></head>''',
r'''.hud{position:absolute;pointer-events:none;line-height:1.3;color:#202124;font-family:Roboto,"Segoe UI",system-ui,sans-serif;animation:hudin .6s ease both}
@keyframes hudin{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
#hudTop{top:12px;left:12px;max-width:55%}
#hudBottom{left:12px;bottom:12px;max-width:calc(100% - 84px)}
.chud,.pill{background:rgba(255,255,255,.96);border-radius:14px;padding:8px 14px;box-shadow:0 2px 12px rgba(0,0,0,.45)}
.chud .l1{display:flex;flex-wrap:wrap;gap:2px 14px;align-items:baseline;font-size:14px}
.chud .big{font-size:22px;font-weight:600}
.chud .nt{font-size:11px;color:#5f6368;margin-top:2px}
.pill{display:flex;flex-wrap:wrap;align-items:center;gap:4px 12px;font-size:14px}
.pill .big{font-size:18px;font-weight:600}
.pill .dot{width:11px;height:11px;border-radius:50%}
.pill.go .dot{background:#1e8e3e} .pill.nogo .dot{background:#d93025}
#pop{position:absolute;left:0;top:0;z-index:6;pointer-events:none;opacity:0;transform:translateY(6px) scale(.96);transform-origin:left bottom;
  transition:opacity .18s ease,transform .18s ease,left .12s ease-out,top .12s ease-out;
  background:#fff;color:#202124;border-radius:14px;padding:10px 14px;box-shadow:0 8px 28px rgba(0,0,0,.55);
  font:13px/1.4 Roboto,"Segoe UI",system-ui,sans-serif;min-width:190px}
#pop.show{opacity:1;transform:none}
#pop .pt{display:flex;align-items:center;gap:8px;font-weight:600;font-size:14px;margin-bottom:4px}
#pop .pt i{width:10px;height:10px;border-radius:50%}
.s-ok{background:#1e8e3e} .s-warn{background:#f9ab00} .s-bad{background:#d93025}
#pop .pg{display:grid;grid-template-columns:auto 1fr;gap:1px 16px}
#pop .pg span{color:#5f6368} #pop .pg b{text-align:right}
.zoomctl{top:auto;bottom:14px;right:12px;flex-direction:column;gap:8px}
.zoomctl button{background:#fff;color:#3c4043;border:none;box-shadow:0 1px 6px rgba(0,0,0,.5);border-radius:10px;min-width:44px;height:44px;
  transition:transform .15s ease,background .2s ease,color .2s ease}
.zoomctl button:hover{background:#f1f3f4} .zoomctl button:active{transform:scale(.92)}
.zoomctl button.on{background:#1a73e8;color:#fff}
.chip{transition:border-color .2s ease,background .2s ease}
@media(max-width:620px){#hudTop{max-width:62%}.chud .big{font-size:18px}.chud .l1{font-size:12px}.chud .nt{display:none}.pill{font-size:12px;padding:6px 10px}.pill .opt{display:none}}
</style></head>'''))

# ================================ HTML ================================
PATCHES.append(("html overlays + follow button",
r'''<div class="zoomctl">''',
r'''<div class="hud" id="hudTop"></div><div class="hud" id="hudBottom"></div><div id="pop"></div><div class="zoomctl"><button id="zfollow" title="Follow the astronaut">&#9678;</button>'''))

# ================================ JAVASCRIPT ================================
PATCHES.append(("temperature lookup",
r'''const elevAt = (r, c) => D.elevMin + elevRaw[r * W + c] / 65535 * D.elevRange;''',
r'''const tempRaw = b64(D.temp);
const tempAt = (r, c) => D.tempMin + tempRaw[r * W + c] / 255 * D.tempRange;
const elevAt = (r, c) => D.elevMin + elevRaw[r * W + c] / 65535 * D.elevRange;'''))

PATCHES.append(("animation state",
r'''const imgs = {};''',
r'''const imgs = {};
const la = {}; D.layers.forEach(n => la[n] = on.has(n) ? 1 : 0);     // layer fade (0-1)
let hv = null, hva = 0, wDisp = 0, hdDisp = null;                    // smooth hover ring, arrow position, arrow heading'''))

PATCHES.append(("target view for smooth zoom",
r'''let V = { x: 0, y: 0, w: 1 }, baseAsp = 0.5,''',
r'''const VT = { x: 0, y: 0, w: 1 };                                      // where the view is heading (V glides there)
let V = { x: 0, y: 0, w: 1 }, baseAsp = 0.5,'''))

PATCHES.append(("draw -> kick, render",
r'''function draw() {''',
r'''function draw() { kick(); }
function render() {'''))

PATCHES.append(("layers fade",
r'''    if (imgs[n] && on.has(n)) { ctx.globalAlpha = D.opacity[n] ?? 1; const im''',
r'''    if (imgs[n] && (la[n] ?? 0) > 0.01) { ctx.globalAlpha = (D.opacity[n] ?? 1) * la[n]; const im'''))

PATCHES.append(("ring fade",
r'''if (on.has('Return ring')) {''',
r'''ctx.globalAlpha = la['Return ring']; if (la['Return ring'] > 0.01) {'''))

PATCHES.append(("route fade",
r'''if (on.has('Route')) {''',
r'''ctx.globalAlpha = la['Route']; if (la['Route'] > 0.01) {'''))

PATCHES.append(("blue route",
r'''    ctx.beginPath(); for (let i = 0; i < D.route.length; i += 2) ctx[i ? 'lineTo' : 'moveTo'](X(D.route[i + 1]), Y(D.route[i]));
    ctx.lineWidth = 7 * s; ctx.strokeStyle = 'rgba(0,0,0,.55)'; ctx.stroke();
    ctx.lineWidth = 3.5 * s; ctx.strokeStyle = css('--route'); ctx.stroke();''',
r'''    const me = Math.round(wDisp), npts = D.route.length / 2;
    const trace = (a, b) => { ctx.beginPath(); for (let i = a; i <= b; i++) ctx[i === a ? 'moveTo' : 'lineTo'](X(D.route[i * 2 + 1]), Y(D.route[i * 2])); };
    trace(0, npts - 1); ctx.lineWidth = 9 * s; ctx.strokeStyle = '#fff'; ctx.stroke();
    trace(me, npts - 1); ctx.lineWidth = 5.5 * s; ctx.strokeStyle = '#1a73e8'; ctx.stroke();
    if (me > 0) { trace(0, me); ctx.lineWidth = 5.5 * s; ctx.strokeStyle = '#9aa0a6'; ctx.stroke(); }'''))

PATCHES.append(("marker label offset",
r'''halo(m.name, X(m.c), Y(m.r) + (last ? -14 : 20) * s, s, 12, 'center');''',
r'''halo(m.name, X(m.c), Y(m.r) + (last ? -14 : (m === D.markers[0] ? 40 : 20)) * s, s, 12, 'center');'''))

PATCHES.append(("point of no return fade",
r'''if (on.has('Route') && pnrIdx != null) {''',
r'''ctx.globalAlpha = la['Route']; if (la['Route'] > 0.01 && pnrIdx != null) {'''))

PATCHES.append(("scale bar reset alpha",
r'''const kmView = V.w * W * D.mpp / 1000;''',
r'''ctx.globalAlpha = 1;
  const kmView = V.w * W * D.mpp / 1000;'''))

PATCHES.append(("scale bar position",
r'''const bx = 16 * s, by = ch - 18 * s, bw = bar / kmView * cw;''',
r'''const bw = bar / kmView * cw, bx = cw - 16 * s - bw, by = 34 * s;'''))

PATCHES.append(("scale bar label",
r'''halo(bar + ' km   (zoom x' + (1 / V.w).toFixed(1) + ')', bx, by - 8 * s, s, 12, 'left');''',
r'''halo(bar + ' km  (zoom x' + (1 / V.w).toFixed(1) + ')', bx + bw, by - 8 * s, s, 12, 'right');'''))

PATCHES.append(("navigation arrow",
r'''  if (walkIdx != null) {
    const wx = X(D.route[walkIdx * 2 + 1]), wy = Y(D.route[walkIdx * 2]);
    ctx.beginPath(); ctx.arc(wx, wy, 7 * s, 0, 6.2832); ctx.fillStyle = '#ff9800'; ctx.fill();
    ctx.lineWidth = 2.5 * s; ctx.strokeStyle = '#fff'; ctx.stroke();
    halo('Astronaut', wx, wy - 13 * s, s, 12, 'center');
  }''',
r'''  {
    const n = D.route.length / 2, f = Math.max(0, Math.min(wDisp, n - 1)), i0 = Math.floor(f), i1 = Math.min(i0 + 1, n - 1), u = f - i0;
    const wx = X(D.route[i0 * 2 + 1] * (1 - u) + D.route[i1 * 2 + 1] * u), wy = Y(D.route[i0 * 2] * (1 - u) + D.route[i1 * 2] * u);
    ctx.beginPath(); ctx.arc(wx, wy, 24 * s, 0, 6.2832); ctx.fillStyle = 'rgba(26,115,232,.22)'; ctx.fill();
    ctx.save(); ctx.translate(wx, wy); ctx.rotate(hdDisp ?? headingRad(Math.round(f)));
    ctx.beginPath(); ctx.moveTo(17 * s, 0); ctx.lineTo(-11 * s, 11 * s); ctx.lineTo(-5 * s, 0); ctx.lineTo(-11 * s, -11 * s); ctx.closePath();
    ctx.lineJoin = 'round'; ctx.lineWidth = 5 * s; ctx.strokeStyle = '#fff'; ctx.stroke();
    ctx.fillStyle = '#1a73e8'; ctx.fill(); ctx.restore();
  }'''))

PATCHES.append(("smooth hover ring",
r'''if (hover) mark(hover, '#fff');''',
r'''if (hva > 0.02 && hv) { ctx.globalAlpha = hva; mark(hv, '#fff'); ctx.globalAlpha = 1; }'''))

PATCHES.append(("popup on hover",
r'''const p = mapPoint(e); hover = p; routeHover = null;''',
r'''const p = mapPoint(e); hover = p; routeHover = null; showPop(e, p);'''))

PATCHES.append(("popup hides on leave",
r'''cv.addEventListener('pointerleave', () => { hover = null; draw(); });''',
r'''cv.addEventListener('pointerleave', () => { hover = null; hidePop(); draw(); });'''))

PATCHES.append(("drag keeps target in sync",
r'''V.y = drag.vy - (e.clientY - drag.y) / rc.height * V.w; clampV(); }''',
r'''V.y = drag.vy - (e.clientY - drag.y) / rc.height * V.w; clampV(); VT.x = V.x; VT.y = V.y; VT.w = V.w; }'''))

PATCHES.append(("smooth zoom 1",
r'''const nx = V.x + fx * V.w, ny = V.y + fy * V.w; V.w = V.w / f; clampV();''',
r'''const nx = V.x + fx * V.w, ny = V.y + fy * V.w; VT.w = Math.max(1 / 24, Math.min(1, VT.w / f));'''))

PATCHES.append(("smooth zoom 2",
r'''V.x = nx - fx * V.w; V.y = ny - fy * V.w; clampV(); draw();''',
r'''VT.x = Math.max(0, Math.min(1 - VT.w, nx - fx * VT.w)); VT.y = Math.max(0, Math.min(1 - VT.w, ny - fy * VT.w)); draw();'''))

PATCHES.append(("smooth reset",
r'''const resetView = () => { V = { x: 0, y: 0, w: 1 }; draw(); };''',
r'''const resetView = () => { VT.x = 0; VT.y = 0; VT.w = 1; draw(); };'''))

PATCHES.append(("walk: update HUD when slider is at 0",
r'''box.textContent = 'Move the slider or press Play to walk the route.'; draw(); return; }''',
r'''box.textContent = 'Move the slider or press Play to walk the route.'; hud(); if (follow) centerOnMe(); draw(); return; }'''))

PATCHES.append(("walk: update HUD while walking",
r'''(ok ? 'Safe to continue.' : 'Turn back now.');
  draw();''',
r'''(ok ? 'Safe to continue.' : 'Turn back now.');
  hud(); if (follow) centerOnMe(); draw();'''))

PATCHES.append(("animation loop + HUD + popup + follow",
r'''$('walk').oninput = walkUpdate;''',
r'''// ---------- smooth animation: everything glides toward its target ----------
var raf = 0;
function kick() { if (!raf) raf = requestAnimationFrame(tick); }
function tick() {
  raf = 0; let busy = false;
  D.layers.forEach(n => { const t = on.has(n) ? 1 : 0, c = la[n] ?? t, d = t - c;
    if (Math.abs(d) > 0.01) { la[n] = c + d * 0.2; busy = true; } else la[n] = t; });
  ['x', 'y', 'w'].forEach(k => { const d = VT[k] - V[k];
    if (Math.abs(d) > 0.0002) { V[k] += d * 0.2; busy = true; } else V[k] = VT[k]; });
  const wt = walkIdx ?? 0, dw = wt - wDisp;
  if (Math.abs(dw) > 0.05) { wDisp += dw * 0.25; busy = true; } else wDisp = wt;
  const ht = headingRad(Math.round(wDisp)); if (hdDisp == null) hdDisp = ht;
  let dh = ht - hdDisp; dh = Math.atan2(Math.sin(dh), Math.cos(dh));
  if (Math.abs(dh) > 0.01) { hdDisp += dh * 0.2; busy = true; } else hdDisp = ht;
  if (hover) { if (!hv) hv = { r: hover.r, c: hover.c };
    const dr = hover.r - hv.r, dc = hover.c - hv.c;
    if (Math.abs(dr) + Math.abs(dc) > 0.05) { hv.r += dr * 0.35; hv.c += dc * 0.35; busy = true; } else { hv.r = hover.r; hv.c = hover.c; } }
  const ha = hover ? 1 : 0, da = ha - hva;
  if (Math.abs(da) > 0.02) { hva += da * 0.3; busy = true; } else hva = ha;
  render(); if (busy) kick();
}
function headingRad(i) {             // direction of travel on the screen (0 = right/east)
  const n = D.route.length / 2, a = Math.max(0, Math.min(i, n - 9)), b = Math.min(n - 1, a + 8);
  return Math.atan2(D.route[b * 2] - D.route[a * 2], D.route[b * 2 + 1] - D.route[a * 2 + 1]);
}
let follow = false;
const DIRS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
function centerOnMe() {
  const i = walkIdx ?? 0;
  VT.x = Math.max(0, Math.min(1 - VT.w, (D.route[i * 2 + 1] + 0.5) / W - VT.w / 2));
  VT.y = Math.max(0, Math.min(1 - VT.w, (D.route[i * 2] + 0.5) / H - VT.w / 2));
}
$('zfollow').onclick = () => {
  follow = !follow; $('zfollow').classList.toggle('on', follow);
  if (follow) { VT.w = Math.min(VT.w, 0.2); centerOnMe(); }
  draw();
};
function hud() {                     // the compact cards drawn ON the map
  const i = walkIdx ?? 0, r = D.route[i * 2], c = D.route[i * 2 + 1];
  const speed = +$('speed').value, k = +$('suit').value / D.suitBase, km = D.routeKm[i], t = km / speed;
  let limit = Infinity, name = '';
  Object.keys(D.supplies).forEach(n => { const h = D.supplies[n] * k; if (h < limit) { limit = h; name = n; } });
  const left = limit - t, back = km / speed, ok = left - back >= L.margin - 1e-9;
  const deg = (headingRad(i) * 180 / Math.PI + 450) % 360;
  const nxt = D.markers.find(m => m.km > km + 1e-6), rem = Math.max(0, D.distanceKm - km);
  const mins = h => { const m = Math.max(0, Math.round(h * 60)); return m >= 60 ? Math.floor(m / 60) + ' h ' + (m % 60) + ' min' : m + ' min'; };
  $('hudTop').innerHTML = '<div class="chud"><div class="l1"><span class="big">' + tempAt(r, c).toFixed(0) + ' \u00b0C</span><span>' +
    elevAt(r, c).toFixed(0) + ' m</span><span>' + slopeAt(r, c).toFixed(1) + '\u00b0 slope</span><span>' +
    DIRS[Math.round(deg / 45) % 8] + ' ' + deg.toFixed(0) + '\u00b0</span></div><div class="nt">' + D.conditions + '</div></div>';
  $('hudBottom').innerHTML = '<div class="pill ' + (ok ? 'go' : 'nogo') + '"><i class="dot"></i><span class="big">' + mins(rem / speed) +
    '</span><span>' + rem.toFixed(1) + ' km to target</span><span class="opt">' +
    (nxt ? 'Next: <b>' + nxt.name + '</b> in ' + (nxt.km - km).toFixed(1) + ' km' : 'Arrived') + '</span><span class="opt">' +
    name + ' left <b>' + mins(left) + '</b></span><b>' + (ok ? 'Safe to continue' : 'TURN BACK NOW') + '</b></div>';
}
function showPop(e, p) {             // pop-up that glides with the mouse
  const el = $('pop');
  if (drag) { el.classList.remove('show'); return; }
  const sl = slopeAt(p.r, p.c), tp = tempAt(p.r, p.c), ev = elevAt(p.r, p.c);
  const km = Math.hypot(p.r - D.habitat[0], p.c - D.habitat[1]) * D.mpp / 1000, speed = +$('speed').value;
  const cls = sl > L.slope ? 's-bad' : sl > L.slope * 0.66 ? 's-warn' : 's-ok';
  const txt = sl > L.slope ? 'Too steep to walk' : sl > L.slope * 0.66 ? 'Steep, take care' : 'Easy ground';
  const row = (a, b) => '<span>' + a + '</span><b>' + b + '</b>';
  el.innerHTML = '<div class="pt"><i class="' + cls + '"></i>' + txt + '</div><div class="pg">' + row('Temperature', tp.toFixed(0) + ' \u00b0C') +
    row('Elevation', ev.toFixed(0) + ' m') + row('Slope', sl.toFixed(1) + '\u00b0') +
    row('From base', km.toFixed(1) + ' km \u00b7 ' + Math.round(km / speed * 60) + ' min') + '</div>';
  const wr = cv.parentElement.getBoundingClientRect(), x = e.clientX - wr.left, y = e.clientY - wr.top;
  const pw = el.offsetWidth, ph = el.offsetHeight;
  let lx = x + 18, ly = y - ph - 14;
  if (lx + pw > wr.width - 8) lx = x - 18 - pw;
  if (ly < 8) ly = y + 18;
  lx = Math.max(8, lx);
  const first = !el.classList.contains('show');
  if (first) el.style.transition = 'opacity .18s ease, transform .18s ease';
  el.style.left = lx + 'px'; el.style.top = ly + 'px';
  if (first) requestAnimationFrame(() => { el.style.transition = ''; });
  el.classList.add('show');
}
function hidePop() { $('pop').classList.remove('show'); }
$('walk').oninput = walkUpdate;'''))

bad = [name for name, old, new in PATCHES if text.count(old) != 1]
if bad:
    sys.exit("Nothing changed. Could not find these spots exactly once in build_map.py: " + ", ".join(bad))

shutil.copy(SRC, "build_map_backup.py")
for name, old, new in PATCHES:
    text = text.replace(old, new)
with open(SRC, "w", encoding="utf-8") as f:
    f.write(text)
print("Done. Backup saved as build_map_backup.py. Now run: python build_map.py")
