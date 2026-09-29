// 메타 변화: season by season, how far the units in use follow the boss's weakness (model.js
// metaTrend, debuts, curves; analyze/meta.py). Not roles: a unit used only in its own element's
// seasons may be dealing the damage there or giving that element's decks what they need.

import { GENERALITY_MAX, DAY_MS } from "../model.js";
import { h, s, num, pct, elementIcon, ELEMENT_KO, unitName, face, showTip, moveTip, hideTip, sortableTable, segmented } from "../ui.js";
import { lineChart, lineLegend } from "../linechart.js";
import { CURVE_KO, CURVE_HINT } from "./common.js";

const MIX = [
  { key: "specialist", name: "특화", cls: "mix0" },
  { key: "element_first", name: "속성 우선", cls: "mix1" },
  { key: "generalist", name: "범용", cls: "mix2" },
];
const SHOWN_CURVES = ["specialist", "narrowed", "faded", "general"];

export function metaView(app) {
  const { state } = app;
  const params = state.params;
  const rows = app.metaTrend();
  const root = h("div", { class: "view view-meta" });
  if (!rows.length) {
    root.append(h("div", { class: "panel empty" }, "시즌이 아직 없습니다."));
    return root;
  }
  const first = rows[0].season.start;
  const full = (r) => r.season.start - first >= params.metaWindowDays * DAY_MS;
  const chosen = state.season != null ? rows.findIndex((r) => r.season.season === state.season) : -1;
  const markAt = chosen >= 0 ? chosen : null;
  const upTo = markAt ?? rows.length - 1;
  const points = rows.map((r) => ({ label: r.season.season }));

  root.append(intro(app, rows, full, upTo));
  root.append(mixPanel(app, rows, full, points, markAt));
  root.append(followPanel(app, rows, points, markAt));
  root.append(debutPanel(app));
  root.append(cohortPanel(app));
  root.append(tablePanel(app, rows, full));
  return root;
}

// ---------------------------------------------------------------------------

const seasonName = (r) => `S${r.season.season}`;

function intro(app, rows, full, upTo) {
  const params = app.state.params;
  const then = rows.find(full) || rows[0];
  const now = rows[upTo];
  const early = rows.filter((r) => !Number.isNaN(r.similarity)).slice(0, 10);
  const late = rows.slice(0, upTo + 1).filter((r) => !Number.isNaN(r.similarity)).slice(-10);
  const mean = (list, f) => list.reduce((a, r) => a + f(r), 0) / Math.max(list.length, 1);
  const share = (r, k) => (r.units ? r[k] / r.units : NaN);
  const tile = (label, a, b, sub) => h("div", { class: "meta-tile" },
    h("div", { class: "mt-label" }, label), h("div", { class: "mt-value" }, a, h("small", null, "→ "), b), h("div", { class: "mt-sub" }, sub));
  return h("section", { class: "panel meta-intro" },
    h("div", { class: "panel-head" }, h("h3", null, "메타 변화"),
      h("span", { class: "muted small" }, `${seasonName(then)} → ${seasonName(now)} · 쓰인 니케 = 시즌 티어 ${params.curveMinTier} 이상`)),
    h("p", null, "시즌마다, 그때까지 ", h("b", null, `${params.metaWindowDays}일`), " 동안 쓰인 니케를 그 기간의 범용도(자기 속성 시즌 기여도와 "
      + "다른 속성 시즌 기여도의 비율)로 나눠 셉니다. 특화가 늘고 범용이 줄면 메타가 보스 약점을 더 따르게 된 것입니다. "
      + "역할(딜러·서포터)이 아니라 쓰임의 모양입니다 — 속성 시즌에만 쓰이는 건 딜 때문일 수도, 그 속성 덱에 주는 버프 때문일 수도 있습니다."),
    h("div", { class: "meta-tiles" },
      tile("쓰인 니케 중 특화", pct(share(then, "specialist")), pct(share(now, "specialist")),
        `${then.specialist}명 / ${then.units}명 → ${now.specialist}명 / ${now.units}명`),
      tile("범용 니케 수", `${then.generalist}명`, `${now.generalist}명`, `쓰인 니케 중 ${pct(share(then, "generalist"))} → ${pct(share(now, "generalist"))}`),
      tile("약점 교차 유사도", num(mean(early, (r) => r.similarity)), num(mean(late, (r) => r.similarity)),
        "처음 10시즌 평균 → 최근 10시즌 평균 · 1 = 약점이 바뀌어도 같은 니케"),
      tile("약점 속성 니케의 몫", pct(mean(rows.slice(0, 10), (r) => r.ownShare)), pct(mean(rows.slice(Math.max(0, upTo - 9), upTo + 1), (r) => r.ownShare)),
        "처음 10시즌 평균 → 최근 10시즌 평균 · 20% = 약점과 무관")));
}

function seasonTip(r, lines) {
  const info = r.season.info;
  return h("div", { class: "tip" },
    h("div", { class: "tip-name" }, `시즌 ${info.season}`, h("span", { class: "muted" }, info.bossKo || info.bossEn || "")),
    h("div", { class: "tip-attrs" }, "약점 ", elementIcon(info.weak, 14), ELEMENT_KO[info.weak] || "?",
      !r.season.final ? h("span", { class: "muted" }, " · 진행 중") : null),
    h("dl", { class: "tip-list" }, lines.flatMap(([k, v]) => [h("dt", null, k), h("dd", null, v)])));
}

function mixPanel(app, rows, full, points, markAt) {
  const params = app.state.params;
  const mode = app.state.metaMix || "count";
  const value = (r, k) => (!full(r) ? null : mode === "count" ? r[k] : r.units ? r[k] / r.units : null);
  const series = MIX.map((m) => ({ ...m, values: rows.map((r) => value(r, m.key)) }));
  const top = mode === "count" ? Math.max(10, ...rows.filter(full).map((r) => r.units)) : 1;
  const max = mode === "count" ? Math.ceil(top / 10) * 10 : 1;
  const ticks = mode === "count" ? Array.from({ length: max / 10 + 1 }, (_, i) => i * 10).filter((v, i, a) => a.length <= 9 || i % 2 === 0)
    : [0, 0.25, 0.5, 0.75, 1];
  const [low, high] = params.generalityBands;
  const toggle = segmented([{ value: "count", label: "명" }, { value: "share", label: "비율" }], mode,
    (v) => { app.state.metaMix = v; app.rerender(); }, { label: "명 또는 비율" });
  return h("section", { class: "panel chart-panel" },
    h("div", { class: "panel-head" }, h("h3", null, "쓰인 니케의 범용도"), toggle,
      h("span", { class: "muted small" }, `시즌마다 그때까지 ${params.metaWindowDays}일 · 특화 < ${num(low)} ≤ 속성 우선 < ${num(high)} ≤ 범용 · 첫 ${params.metaWindowDays}일은 기간이 덜 차서 비움`)),
    lineLegend(series, { stacked: true }),
    lineChart({
      points, series, stacked: true, max, ticks, mark: markAt, height: 240,
      format: mode === "count" ? (v) => String(v) : (v) => `${Math.round(v * 100)}%`,
      label: "시즌별로 쓰인 니케를 특화·속성 우선·범용으로 나눈 누적 그래프",
      tip: (i) => {
        const r = rows[i];
        if (!full(r)) return seasonTip(r, [["", `아직 ${params.metaWindowDays}일이 차지 않음`]]);
        return seasonTip(r, [...MIX.map((m) => [m.name, `${r[m.key]}명 (${pct(r[m.key] / r.units)})`]), ["쓰인 니케", `${r.units}명`]]);
      },
    }));
}

function followPanel(app, rows, points, markAt) {
  const series = [
    { name: "교차 유사도", cls: "own", values: rows.map((r) => (Number.isNaN(r.similarity) ? null : r.similarity)) },
    { name: "약점 속성 몫", cls: "other", values: rows.map((r) => r.ownShare) },
  ];
  return h("section", { class: "panel chart-panel" },
    h("div", { class: "panel-head" }, h("h3", null, "약점을 따르는 정도"),
      h("span", { class: "muted small" }, "교차 유사도 = 그 시즌의 기여도가 약점이 다른 앞 시즌 네 개와 얼마나 같은가(1 = 약점이 바뀌어도 같은 니케) · "
        + "약점 속성 몫 = 그 시즌 기여도 중 약점 속성 니케가 가져간 비율(20% = 약점과 무관)")),
    lineLegend(series),
    lineChart({
      points, series, max: 1, ticks: [0, 0.2, 0.4, 0.6, 0.8, 1], mark: markAt, height: 220, format: (v) => num(v, 1),
      label: "시즌별 약점 교차 유사도와 약점 속성 니케의 기여도 몫",
      tip: (i) => seasonTip(rows[i], [["약점 교차 유사도", Number.isNaN(rows[i].similarity) ? "–" : num(rows[i].similarity)],
        ["약점 속성 몫", pct(rows[i].ownShare)]]),
    }));
}

// Each unit in use in its first year, by the season it came in and how general that year was.
function debutPanel(app) {
  const { model, state } = app;
  const params = state.params;
  const list = app.debuts().filter((d) => !Number.isNaN(d.generality));
  const pop = app.population();
  const seasons = pop.summary;
  const host = h("div", { class: "chart-host lc-host", style: { minHeight: "260px" }, role: "img",
    "aria-label": "니케마다 첫 1년의 범용도, 처음 쓰인 시즌 순" });
  const [low, high] = params.generalityBands;
  let lastWidth = 0;
  function draw() {
    const width = Math.max(300, Math.floor(host.clientWidth));
    const height = 260;
    const m = { l: 40, r: 70, t: 14, b: 30 };
    const iw = width - m.l - m.r, ih = height - m.t - m.b;
    const n = seasons.length;
    const step = iw / Math.max(n, 1);
    const pos = new Map(seasons.map((s0, i) => [s0.season, i]));
    const x = (season) => m.l + step * ((pos.get(season) ?? 0) + 0.5);
    const y = (v) => m.t + ih * (1 - Math.min(v, GENERALITY_MAX) / GENERALITY_MAX);
    const svg = s("svg", { width, height, viewBox: `0 0 ${width} ${height}`, class: "traj gen debut-dots" });
    [[0, low, "특화"], [low, high, "속성 우선"], [high, GENERALITY_MAX, "범용"]].forEach(([a, b, name], k) => {
      svg.append(s("rect", { class: `zone z${k}`, x: m.l, y: y(b), width: iw, height: y(a) - y(b) }));
      if (y(a) - y(b) >= 16) svg.append(s("text", { class: `ax zone-label z${k}`, x: m.l + iw + 8, y: (y(a) + y(b)) / 2 + 4 }, name));
    });
    for (const v of [0, 1, GENERALITY_MAX]) {
      svg.append(s("line", { class: v === 0 ? "axis" : "grid", x1: m.l, x2: m.l + iw, y1: y(v), y2: y(v) }));
      svg.append(s("text", { class: "ax", x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, String(v)));
    }
    // several units in one season spread sideways a little
    const bySeason = new Map();
    for (const d of list) bySeason.set(d.first, [...(bySeason.get(d.first) || []), d]);
    for (const [season, group] of bySeason) {
      group.forEach((d, k) => {
        const unit = model.units[d.u];
        const cx = x(season) + (k - (group.length - 1) / 2) * Math.min(7, step / Math.max(group.length, 1));
        const dot = s("g", { class: "dot-unit", tabindex: "0", role: "link", "aria-label": unitName(unit) },
          s("circle", { cx, cy: y(d.generality), r: 5, style: { fill: `var(--el-${unit.element})` } }));
        const tip = () => h("div", { class: "tip" },
          h("div", { class: "tip-name" }, face(unit, 28), unitName(unit)),
          h("dl", { class: "tip-list" },
            h("dt", null, "처음 쓰인 시즌"), h("dd", null, `S${d.first}`),
            h("dt", null, "첫 1년 범용도"), h("dd", null, num(d.generality)),
            h("dt", null, "자기 속성 · 다른 속성"), h("dd", null, `${num(d.own)} · ${num(d.other)}`)));
        dot.addEventListener("pointerenter", (e) => showTip(host, tip(), { x: e.clientX, y: e.clientY }));
        dot.addEventListener("pointermove", (e) => moveTip(host, { x: e.clientX, y: e.clientY }));
        dot.addEventListener("pointerleave", () => hideTip(host));
        dot.addEventListener("click", () => app.go({ tab: "trend", trend: "unit", unit: d.u }));
        dot.addEventListener("keydown", (e) => { if (e.key === "Enter") app.go({ tab: "trend", trend: "unit", unit: d.u }); });
        svg.append(dot);
      });
    }
    const every = Math.max(1, Math.ceil(28 / step));
    seasons.forEach((s0, i) => {
      if (i !== 0 && i !== n - 1 && i % every !== 0) return;
      svg.append(s("text", { class: "ax", x: m.l + step * (i + 0.5), y: y(0) + 18, "text-anchor": "middle" }, s0.season));
    });
    svg.append(s("text", { class: "ax", x: m.l - 8, y: y(0) + 18, "text-anchor": "end" }, "시즌"));
    host.replaceChildren(svg);
  }
  new ResizeObserver(() => {
    const w = Math.floor(host.clientWidth);
    if (w && w !== lastWidth) { lastWidth = w; draw(); }
  }).observe(host);
  return h("section", { class: "panel chart-panel" },
    h("div", { class: "panel-head" }, h("h3", null, "새 니케의 첫 1년"),
      h("span", { class: "muted small" }, `점 하나가 니케 하나(색 = 속성) · 처음 쓰인 시즌부터 ${params.metaWindowDays}일 동안의 범용도 · `
        + `그 기간이 끝났고 시즌 티어 ${params.curveMinTier} 이상으로 쓰인 니케 ${list.length}명 · 누르면 그 니케로`)),
    host);
}

// The curves of the units that came in each ten seasons, as known now (or on the chosen season).
function cohortPanel(app) {
  const view = app.viewAt(app.moment());
  const eras = new Map();
  const latest = app.latestSeason();
  for (const [u, c] of view.curves) {
    const a = view.life.get(u);
    if (!a || a.firstUsed == null) continue;
    const lo = Math.floor((a.firstUsed - 1) / 10) * 10 + 1;
    const key = lo + 9 >= latest ? `S${lo}–` : `S${lo}–${lo + 9}`;
    if (!eras.has(key)) eras.set(key, { lo, counts: {} });
    const e = eras.get(key);
    e.counts[c.curve] = (e.counts[c.curve] || 0) + 1;
  }
  const list = [...eras.entries()].sort((a, b) => a[1].lo - b[1].lo);
  const legend = h("div", { class: "legend" }, SHOWN_CURVES.map((k) =>
    h("span", { class: "lg", title: CURVE_HINT[k] }, h("i", { class: `sw zone s-${k}` }), CURVE_KO[k])));
  return h("section", { class: "panel chart-panel" },
    h("div", { class: "panel-head" }, h("h3", null, "데뷔 시기별 생애 곡선"),
      h("span", { class: "muted small" }, `처음 쓰인 시즌(시즌 티어 ${app.state.params.minTier} 이상)으로 10시즌씩 묶어, 지금까지의 생애 곡선을 셈 · 최근 데뷔일수록 아직 곡선이 덜 그려짐`)),
    legend,
    h("div", { class: "cohort" }, list.map(([key, e]) => {
      const shown = SHOWN_CURVES.reduce((a, k) => a + (e.counts[k] || 0), 0);
      return h("div", { class: "cohort-row" },
        h("b", null, key),
        h("div", { class: "cohort-bar", role: "img", "aria-label": SHOWN_CURVES.map((k) => `${CURVE_KO[k]} ${e.counts[k] || 0}명`).join(", ") },
          SHOWN_CURVES.filter((k) => e.counts[k]).map((k) => h("span", { class: `cohort-seg s-${k}`,
            style: { flex: `${e.counts[k]} 1 0` }, title: `${CURVE_KO[k]} ${e.counts[k]}명` }, String(e.counts[k])))),
        h("span", { class: "cohort-rest" }, `${shown}명`,
          e.counts.unknown ? ` · 아직 모름 ${e.counts.unknown}` : "", e.counts.unused ? ` · 안 쓰임 ${e.counts.unused}` : ""));
    })));
}

function tablePanel(app, rows, full) {
  const state = app.state;
  const sort = state.sort.meta || { key: "season", dir: "desc" };
  const columns = [
    { key: "season", label: "시즌", num: true, head: true, sort: (r) => r.season.season, cell: (r) => `S${r.season.season}` },
    { key: "weak", label: "약점", sort: (r) => r.season.weak, cell: (r) => elementIcon(r.season.weak, 15) },
    ...MIX.map((m) => ({ key: m.key, label: m.name, num: true, sort: (r) => (full(r) ? r[m.key] : null),
      cell: (r) => (full(r) ? `${r[m.key]}` : h("span", { class: "muted" }, "–")) })),
    { key: "units", label: "쓰인 니케", num: true, sort: (r) => (full(r) ? r.units : null), cell: (r) => (full(r) ? `${r.units}` : h("span", { class: "muted" }, "–")) },
    { key: "similarity", label: "교차 유사도", num: true, sort: (r) => r.similarity, cell: (r) => num(r.similarity) },
    { key: "own", label: "약점 속성 몫", num: true, sort: (r) => r.ownShare, cell: (r) => pct(r.ownShare) },
  ];
  return h("details", { class: "panel table-panel meta-table" },
    h("summary", null, h("h3", null, "숫자로 보기")),
    sortableTable(columns, rows, {
      sortKey: sort.key, sortDir: sort.dir, caption: "시즌별 메타 지표",
      onSort: (key, dir) => { state.sort.meta = { key, dir }; app.rerender(); },
    }));
}

