// A small chart over a row of points - seasons, or turns of the rotation: lines, or areas stacked
// on each other, on one y axis, with a crosshair and a tooltip. The meta tab's charts and a unit's
// turns use it.
//
//   points  [{label (the x tick), key (what the tooltip names)}]
//   series  [{name, cls (colour class: s-<cls>), values: one per point, null for none}]
//   stacked areas, each on the ones before it (values are counts or shares)
//   min, max, ticks, format   the y axis: min (0 unless given) to max, the grid lines, how a value reads
//   zones   [{from, to, cls, label}] behind the marks (the generality bands)
//   tip(i)  the tooltip of point i; mark (a point index) a dashed line after it

import { h, s, showTip, moveTip, hideTip } from "./ui.js";

const MARGIN = { l: 40, r: 70, t: 14, b: 30 };

export function lineChart({ points, series, stacked = false, min = 0, max, ticks, format = String, zones = [], tip, mark = null,
  height = 220, label, xLabel = "시즌" }) {
  const host = h("div", { class: "chart-host lc-host", tabindex: "0", role: "img", "aria-label": label,
    style: { minHeight: `${height}px` } });
  const n = points.length;
  let hover = -1;
  let geometry = null;

  // stacked: each series' band is [below, below + value]
  const bands = series.map(() => new Array(n));
  for (let i = 0; i < n; i++) {
    let below = 0;
    series.forEach((ser, k) => {
      const v = ser.values[i];
      if (v == null || Number.isNaN(v)) { bands[k][i] = null; return; }
      bands[k][i] = stacked ? [below, below + v] : [v, v];
      if (stacked) below += v;
    });
  }

  function setHover(i, pointer = null) {
    if (i === hover && i >= 0 && pointer && geometry) { moveTip(host, pointer); return; }
    hover = i;
    if (!geometry) return;
    const { svg, x, y } = geometry;
    const cross = svg.querySelector(".cross");
    for (const dot of svg.querySelectorAll(".hover-dot")) dot.remove();
    if (i < 0) { cross.setAttribute("visibility", "hidden"); hideTip(host); return; }
    cross.setAttribute("x1", x(i));
    cross.setAttribute("x2", x(i));
    cross.setAttribute("visibility", "visible");
    series.forEach((ser, k) => {
      const b = bands[k][i];
      if (b) svg.append(s("circle", { class: `hover-dot s-${ser.cls}`, cx: x(i), cy: y(b[1]), r: 4.5 }));
    });
    const box = host.getBoundingClientRect();
    showTip(host, tip(i), pointer || { x: box.left + x(i), y: box.top + 20 });
  }

  function draw() {
    const width = Math.max(300, Math.floor(host.clientWidth));
    const narrow = width < 560;
    const m = { ...MARGIN, l: narrow ? 34 : MARGIN.l, r: narrow ? 66 : MARGIN.r };
    const iw = width - m.l - m.r;
    const ih = height - m.t - m.b;
    const step = iw / Math.max(n, 1);
    const x = (i) => m.l + step * (i + 0.5);
    const y = (v) => m.t + ih * (1 - (Math.min(v, max) - min) / (max - min));
    const base = y(min);
    const svg = s("svg", { width, height, viewBox: `0 0 ${width} ${height}`, class: "traj lc" });

    const back = s("g", { class: "bands" });
    for (const z of zones) {
      back.append(s("rect", { class: `zone ${z.cls}`, x: m.l, y: y(z.to), width: iw, height: y(z.from) - y(z.to) }));
      if (z.label && y(z.from) - y(z.to) >= 16) {
        back.append(s("text", { class: `ax zone-label ${z.cls}`, x: m.l + iw + 8, y: (y(z.from) + y(z.to)) / 2 + 4 }, z.label));
      }
    }
    for (const v of ticks) {
      back.append(s("line", { class: v === min ? "axis" : "grid", x1: m.l, x2: m.l + iw, y1: y(v), y2: y(v) }));
      back.append(s("text", { class: "ax", x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, format(v)));
    }
    svg.append(back);

    // runs of points with a value: a line (or an area) breaks where there is none
    const runs = (k) => {
      const out = [];
      let cur = [];
      for (let i = 0; i < n; i++) {
        if (bands[k][i]) cur.push(i);
        else if (cur.length) { out.push(cur); cur = []; }
      }
      if (cur.length) out.push(cur);
      return out;
    };
    series.forEach((ser, k) => {
      for (const run of runs(k)) {
        if (stacked) {
          const top = run.map((i, j) => `${j ? "L" : "M"}${x(i)},${y(bands[k][i][1])}`).join("");
          const bottom = [...run].reverse().map((i) => `L${x(i)},${y(bands[k][i][0])}`).join("");
          svg.append(s("path", { class: `area s-${ser.cls}`, d: `${top}${bottom}Z` }));
        } else if (run.length > 1) {
          const d = run.map((i, j) => `${j ? "L" : "M"}${x(i)},${y(bands[k][i][1])}`).join("");
          svg.append(s("path", { class: "halo", d }), s("path", { class: `line s-${ser.cls}`, d }));
        } else {
          svg.append(s("circle", { class: `dot s-${ser.cls}`, cx: x(run[0]), cy: y(bands[k][run[0]][1]), r: 3 }));
        }
      }
    });

    // each series named at its last point (the legend says it too)
    const ends = [];
    series.forEach((ser, k) => {
      let i = n - 1;
      while (i >= 0 && !bands[k][i]) i--;
      if (i < 0) return;
      const [lo, hi] = bands[k][i];
      ends.push({ ser, i, y: stacked ? (y(lo) + y(hi)) / 2 : y(hi) });
    });
    ends.sort((a, b) => a.y - b.y);
    for (let j = 1; j < ends.length; j++) if (ends[j].y - ends[j - 1].y < 13) ends[j].y = ends[j - 1].y + 13;
    for (const e of ends) {
      if (!stacked) svg.append(s("circle", { class: `dot s-${e.ser.cls}`, cx: x(e.i), cy: y(bands[series.indexOf(e.ser)][e.i][1]), r: 3.5 }));
      svg.append(s("text", { class: "ax end-label", x: x(n - 1) + step / 2 + 6, y: e.y + 4 }, e.ser.name));
    }

    if (mark != null && mark < n - 1) {
      const mx = m.l + step * (mark + 1);
      svg.append(s("rect", { class: "after-day", x: mx, y: m.t, width: step * (n - 1 - mark), height: base - m.t }));
      svg.append(s("line", { class: "day-line", x1: mx, x2: mx, y1: m.t - 4, y2: base }));
    }

    const every = Math.max(1, Math.ceil(28 / step));
    const axis = s("g", { class: "xaxis" });
    let lastX = -1e9;
    points.forEach((p, i) => {
      if (i !== 0 && i !== n - 1 && i % every !== 0) return;
      if (x(i) - lastX < 26 && i !== n - 1) return;
      lastX = x(i);
      axis.append(s("text", { class: "ax", x: x(i), y: base + 18, "text-anchor": "middle" }, p.label));
    });
    axis.append(s("text", { class: "ax", x: m.l - 8, y: base + 18, "text-anchor": "end" }, xLabel));
    svg.append(axis);

    svg.append(s("line", { class: "cross", x1: 0, x2: 0, y1: m.t, y2: base, visibility: "hidden" }));
    const hit = s("rect", { class: "hit", x: m.l, y: 0, width: iw, height });
    svg.append(hit);
    const index = (clientX) => {
      const box = svg.getBoundingClientRect();
      return Math.max(0, Math.min(n - 1, Math.floor((clientX - box.left - m.l) / step)));
    };
    hit.addEventListener("pointermove", (e) => setHover(index(e.clientX), { x: e.clientX, y: e.clientY }));
    hit.addEventListener("pointerdown", (e) => setHover(index(e.clientX), { x: e.clientX, y: e.clientY }));
    hit.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") setHover(-1); });
    geometry = { svg, x, y };
    host.replaceChildren(svg);
    if (hover >= 0) setHover(hover);
  }

  host.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      setHover(Math.max(0, Math.min(n - 1, (hover < 0 ? n : hover) + (e.key === "ArrowRight" ? 1 : -1))));
    } else if (e.key === "Escape") setHover(-1);
  });
  host.addEventListener("blur", () => setHover(-1));
  let lastWidth = 0;
  new ResizeObserver(() => {
    const w = Math.floor(host.clientWidth);
    if (w && w !== lastWidth) { lastWidth = w; draw(); }
  }).observe(host);
  return host;
}

// A legend row for ``series``: a swatch and the name each.
export function lineLegend(series, { stacked = false } = {}) {
  return h("div", { class: "legend" }, series.map((ser) =>
    h("span", { class: "lg" }, h("i", { class: ["sw", stacked ? "zone" : "line", `s-${ser.cls}`] }), ser.name)));
}
