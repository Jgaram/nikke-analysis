// 메타 변화 · 파워 인플레: every unit's 체급 (power.py, docs/power.md) by release date, and the field
// season by season - over all seasons (the 종합 체급: own and other seasons mixed by how often the boss
// was weak to the unit), or for one element (its units in their own seasons, the seasons weak to it). The 체급 is computed once when the site is built (data/power.json, the default
// parameters): the page's parameters move only the tier filter here, never the weights.
// It is a deck multiple - a floor under the unit's own damage multiple - and not a role.

import { assignTier, DAY_MS, ELEMENTS } from "../model.js";
import {
  h, s, num, int, day, elementIcon, unitName, face, showTip, moveTip, hideTip, sortableTable, segmented, infoButton, ELEMENT_KO,
} from "../ui.js";
import { lineChart, lineLegend } from "../linechart.js";
import { metaTabs, paramsNote, PARAM, unitInline, unitSearch } from "./common.js";
import { seasonTip } from "./meta.js";

// The views: "overall", or an element.
const viewName = (view) => (view === "overall" ? "종합" : ELEMENT_KO[view]);
// Every element a unit counts as before its treasure (the scatter's cells are before it).
const countsAs = (unit, element) => unit.element === element || (unit.extra || []).includes(element);
const YEAR_MS = 365.25 * DAY_MS;
const QUANTILES = [0.75, 0.9];
const TICKS = [0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1, 1.25, 1.5, 2, 2.5, 3, 4];

const help = (name, ...body) => h("div", { class: "tip tip-help" }, h("div", { class: "tip-name" }, name), ...body);
const times = (log) => (log == null ? "–" : `${num(Math.exp(log))}`);
// a year's later release, as a percent: +15%
const perYear = (b) => {
  if (b == null || Number.isNaN(b)) return "–";
  const p = Math.round(Math.expm1(b) * 100);
  return `${p >= 0 ? "+" : "−"}${Math.abs(p)}%`;
};

// ---------------------------------------------------------------------------
// fits: y = a + b x, least squares and quantiles (iteratively reweighted)

function leastSquares(xs, ys) {
  const n = xs.length;
  if (n < 3) return null;
  const mx = xs.reduce((a, v) => a + v, 0) / n;
  const my = ys.reduce((a, v) => a + v, 0) / n;
  let sxy = 0, sxx = 0;
  for (let i = 0; i < n; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) ** 2; }
  if (!sxx) return null;
  const b = sxy / sxx;
  return { a: my - b * mx, b };
}

function quantileFit(xs, ys, q) {
  let fit = leastSquares(xs, ys);
  if (!fit) return null;
  for (let it = 0; it < 300; it++) {
    let sw = 0, swx = 0, swy = 0, swxx = 0, swxy = 0;
    for (let i = 0; i < xs.length; i++) {
      const r = ys[i] - fit.a - fit.b * xs[i];
      const w = (r > 0 ? q : 1 - q) / Math.max(Math.abs(r), 1e-6);
      sw += w; swx += w * xs[i]; swy += w * ys[i]; swxx += w * xs[i] * xs[i]; swxy += w * xs[i] * ys[i];
    }
    const det = sw * swxx - swx * swx;
    if (!det) break;
    const next = { a: (swxx * swy - swx * swxy) / det, b: (sw * swxy - swx * swy) / det };
    const done = Math.abs(next.b - fit.b) < 1e-9 && Math.abs(next.a - fit.a) < 1e-9;
    fit = next;
    if (done) break;
  }
  return fit;
}

// ---------------------------------------------------------------------------
// the data

// Per unit index: the best season tier it ever reached (an index into the cuts), with the page's
// parameters. The filter's measure of "a raid unit in its day".
function bestTiers(app) {
  const cuts = app.state.params.cuts;
  const best = new Map();
  for (const season of app.population().summary) {
    for (const r of season.rows) {
      const k = cuts.findIndex(([l]) => l === assignTier(r.lift, cuts));
      if (k >= 0 && k < (best.get(r.u) ?? Infinity)) best.set(r.u, k);
    }
  }
  return best;
}

// The cells of a view before the treasure, as points: the unit, its release (years since launch),
// its log weight, and whether it is in the fits (well weighed and through the filter). Overall: every
// unit's 종합 체급; an element: its units' own-season 체급.
function points(app, data, view, floor, best = bestTiers(app)) {
  const { model } = app;
  const out = [];
  const cells = view === "overall" ? data.overall || [] : data.cells.filter((c) => c.own);
  for (const c of cells) {
    if (c.treasure || c.log == null) continue;
    const u = model.byId.get(c.unit);
    const unit = u != null ? model.units[u] : null;
    if (!unit || unit.release == null || (view !== "overall" && !countsAs(unit, view))) continue;
    const passes = floor == null || (best.get(u) ?? Infinity) <= floor;
    out.push({ c, u, unit, x: (unit.release - model.launch) / YEAR_MS, y: c.log, passes,
      fitted: passes && c.status === "ok", best: best.get(u) });
  }
  return out;
}

function fits(list) {
  const used = list.filter((p) => p.fitted);
  const xs = used.map((p) => p.x), ys = used.map((p) => p.y);
  return {
    n: used.length,
    mean: leastSquares(xs, ys),
    quantiles: QUANTILES.map((q) => ({ q, fit: quantileFit(xs, ys, q) })),
    span: used.length ? [Math.min(...xs), Math.max(...xs)] : null,
  };
}

// ---------------------------------------------------------------------------

function powerHelp(app, data) {
  return help("출시일과 체급",
    h("p", null, h("b", null, "체급 = 홍련 자리에 이 니케를 넣으면 덱 대미지가 몇 배가 되나"), " (홍련이 자기 속성 시즌에 쓰일 때 = 1). "
      + "같은 랭커의 다섯 덱끼리만 비교해서(계정 육성·실력·보스가 지워진다) 전 시즌 덱을 한 번에 풉니다. 시즌과 무관한 고정 값이고, "
      + "자기 속성 시즌 / 다른 속성 시즌, 애장품 전 / 뒤를 따로 잽니다. 이 그래프는 애장품 전입니다."),
    h("p", null, h("b", null, "종합"), " = 자기 속성 시즌 체급과 다른 속성 시즌 체급을, 지금까지 시즌 중 보스 약점이 그 니케 속성이었던 비율"
      + "로 섞은 것(로그로 가중 평균, 비율은 점에 올리면 나옵니다) — 시즌이 오는 대로 넣었을 때 평균 몇 배인가. "
      + "두 쪽이 다 재진 니케만 있습니다. ", h("b", null, "속성"), "을 고르면 그 속성 니케의 자기 속성 시즌 체급입니다."),
    h("p", null, "점 하나가 니케 하나(색 = 속성), 세로축은 로그 눈금입니다. 선 끝의 숫자는 출시가 1년 늦을 때 체급이 몇 % 높은가 — 이게 파워 인플레입니다. "
      + "평균선과, 그보다 위쪽을 따라가는 상위 25% · 상위 10% 선(분위 회귀)을 그립니다. 위쪽 선은 레이드에 거의 안 쓰인 니케가 아래에 깔려도 덜 흔들립니다."),
    h("p", null, "점을 누르면 아래 시즌별 파워 그래프에 그 니케가 같이 그려집니다."),
    h("p", { class: "muted" }, `덱 ${data.minDecks}개 이상이고 표준오차 ±${Math.round(data.maxSe * 100)}% 이하인 칸만 선에 넣습니다. 속이 빈 점은 잠정이거나, `
      + "늘 같이 쓰여 둘을 묶어서만 잴 수 있는 니케입니다(선에서 뺌). 덱에 한 번도 안 들어간 니케는 점이 없습니다(0이 아니라 모름)."),
    h("p", { class: "muted" }, `사이트를 만들 때 기본 설정으로 한 번 계산한 값입니다(덱 ${int(data.decks)}개). 자세한 건 docs/power.md.`));
}

function filterHelp() {
  return help("선에 넣을 니케",
    h("p", null, "레이드용이 아닌 니케를 빼 보려고, 어느 시즌에서든 시즌 티어를 그 이상 찍은 적 있는 니케만 선에 넣습니다. 빠진 니케는 흐리게 남깁니다."),
    h("p", null, "시즌 티어는 그 시즌 안의 몫이라 시대가 달라도 \"그때 레이드에서 쓰였나\"를 같은 뜻으로 묻습니다. 다만 체급과 독립은 아닙니다:"),
    h("ul", null,
      h("li", null, "같은 랭킹에서 나온 값이라 결과로 고르는 셈입니다."),
      h("li", null, "시즌 파워가 오를수록 같은 티어를 찍는 데 필요한 체급이 올라, 새 니케가 더 세게 걸러집니다(인플레를 키우는 쪽)."),
      h("li", null, "오래된 니케는 시즌을 많이 겪어 한 번이라도 높게 찍을 기회가 많습니다.")),
    h("p", { class: "muted" }, "필터를 바꿔 가며 선이 얼마나 움직이는지 보세요. 자기 속성 시즌은 거의 안 움직이고, 다른 속성 시즌은 꽤 움직입니다."),
    paramsNote([
      [PARAM.cuts, "시즌 티어 컷"],
      [PARAM.sample, "시즌 티어의 기여도 (체급은 그대로)"],
    ]));
}

function fieldHelp(data) {
  return help("시즌별 파워",
    h("p", null, `시즌마다 그 시즌 시작 때 나와 있던 니케의 그 시즌 체급(약점이 맞으면 자기 속성, 애장품이 있으면 애장품 뒤) 중 상위 ${data.top}칸의 평균(기하평균).`
      + " 속성을 고르면 보스 약점이 그 속성인 시즌만 그립니다."),
    h("p", null, "니케를 고르면 그 니케의 체급을 같이 그립니다 — 종합에서는 종합 체급, 속성에서는 그 시즌들에 쓰일 체급. "
      + "체급은 고정이라 선이 평평하고, 시즌 파워가 올라가면서 차이가 좁혀집니다 — "
      + "니케가 안 쓰이게 되는 건 체급이 줄어서가 아니라 더 센 니케가 들어와서입니다."),
    h("p", { class: "muted" }, "출시 뒤 경과별로 덱 대미지의 빗나감이 ±1% 안이고 추세가 없어, 체급을 고정으로 둔 것이 데이터로 받쳐집니다(docs/power.md)."));
}

// The warning on top: the 체급 is the roughest number on the site.
function caution() {
  return h("div", { class: "caution", role: "note" },
    h("p", null, h("b", null, "실험적인 지표입니다. "), "체급은 랭커들의 덱 대미지에서 거꾸로 추정한 값이라, 계산 방식 때문에 왜곡이 클 수 있습니다. "
      + "참고용으로만 봐 주세요."),
    h("details", null, h("summary", null, "왜 그런가"),
      h("ul", null,
        h("li", null, "덱 대미지를 다섯 멤버 체급의 곱으로 놓았습니다. 합으로 놓아도 데이터에 똑같이 맞아서, \"몇 배\"의 크기가 이 가정에 걸려 있습니다."),
        h("li", null, "덱 대미지 배수입니다. 니케 자기 딜이 몇 배인지가 아니라 그 하한이고, 역할(딜러·서포터)을 뜻하지 않습니다."),
        h("li", null, "랭커들이 실제로 한 자리만 바꾼 덱들로 맞혀 보면, 실제 차이가 예측의 0.74배쯤입니다 — 배수가 부풀어 있을 수 있습니다."),
        h("li", null, "늘 같이 쓰인 니케끼리는 체급을 나눠 갖습니다. 한쪽이 부풀고 다른 쪽이 줄 수 있습니다."),
        h("li", null, "덱은 랭커가 고른 것입니다. 가진 니케, 육성, 손에 맞는 조합 같은 이유는 데이터에 없습니다."),
        h("li", null, "보스마다 맞는 니케가 다른 것은 자기 / 다른 속성 시즌 두 갈래로만 나눕니다."),
        h("li", null, "상위 랭커가 덱에 넣은 니케만 잴 수 있습니다."),
        h("li", null, "사이트를 만들 때 기본 설정으로 한 번 계산한 값이라, 인자 패널은 시즌 티어 필터만 움직입니다."))));
}

// ---------------------------------------------------------------------------

export function powerView(app) {
  const { state } = app;
  const data = app.power;
  const root = h("div", { class: "view view-meta" }, metaTabs(app));
  if (!data || !data.cells?.length) {
    root.append(h("div", { class: "panel empty" }, "체급 데이터가 없습니다."));
    return root;
  }
  const view = state.powerView || "overall";
  const cuts = state.params.cuts;
  const labels = cuts.slice(0, Math.min(4, cuts.length - 1)).map(([l]) => l);
  const floor = state.powerFloor != null && state.powerFloor < labels.length ? state.powerFloor : null;
  const best = bestTiers(app);
  const list = points(app, data, view, floor, best);
  // every view's inflation (the mean line) on its button
  const rate = (v) => perYear((v === view ? fits(list) : fits(points(app, data, v, floor, best))).mean?.b);

  root.append(
    caution(),
    h("div", { class: "toolbar" },
      segmented(["overall", ...ELEMENTS].map((value) => ({
        value, icon: value === "overall" ? null : elementIcon(value, 15), label: `${viewName(value)} ${rate(value)}`,
        title: value === "overall" ? "모든 니케의 종합 체급 · 모든 시즌 — 출시 1년당 체급(평균선)"
          : `${ELEMENT_KO[value]} 니케의 자기 속성 시즌 체급 · ${ELEMENT_KO[value]} 약점 시즌 — 출시 1년당 체급(평균선)`,
      })), view, (v) => { state.powerView = v; app.rerender(); }, { label: "종합 또는 속성", class: "wrap" }),
      h("span", { class: "head-title" },
        segmented([{ value: null, label: "전체", title: "잘 잰 니케 모두" },
          ...labels.map((l, k) => ({ value: k, label: `${l} 이상`, title: `어느 시즌에서든 시즌 티어 ${l} 이상을 찍은 적 있는 니케만` }))],
        floor, (v) => { state.powerFloor = v; app.rerender(); }, { label: "선에 넣을 니케" }),
        infoButton("선에 넣을 니케", () => filterHelp()))),
    scatterPanel(app, data, view, list),
    fieldPanel(app, data, view),
    tablePanel(app, data, view),
  );
  return root;
}

// ---------------------------------------------------------------------------
// the scatter: release date x 체급, one dot per unit, and the fitted lines

function scatterPanel(app, data, view, list) {
  const { model, state } = app;
  const f = fits(list);
  const host = h("div", { class: "chart-host lc-host", style: { minHeight: "320px" }, role: "img",
    "aria-label": `니케마다 출시일과 ${view === "overall" ? "종합" : `${ELEMENT_KO[view]} 니케의 자기 속성 시즌`} 체급` });
  const lines = [
    { name: "평균", cls: "mean", fit: f.mean },
    ...f.quantiles.map(({ q, fit }) => ({ name: `상위 ${Math.round((1 - q) * 100)}%`, cls: `q${Math.round(q * 100)}`, fit })),
  ];
  if (!list.length) return h("section", { class: "panel empty" }, "잰 니케가 없습니다.");
  const ys = list.map((p) => p.y);
  const lo = Math.log(0.8) > Math.min(...ys) ? Math.min(...ys) - 0.05 : Math.log(0.8);
  const hi = Math.max(...ys) + 0.05;
  const xs = list.map((p) => p.x);
  const x0 = Math.min(...xs) - 0.08, x1 = Math.max(...xs) + 0.08;
  let lastWidth = 0;

  function draw() {
    const width = Math.max(300, Math.floor(host.clientWidth));
    const height = 350;
    const narrow = width < 560;
    const m = { l: narrow ? 36 : 44, r: narrow ? 40 : 64, t: 26, b: 30 };
    const iw = width - m.l - m.r, ih = height - m.t - m.b;
    const x = (v) => m.l + iw * (v - x0) / (x1 - x0);
    const y = (v) => m.t + ih * (1 - (v - lo) / (hi - lo));
    const svg = s("svg", { width, height, viewBox: `0 0 ${width} ${height}`, class: "traj power-dots" });
    for (const t of TICKS) {
      const v = Math.log(t);
      if (v < lo || v > hi) continue;
      svg.append(s("line", { class: t === 1 ? "axis" : "grid", x1: m.l, x2: m.l + iw, y1: y(v), y2: y(v) }),
        s("text", { class: "ax", x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, String(t)));
    }
    svg.append(s("text", { class: "ax", x: m.l - 6, y: m.t - 10, "text-anchor": "end" }, "배"),
      s("text", { class: "ax", x: m.l + 2, y: m.t - 10 }, "홍련 = 1"));
    // the years
    const launch = new Date(model.launch);
    for (let year = launch.getUTCFullYear() + 1; ; year++) {
      const at = (Date.UTC(year, 0, 1) - 9 * 3600e3 - model.launch) / YEAR_MS;
      if (at > x1) break;
      if (at < x0) continue;
      svg.append(s("line", { class: "grid", x1: x(at), x2: x(at), y1: m.t, y2: m.t + ih }),
        s("text", { class: "ax", x: x(at), y: m.t + ih + 18, "text-anchor": "middle" }, String(year)));
    }
    svg.append(s("text", { class: "ax", x: m.l - 8, y: m.t + ih + 18, "text-anchor": "end" }, "출시"));

    // dots: out of the lines faint, provisional and pairs hollow, the chosen unit ringed; units out
    // on one day (the launch roster) spread sideways a little
    const order = [...list].sort((a, b) => Number(a.fitted) - Number(b.fitted));
    const sameDay = new Map();
    for (const p of [...list].sort((a, b) => a.y - b.y)) sameDay.set(p.unit.release, [...(sameDay.get(p.unit.release) || []), p]);
    for (const p of order) {
      const cls = ["dot-unit", !p.passes && "out", p.c.status !== "ok" && "hollow", state.powerUnit === p.u && "on"].filter(Boolean).join(" ");
      const group = sameDay.get(p.unit.release);
      const shift = group.length > 1 ? ((group.indexOf(p) % 5) - 2) * 3 : 0;
      const dot = s("g", { class: cls, tabindex: "0", role: "button", "aria-label": `${unitName(p.unit)} ${times(p.y)}`,
        style: { color: `var(--el-${p.unit.element})` } },
      s("circle", { cx: x(p.x) + shift, cy: y(p.y), r: state.powerUnit === p.u ? 6.5 : 4.5 }));
      const tip = () => unitTip(app, data, p.u, p.c, state.params.cuts, p.best);
      dot.addEventListener("pointerenter", (e) => showTip(host, tip(), { x: e.clientX, y: e.clientY }));
      dot.addEventListener("pointermove", (e) => moveTip(host, { x: e.clientX, y: e.clientY }));
      dot.addEventListener("pointerleave", () => hideTip(host));
      const choose = () => { state.powerUnit = state.powerUnit === p.u ? null : p.u; app.rerender(); };
      dot.addEventListener("click", choose);
      dot.addEventListener("keydown", (e) => { if (e.key === "Enter") choose(); });
      svg.append(dot);
    }

    // the lines over the span of the units they were fitted to, named at their right end
    if (f.span) {
      const [a, b] = f.span;
      const ends = [];
      for (const line of lines) {
        if (!line.fit) continue;
        const ya = line.fit.a + line.fit.b * a, yb = line.fit.a + line.fit.b * b;
        svg.append(s("line", { class: `fit ${line.cls}`, x1: x(a), x2: x(b), y1: y(ya), y2: y(yb) }));
        ends.push({ line, y: y(yb) });
      }
      ends.sort((p, q) => p.y - q.y);
      for (let j = 1; j < ends.length; j++) if (ends[j].y - ends[j - 1].y < 13) ends[j].y = ends[j - 1].y + 13;
      for (const e of ends) {
        svg.append(s("text", { class: `ax end-label fit-label ${e.line.cls}`, x: x(b) + 8, y: e.y + 4 },
          `${perYear(e.line.fit.b)}${narrow ? "" : "/년"}`));
      }
    }
    host.replaceChildren(svg);
  }
  new ResizeObserver(() => {
    const w = Math.floor(host.clientWidth);
    if (w && w !== lastWidth) { lastWidth = w; draw(); }
  }).observe(host);

  return h("section", { class: "panel chart-panel" },
    h("div", { class: "panel-head" },
      h("span", { class: "head-title" }, h("h3", null, `출시일과 체급 · ${view === "overall" ? "종합" : `${ELEMENT_KO[view]} · 자기 속성 시즌`}`), infoButton("출시일과 체급", () => powerHelp(app, data)))),
    h("div", { class: "legend" },
      ...lines.map((l) => h("span", { class: "lg" }, h("i", { class: `sw line fit-sw ${l.cls}` }), l.name)),
      h("span", { class: "lg" }, h("i", { class: "sw dot-sw hollow" }), "잠정")),
    host);
}

function unitTip(app, data, u, cell, cutList, best) {
  const unit = app.model.units[u];
  const mine = data.cells.filter((c) => c.unit === unit.id);
  const row = (own, treasure) => mine.find((c) => c.own === own && c.treasure === treasure);
  const whole = (treasure) => overallOf(data, unit.id, treasure);
  const value = (c) => (!c ? "–" : c.status === "pair" ? `${partnerName(app, c)}와 묶어서 ${times(c.pairLog)}배`
    : `${times(c.log)}배${c.status === "provisional" ? " (잠정)" : ""}`);
  const lines = [
    ["출시", day(unit.release)],
    ["종합", value(whole(false)) + (whole(false) ? ` · 자기 속성 시즌 ${Math.round(whole(false).share * 100)}%` : "")],
    ["자기 속성 시즌", value(row(true, false))],
  ];
  if (row(true, true) || whole(true)) lines.push(["애장품 뒤 종합", value(whole(true))], ["애장품 뒤 자기", value(row(true, true))]);
  lines.push(["최고 시즌 티어", best != null ? cutList[best][0] : "–"]);
  return h("div", { class: "tip" },
    h("div", { class: "tip-name" }, face(unit, 28), unitName(unit), elementIcon(unit.element, 14)),
    h("dl", { class: "tip-list" }, lines.flatMap(([k, v]) => [h("dt", null, k), h("dd", null, v)])));
}

function overallOf(data, id, treasure) {
  return (data.overall || []).find((c) => c.unit === id && c.treasure === treasure);
}

function partnerName(app, c) {
  const u = c.partner != null ? app.model.byId.get(c.partner) : null;
  return u != null ? unitName(app.model.units[u]) : "?";
}

// ---------------------------------------------------------------------------
// the field season by season, and one unit's flat line against it

function fieldPanel(app, data, view) {
  const { model, state } = app;
  const pop = app.population();
  const field = new Map(data.field);
  const seasons = pop.summary.filter((s0) => field.has(s0.season) && (view === "overall" || s0.weak === view));
  const u = state.powerUnit;
  const unit = u != null ? model.units[u] : null;
  const mine = unit ? data.cells.filter((c) => c.unit === unit.id) : [];
  const treasureFrom = unit ? data.treasureFrom[unit.id] ?? null : null;
  // the unit's 체급 that season: overall its 종합, an element the cell it plays then (own when the
  // boss is weak to it); after its treasure the treasure's, else the one before
  const weightIn = (s0) => {
    const treasure = treasureFrom != null && s0.season >= treasureFrom;
    let c;
    if (view === "overall") c = overallOf(data, unit.id, treasure) || overallOf(data, unit.id, false);
    else {
      const own = s0.rows.find((r) => r.u === u)?.elementMatch ?? countsAs(unit, view);
      c = mine.find((x) => x.own === own && x.treasure === treasure) || mine.find((x) => x.own === own && !x.treasure);
    }
    return c && c.log != null && c.status !== "pair" ? Math.exp(c.log) : null;
  };
  const out = (s0) => unit && unit.release != null && s0.start != null && unit.release <= s0.start;
  const series = [{ name: "시즌 파워", cls: "field", values: seasons.map((s0) => field.get(s0.season)) }];
  if (unit) {
    const values = seasons.map((s0) => (out(s0) ? weightIn(s0) : null));
    if (values.some((v) => v != null)) series.push({ name: view === "overall" ? "종합 체급" : "체급", cls: "own", values });
  }
  if (!seasons.length) return h("section", { class: "panel empty" }, `${viewName(view)} 약점 시즌이 없습니다.`);
  // not from 0: the field moves by tenths
  const shownValues = series.flatMap((x) => x.values.filter((v) => v != null));
  const max = Math.ceil(Math.max(...shownValues) * 4 + 0.4) / 4;
  const min = Math.max(0, Math.floor(Math.min(...shownValues) * 4 - 0.4) / 4);
  const ticks = Array.from({ length: Math.round((max - min) / 0.25) + 1 }, (_, i) => min + i * 0.25);
  const chosen = state.season != null ? seasons.findIndex((s0) => s0.season === state.season) : -1;
  const picker = unitSearch(app, {
    placeholder: "니케 찾기", choose: (v) => { state.powerUnit = v; app.rerender(); },
    order: [...new Set(data.cells.map((c) => model.byId.get(c.unit)).filter((v) => v != null))]
      .sort((a, b) => unitName(model.units[a]).localeCompare(unitName(model.units[b]), "ko")),
  });
  return h("section", { class: "panel chart-panel" },
    h("div", { class: "panel-head" },
      h("span", { class: "head-title" }, h("h3", null, view === "overall" ? "시즌별 파워" : `시즌별 파워 · ${ELEMENT_KO[view]} 약점 시즌`),
        infoButton("시즌별 파워", () => fieldHelp(data))),
      picker,
      unit ? h("span", { class: "power-unit" }, unitInline(app, u, { size: 24 }),
        h("button", { type: "button", class: "btn small ghost", onclick: () => { state.powerUnit = null; app.rerender(); } }, "빼기")) : null,
    ),
    lineLegend(series),
    lineChart({
      points: seasons.map((s0) => ({ label: s0.season })), series, min, max, ticks, height: 240, mark: chosen >= 0 ? chosen : null,
      format: (v) => num(v), label: "시즌별 파워(쓸 수 있던 상위 칸의 평균 체급)",
      tip: (i) => {
        const s0 = seasons[i];
        const f = field.get(s0.season);
        const lines = [["시즌 파워", num(f)]];
        const v = unit && out(s0) ? weightIn(s0) : null;
        if (v != null) lines.push([view === "overall" ? "종합 체급" : "이 시즌 체급", `${num(v)} · 시즌 파워의 ${num(v / f)}배`]);
        return seasonTip({ season: s0 }, lines);
      },
    }));
}

// ---------------------------------------------------------------------------

function tablePanel(app, data, view) {
  const { model, state } = app;
  const byUnit = new Map();
  const add = (id, key, c) => { if (!byUnit.has(id)) byUnit.set(id, {}); byUnit.get(id)[key] = c; };
  for (const c of data.cells) if (c.own) add(c.unit, `own${c.treasure ? "T" : ""}`, c);
  for (const c of data.overall || []) add(c.unit, `overall${c.treasure ? "T" : ""}`, c);
  const decks = new Map();
  for (const c of data.cells) decks.set(c.unit, (decks.get(c.unit) || 0) + c.decks);
  const rows = [...byUnit.entries()].map(([id, cells]) => ({ u: model.byId.get(id), cells, decks: decks.get(id) || 0 }))
    .filter((r) => r.u != null).map((r) => ({ ...r, unit: model.units[r.u] }))
    .filter((r) => view === "overall" || countsAs(r.unit, view));
  const value = (c) => (c && c.status !== "pair" && c.log != null ? Math.exp(c.log) : null);
  const shown = (c) => (!c ? h("span", { class: "muted" }, "–") : c.status === "pair" ? h("span", { class: "muted", title: `짝 ${partnerName(app, c)}과 둘이 ${times(c.pairLog)}` }, "짝")
    : h("span", { class: c.status === "provisional" ? "muted" : null }, `${times(c.log)}${c.status === "provisional" ? "?" : ""}`));
  const sort = state.sort.power || { key: view === "overall" ? "overall" : "own", dir: "desc" };
  const columns = [
    { key: "name", label: "니케", head: true, sort: (r) => unitName(r.unit), cell: (r) => unitInline(app, r.u, { size: 24 }) },
    { key: "release", label: "출시", num: true, sort: (r) => r.unit.release, cell: (r) => day(r.unit.release) },
    ...[["overall", "종합"], ["own", "자기 속성"], ["overallT", "애장품 뒤 종합"], ["ownT", "애장품 뒤 자기"]].map(([key, label]) => ({
      key, label, num: true, sort: (r) => value(r.cells[key]), cell: (r) => shown(r.cells[key]) })),
    { key: "decks", label: "덱", num: true, sort: (r) => r.decks, cell: (r) => int(r.decks) },
  ];
  return h("details", { class: "panel table-panel meta-table" },
    h("summary", null, h("h3", null, view === "overall" ? "숫자로 보기" : `숫자로 보기 · ${ELEMENT_KO[view]} 니케`)),
    h("p", { class: "muted small table-note" }, `덱에 들어간 니케 ${rows.length}명 · ? = 잠정 · 짝 = 늘 같이 쓰여 둘을 묶어서만 잼 · `
      + "종합 – = 자기·다른 속성 시즌 중 한쪽이 안 재짐"),
    sortableTable(columns, rows, {
      sortKey: sort.key, sortDir: sort.dir, caption: "니케별 체급",
      onSort: (key, dir) => { state.sort.power = { key, dir }; app.rerender(); },
    }));
}
