// One unit's record as a chart: its lift each season (bars, its own element's
// seasons in the accent), its overall tier once each season was over (line),
// its element tier (a step line that moves in that element's seasons), the tier
// cuts as bands, and the treasure where it came. One axis: every value is lift.

import { assignTier } from "./model.js";
import { h, s, num, pct, elementIcon, ELEMENT_KO, day, shortDay, showTip, moveTip, hideTip, tierBadge, unitName } from "./ui.js";

const HEIGHT = 300;
const MARGIN = { l: 40, r: 34, t: 24, b: 44 };

// 1.4 -> "1.4", 1.45 -> "1.45"
const tick = (v) => num(v, Math.abs(Math.round(v * 10) - v * 10) > 1e-9 ? 2 : 1);

function barPath(x0, base, w, height, r) {
  if (height <= 0.5) return "";
  const rr = Math.min(r, w / 2, height);
  const top = base - height;
  return `M${x0},${base}V${top + rr}Q${x0},${top} ${x0 + rr},${top}H${x0 + w - rr}Q${x0 + w},${top} ${x0 + w},${top + rr}V${base}Z`;
}

// records: [{season (summary entry), row, hist}] in season order; own: the elements the unit counts as.
export function trajectoryChart(app, u, records, { own, treasureAt = null }) {
  const cuts = app.state.params.cuts;
  const unit = app.model.units[u];
  const firstTreasure = records.findIndex((r) => r.row.treasure);
  const slotOf = (rec) => {
    if (!rec.row.elementMatch) return 0;
    const i = own.indexOf(rec.season.weak);
    return i < 0 ? 1 : Math.min(i + 1, 2);
  };

  const legendItems = [
    h("span", { class: "lg" }, h("i", { class: "sw bar own1" }), own.length > 1 ? `${ELEMENT_KO[own[0]]} 약점 시즌` : "자기 속성 약점 시즌"),
    own.length > 1 ? h("span", { class: "lg" }, h("i", { class: "sw bar own2" }), `${ELEMENT_KO[own[1]]} 약점 시즌`) : null,
    h("span", { class: "lg" }, h("i", { class: "sw bar" }), "다른 시즌 (막대 = 그 시즌 기여도)"),
    h("span", { class: "lg" }, h("i", { class: "sw line ink" }), "종합 티어"),
    h("span", { class: "lg" }, h("i", { class: "sw line own1 step" }), own.length > 1 ? `${ELEMENT_KO[own[0]]} 속성 티어` : "속성 티어"),
    own.length > 1 ? h("span", { class: "lg" }, h("i", { class: "sw line own2 step" }), `${ELEMENT_KO[own[1]]} 속성 티어`) : null,
    firstTreasure > 0 ? h("span", { class: "lg" }, h("i", { class: "sw heart" }, "♥"), "애장품") : null,
  ];
  const host = h("div", { class: "chart-host", tabindex: "0", role: "img",
    "aria-label": `${unitName(unit)} 시즌별 기여도와 티어 변화, 시즌 ${records[0]?.season.season}부터 ${records[records.length - 1]?.season.season}까지. 아래 표에 같은 값이 있습니다.` });
  const root = h("div", { class: "chart" }, h("div", { class: "legend" }, legendItems), host);

  let hover = -1;
  let geometry = null;

  function tipFor(i) {
    const rec = records[i];
    const info = rec.season.info;
    const hist = rec.hist;
    const tier = assignTier(rec.row.lift, cuts);
    const live = !rec.season.final;
    return h("div", { class: "tip" },
      h("div", { class: "tip-name" }, `시즌 ${info.season}`, h("span", { class: "muted" }, info.bossKo || info.bossEn || "")),
      h("div", { class: "tip-attrs" }, "약점 ", elementIcon(info.weak, 14), ELEMENT_KO[info.weak] || "?",
        rec.row.elementMatch ? h("span", { class: "pill" }, "▶ 자기 속성") : null,
        h("span", { class: "muted" }, ` · ${day(info.start)}${live ? ` · 진행 중(${shortDay(rec.season.collectedOn)} 수집분)` : ""}`)),
      h("dl", { class: "tip-list" },
        h("dt", null, "기여도"), h("dd", null, tierBadge(tier, rec.row.lift), h("span", { class: "muted" }, " 그 시즌")),
        h("dt", null, "사용"), h("dd", null, rec.row.rankers
          ? `${pct(rec.row.usageRate)} · 1덱 ${pct(rec.row.inDeck[0] / rec.row.rankers)} · 평균 ${num(rec.row.avgDeck)}덱`
          : h("span", { class: "muted" }, "아무도 안 씀")),
        hist && hist.counted && !Number.isNaN(hist.elementLift) ? [h("dt", null, `${ELEMENT_KO[info.weak]} 티어`),
          h("dd", null, tierBadge(hist.elementTier, hist.elementLift), h("span", { class: "muted" }, ` 시즌 끝 · ${hist.elementSeasons}번째`))] : null,
        hist && !Number.isNaN(hist.overall) ? [h("dt", null, "종합 티어"),
          h("dd", null, tierBadge(hist.overallTier, hist.overall), h("span", { class: "muted" }, hist.provisional ? " 시즌 끝 · 잠정" : " 시즌 끝"))] : null),
      i === firstTreasure && treasureAt != null ? h("div", { class: "tip-notes" },
        h("span", { class: "pill heart" }, `♥ 애장품 ${day(treasureAt)} — 여기부터 애장품을 낀 시즌만으로`)) : null);
  }

  function setHover(i, at = null) {
    if (i === hover && i >= 0 && at && geometry) { moveTip(host, at); return; }
    hover = i;
    if (!geometry) return;
    const { svg, x } = geometry;
    const cross = svg.querySelector(".cross");
    const wash = svg.querySelector(".wash");
    for (const dot of svg.querySelectorAll(".hover-dot")) dot.remove();
    if (i < 0) {
      cross.setAttribute("visibility", "hidden");
      wash.setAttribute("visibility", "hidden");
      hideTip(host);
      return;
    }
    const cx = x(i);
    cross.setAttribute("x1", cx);
    cross.setAttribute("x2", cx);
    cross.setAttribute("visibility", "visible");
    wash.setAttribute("x", cx - geometry.band / 2);
    wash.setAttribute("visibility", "visible");
    for (const [cls, value] of geometry.pointsAt(i)) {
      svg.append(s("circle", { class: `hover-dot ${cls}`, cx, cy: geometry.y(value), r: 4.5 }));
    }
    const box = host.getBoundingClientRect();
    showTip(host, tipFor(i), at || { x: box.left + cx, y: box.top + geometry.y(records[i].row.lift) });
  }

  function draw() {
    const width = Math.max(300, Math.floor(host.clientWidth));
    const narrow = width < 560;
    const H = narrow ? 260 : HEIGHT;
    const m = { ...MARGIN, l: narrow ? 34 : MARGIN.l };
    const iw = width - m.l - m.r;
    const ih = H - m.t - m.b;
    const n = records.length;
    const band = iw / Math.max(n, 1);
    const x = (i) => m.l + band * (i + 0.5);
    const values = records.flatMap((r) => [r.row.lift, r.hist?.overall, r.hist?.counted ? r.hist.elementLift : null])
      .filter((v) => v != null && !Number.isNaN(v));
    const top = Math.max(cuts[0][1] + 0.25, ...values) * 1.06;
    const yMax = Math.ceil(top * 5) / 5;
    const y = (v) => m.t + ih * (1 - v / yMax);
    const base = y(0);

    const svg = s("svg", { width, height: H, viewBox: `0 0 ${width} ${H}`, class: "traj" });

    // tier bands and cuts
    const bands = s("g", { class: "bands" });
    cuts.forEach(([label, lo], k) => {
      const hi = k === 0 ? yMax : cuts[k - 1][1];
      if (lo >= yMax) return;
      const y0 = y(Math.min(hi, yMax)), y1 = y(lo);
      if (k < cuts.length - 1) bands.append(s("rect", { class: "band", "data-tier": label, x: m.l, y: y0, width: iw, height: y1 - y0 }));
      if (lo > 0) {
        bands.append(s("line", { class: "grid", x1: m.l, x2: m.l + iw, y1, y2: y1 }));
        bands.append(s("text", { class: "ax", x: m.l - 6, y: y1 + 4, "text-anchor": "end" }, tick(lo)));
      }
      if (y1 - y0 >= 11) bands.append(s("text", { class: "ax tier", "data-tier": label, x: m.l + iw + 8, y: (y0 + y1) / 2 + 4 }, label));
    });
    bands.append(s("line", { class: "axis", x1: m.l, x2: m.l + iw, y1: base, y2: base }));
    bands.append(s("text", { class: "ax", x: m.l - 6, y: base + 4, "text-anchor": "end" }, "0"));
    svg.append(bands);

    // hover wash sits under the marks
    svg.append(s("rect", { class: "wash", x: 0, y: m.t, width: band, height: ih, visibility: "hidden" }));

    // bars: the season's lift
    const bw = Math.max(2, Math.min(16, band * 0.62));
    const bars = s("g", { class: "bars" });
    let peak = -1;
    records.forEach((rec, i) => {
      if (peak < 0 || rec.row.lift > records[peak].row.lift) peak = i;
      const d = barPath(x(i) - bw / 2, base, bw, base - y(rec.row.lift), Math.min(3, bw / 2));
      if (d) bars.append(s("path", { d, class: `bar own${slotOf(rec)}${rec.season.final ? "" : " live"}` }));
    });
    svg.append(bars);
    if (peak >= 0 && records[peak].row.lift > 0) {
      const px = x(peak);
      const anchor = px < m.l + 40 ? "start" : px > m.l + iw - 40 ? "end" : "middle";
      svg.append(s("text", { class: "ax peak", x: px, y: y(records[peak].row.lift) - 6, "text-anchor": anchor },
        `최고 ${num(records[peak].row.lift)} · S${records[peak].season.season}`));
    }

    // lines break at the treasure: its tiers start over from there
    const segments = (pick) => {
      const parts = [];
      let cur = [];
      records.forEach((rec, i) => {
        if (i === firstTreasure && firstTreasure > 0) { if (cur.length) parts.push(cur); cur = []; }
        const v = pick(rec);
        if (v == null || Number.isNaN(v)) { if (cur.length) parts.push(cur); cur = []; return; }
        cur.push([i, v]);
      });
      if (cur.length) parts.push(cur);
      return parts;
    };
    const overall = segments((rec) => rec.hist?.overall);
    for (const part of overall) {
      svg.append(s("path", { class: "line ink", d: part.map(([i, v], k) => `${k ? "L" : "M"}${x(i)},${y(v)}`).join("") }));
    }
    const last = overall.length ? overall[overall.length - 1][overall[overall.length - 1].length - 1] : null;
    if (last) svg.append(s("circle", { class: "dot ink", cx: x(last[0]), cy: y(last[1]), r: 4 }));

    // element tiers: set in the seasons of the element, held until the next one
    const steps = own.slice(0, 2).map((element, k) => {
      const cls = `own${k + 1}`;
      // a step line runs from each update to the next one on the same side of the treasure
      const updates = [];
      records.forEach((rec, i) => {
        if (rec.hist?.counted && rec.season.weak === element && !Number.isNaN(rec.hist.elementLift)) updates.push([i, rec.hist.elementLift]);
      });
      const g = s("g", { class: `step ${cls}` });
      updates.forEach(([i, v], j) => {
        const sideEnd = firstTreasure > 0 && i < firstTreasure ? firstTreasure - 1 : n - 1;
        const next = updates[j + 1] && updates[j + 1][0] <= sideEnd ? updates[j + 1] : null;
        const to = next ? next[0] : sideEnd;
        let d = `M${x(i)},${y(v)}H${x(to)}`;
        if (next) d += `V${y(next[1])}`;
        g.append(s("path", { class: `line ${cls}`, d }));
      });
      for (const [i, v] of updates) g.append(s("circle", { class: `dot ${cls}`, cx: x(i), cy: y(v), r: 4 }));
      svg.append(g);
      return { element, cls, updates };
    });

    // the treasure
    if (firstTreasure > 0) {
      const tx = m.l + band * firstTreasure;
      svg.append(s("line", { class: "treasure", x1: tx, x2: tx, y1: m.t - 6, y2: base }));
      svg.append(s("text", { class: "treasure-mark", x: tx, y: m.t - 9, "text-anchor": "middle" }, "♥"));
    }

    // the x axis: season numbers, and the weak element of each season when there is room
    const every = Math.max(1, Math.ceil(26 / band));
    const labelled = [];
    records.forEach((rec, i) => {
      if (i !== 0 && i !== n - 1 && rec.season.season % every !== 0) return;
      if (labelled.length && x(i) - x(labelled[labelled.length - 1]) < 24) {
        if (i !== n - 1) return;
        if (labelled.length > 1) labelled.pop();
        else return;
      }
      labelled.push(i);
    });
    const axis = s("g", { class: "xaxis" });
    records.forEach((rec, i) => {
      if (labelled.includes(i)) {
        axis.append(s("text", { class: "ax", x: x(i), y: base + (band >= 13 ? 32 : 16), "text-anchor": "middle" }, rec.season.season));
      }
      if (band >= 13) {
        axis.append(s("image", {
          href: `icons/elements/${rec.season.weak.toLowerCase()}.png`, x: x(i) - 5.5, y: base + 5, width: 11, height: 13,
          class: rec.row.elementMatch ? "wk on" : "wk",
        }));
      }
    });
    axis.append(s("text", { class: "ax", x: m.l - 8, y: base + (band >= 13 ? 32 : 16), "text-anchor": "end" }, "시즌"));
    svg.append(axis);

    // crosshair and the hit area: each season's whole band
    svg.append(s("line", { class: "cross", x1: 0, x2: 0, y1: m.t, y2: base, visibility: "hidden" }));
    const hit = s("rect", { class: "hit", x: m.l, y: 0, width: iw, height: H });
    svg.append(hit);
    const index = (clientX) => {
      const box = svg.getBoundingClientRect();
      return Math.max(0, Math.min(n - 1, Math.floor((clientX - box.left - m.l) / band)));
    };
    hit.addEventListener("pointermove", (e) => setHover(index(e.clientX), { x: e.clientX, y: e.clientY }));
    hit.addEventListener("pointerdown", (e) => setHover(index(e.clientX), { x: e.clientX, y: e.clientY }));
    hit.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") setHover(-1); });

    const pointsAt = (i) => {
      const out = [];
      const rec = records[i];
      if (rec.hist && !Number.isNaN(rec.hist.overall)) out.push(["ink", rec.hist.overall]);
      for (const st of steps) {
        const held = [...st.updates].reverse().find(([j]) => j <= i && (firstTreasure <= 0 || (j < firstTreasure) === (i < firstTreasure)));
        if (held) out.push([st.cls, held[1]]);
      }
      return out;
    };
    geometry = { svg, x, y, band, pointsAt };
    host.replaceChildren(svg);
    if (hover >= 0) setHover(hover);
  }

  host.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      setHover(Math.max(0, Math.min(records.length - 1, (hover < 0 ? records.length : hover) + (e.key === "ArrowRight" ? 1 : -1))));
    } else if (e.key === "Escape") setHover(-1);
  });
  host.addEventListener("blur", () => setHover(-1));

  let lastWidth = 0;
  const observer = new ResizeObserver(() => {
    const w = Math.floor(host.clientWidth);
    if (w && w !== lastWidth) { lastWidth = w; draw(); }
  });
  observer.observe(host);
  return root;
}
