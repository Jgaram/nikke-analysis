// 메타 변화 · 티어 분포: season by season, how many units each tier holds - their overall tier
// once the season was over (model.js tierHistory), their element tier then (in every element, or
// one), or their season tier (the season's own lift against the fixed cuts). The cuts are fixed, so the count itself is the news: a season one deck
// ran has many at the top, a season without one has none there and more in the middle.

import { assignTier, ELEMENTS } from "../model.js";
import { h, pct, elementIcon, sortableTable, segmented, infoButton, ELEMENT_KO } from "../ui.js";
import { lineChart, lineLegend } from "../linechart.js";
import { metaTabs, paramsNote, PARAM } from "./common.js";
import { seasonTip, seasonName } from "./meta.js";

const KINDS = {
  overall: { name: "종합 티어", hint: "그 시즌이 끝났을 때의 종합 티어", units: "출시된 니케" },
  element: { name: "속성 티어", hint: "그 시즌이 끝났을 때의 속성 티어", units: "속성 티어가 있는 니케" },
  season: { name: "시즌 티어", hint: "그 시즌 기여도에 댄 고정 컷", units: "출시된 니케" },
};

const help = (name, ...body) => h("div", { class: "tip tip-help" }, h("div", { class: "tip-name" }, name), ...body);

function mixHelp(app) {
  const p = app.state.params;
  const floor = p.cuts[p.cuts.length - 1][0];
  return help("티어별 니케 수",
    h("p", null, "시즌마다 그 시즌까지 출시된 니케를 티어로 나눠 셉니다. ", h("b", null, "종합 티어"),
      "는 그 시즌이 끝났을 때의 종합 티어(니케 탭 그래프의 값), ", h("b", null, "속성 티어"),
      "는 그때의 속성 티어 — 전체면 다섯 속성 표를 합친 것(두 속성으로 치는 니케는 두 번), 속성 하나면 그 속성 표만. 그 속성 약점 시즌을 아직 못 겪은 니케는 속성 티어가 없어 빠집니다. ",
      h("b", null, "시즌 티어"), "는 그 시즌 기여도에 댄 고정 컷입니다."),
    h("p", null, `${floor}(사실상 안 씀)는 그래프에서 빼고, 나머지를 "쓰인 니케"로 셉니다. 비율은 쓰인 니케 중 비율입니다. `
      + "컷이 고정이라 인원 자체가 정보입니다 — 한 덱이 압도한 시즌은 맨 위가 두껍고, 뚜렷한 메인 덱이 없던 시즌은 맨 위가 비고 가운데가 두껍습니다."),
    h("p", { class: "muted" }, "시즌 티어는 보스 약점마다 크게 흔들리니 한 시즌보다 10시즌 평균을 보세요. 종합 티어의 초기 시즌은 겪은 보스 약점이 적어 "
      + "잠정 값이 많고(툴팁의 \"잠정\"), 못 겪은 칸을 채운 값이라 위쪽이 부풀어 있습니다."),
    paramsNote([
      [PARAM.cuts, "속성·시즌 티어의 컷"],
      [PARAM.overallCuts, "종합 티어의 컷"],
      [PARAM.combine, "속성·종합 값 자체"],
      [PARAM.sample, "기여도 자체"],
    ]));
}

// One row a season: {season, counts: {label: n}, units (the ones with a tier), used (above the
// floor), provisional}. ``element`` narrows the element tiers to one element's table.
function tierRows(app, kind, element) {
  const params = app.state.params;
  const cuts = kind === "overall" ? params.overallCuts : params.cuts;
  const labels = cuts.map(([l]) => l);
  const shown = labels.slice(0, -1);
  const history = kind === "overall" ? app.history() : kind === "element" ? app.elementHistory() : null;
  const rows = [];
  for (const s of app.population().summary) {
    const here = history?.get(s.season);
    if (history && !here) continue;
    const counts = Object.fromEntries(labels.map((l) => [l, 0]));
    let provisional = 0;
    if (kind === "element") {
      let units = 0;
      for (const r of here) {
        if (!r.seasons || (element && r.element !== element)) continue;
        units++;
        if (r.tier in counts) counts[r.tier]++;
      }
      if (!units) continue; // before the first season of that weakness: no element tier yet
      rows.push({ season: s, counts, units, used: shown.reduce((a, l) => a + counts[l], 0), provisional });
      continue;
    }
    for (const r of s.rows) {
      let tier;
      if (kind === "season") tier = assignTier(r.lift, cuts);
      else {
        const e = here.get(r.u);
        tier = e?.overallTier;
        if (e?.provisional && tier && tier !== labels[labels.length - 1]) provisional++;
      }
      if (tier in counts) counts[tier]++;
    }
    const used = shown.reduce((a, l) => a + counts[l], 0);
    rows.push({ season: s, counts, units: s.rows.length, used, provisional });
  }
  return { rows, labels, shown };
}

export function tierMixView(app) {
  const { state } = app;
  const kind = state.tierKind || "overall";
  const element = kind === "element" ? state.tierElement || null : null;
  const { rows, shown } = tierRows(app, kind, element);
  const root = h("div", { class: "view view-meta" }, metaTabs(app));
  if (!rows.length) {
    root.append(h("div", { class: "panel empty" }, "시즌이 아직 없습니다."));
    return root;
  }
  const chosen = state.season != null ? rows.findIndex((r) => r.season.season === state.season) : -1;
  const markAt = chosen >= 0 ? chosen : null;
  const name = element ? `${ELEMENT_KO[element]} 속성 티어` : KINDS[kind].name;
  root.append(...intro(app, kind, element), chartPanel(app, kind, name, rows, shown, markAt), tablePanel(app, kind, name, rows, shown));
  return root;
}

const kindToggle = (app, kind) => segmented(Object.entries(KINDS).map(([value, k]) => ({ value, label: k.name, title: k.hint })), kind,
  (v) => { app.state.tierKind = v; app.rerender(); }, { label: "어느 티어" });

// the element tiers: every element's table together, or one element's
const elementToggle = (app, element) => segmented([
  { value: null, label: "전체", title: "다섯 속성 표를 합쳐서 — 두 속성으로 치는 니케는 두 번" },
  ...ELEMENTS.map((el) => ({ value: el, label: ELEMENT_KO[el], icon: elementIcon(el, 16, { title: "" }), title: `${ELEMENT_KO[el]} 속성 티어 표만` })),
], element, (v) => { app.state.tierElement = v; app.rerender(); }, { class: "viewtabs", label: "속성" });

// which tier (and, for the element tiers, which element), and a line on what is counted
function intro(app, kind, element) {
  return [
    h("div", { class: "toolbar" }, kindToggle(app, kind), kind === "element" ? elementToggle(app, element) : null),
    h("p", { class: "meta-lede" }, `시즌마다 그때까지 출시된 니케를 ${KINDS[kind].name}(${KINDS[kind].hint})로 나눠 셉니다. 컷이 고정이라 인원 자체가 정보입니다. `,
      { season: "보스 약점마다 크게 흔들립니다.",
        overall: "초기 시즌은 겪은 보스 약점이 적어 잠정 값이 많습니다.",
        element: `${element ? `${ELEMENT_KO[element]} 속성 표만 봅니다.` : "전체는 다섯 속성 표를 합친 것으로, 두 속성으로 치는 니케는 두 번 셉니다."} `
          + "그 속성 약점 시즌을 아직 못 겪은 니케는 빠집니다." }[kind]),
  ];
}

function chartPanel(app, kind, name, rows, shown, markAt) {
  const mode = app.state.tierMix || "count";
  const value = (r, l) => (mode === "count" ? r.counts[l] : r.used ? r.counts[l] / r.used : null);
  // the top tier at the bottom, on the axis
  const series = shown.map((l, k) => ({ name: l, cls: `tk${Math.min(k, 5)}`, values: rows.map((r) => value(r, l)) }));
  const top = Math.max(10, ...rows.map((r) => r.used));
  const max = mode === "count" ? Math.ceil(top / 10) * 10 : 1;
  const ticks = mode === "count" ? Array.from({ length: max / 10 + 1 }, (_, i) => i * 10).filter((v, i, a) => a.length <= 9 || i % 2 === 0)
    : [0, 0.25, 0.5, 0.75, 1];
  const toggle = segmented([{ value: "count", label: "명" }, { value: "share", label: "비율" }], mode,
    (v) => { app.state.tierMix = v; app.rerender(); }, { label: "명 또는 비율" });
  return h("section", { class: "panel chart-panel" },
    h("div", { class: "panel-head" }, h("span", { class: "head-title" }, h("h3", null, "티어별 니케 수"), infoButton("티어별 니케 수", () => mixHelp(app))),
      toggle,
      h("span", { class: "muted small" }, `${name} · 아래부터 ${shown[0]} → ${shown[shown.length - 1]} · 비율 = 쓰인 니케 중`)),
    lineLegend(series, { stacked: true }),
    lineChart({
      points: rows.map((r) => ({ label: r.season.season })), series, stacked: true, max, ticks, mark: markAt, height: 260,
      format: mode === "count" ? (v) => String(v) : (v) => `${Math.round(v * 100)}%`,
      label: `시즌별 ${name}마다 니케 수를 쌓은 그래프`,
      tip: (i) => {
        const r = rows[i];
        return seasonTip(r, [...shown.map((l) => [l, `${r.counts[l]}명 (${pct(r.used ? r.counts[l] / r.used : NaN)})`]),
          ["쓰인 니케", `${r.used}명`], [KINDS[kind].units, `${r.units}명`],
          ...(kind === "overall" && r.provisional ? [["잠정", `${r.provisional}명`]] : [])]);
      },
    }));
}

function tablePanel(app, kind, name, rows, shown) {
  const state = app.state;
  const sort = state.sort.tierMix || { key: "season", dir: "desc" };
  const columns = [
    { key: "season", label: "시즌", num: true, head: true, sort: (r) => r.season.season, cell: (r) => seasonName(r) },
    { key: "weak", label: "약점", sort: (r) => r.season.weak, cell: (r) => elementIcon(r.season.weak, 15) },
    ...shown.map((l) => ({ key: l, label: l, num: true, sort: (r) => r.counts[l], cell: (r) => `${r.counts[l]}` })),
    { key: "used", label: "쓰인 니케", num: true, sort: (r) => r.used, cell: (r) => `${r.used}` },
    { key: "units", label: KINDS[kind].units, num: true, sort: (r) => r.units, cell: (r) => `${r.units}` },
    { key: "top", label: `${shown[0]} 비율`, num: true, sort: (r) => (r.used ? r.counts[shown[0]] / r.used : null),
      cell: (r) => pct(r.used ? r.counts[shown[0]] / r.used : NaN) },
    ...(kind === "overall" ? [{ key: "prov", label: "잠정", num: true, sort: (r) => r.provisional, cell: (r) => `${r.provisional}` }] : []),
  ];
  return h("details", { class: "panel table-panel meta-table" },
    h("summary", null, h("h3", null, "숫자로 보기")),
    sortableTable(columns, rows, {
      sortKey: sort.key, sortDir: sort.dir, caption: `시즌별 ${name} 인원`,
      onSort: (key, dir) => { state.sort.tierMix = { key, dir }; app.rerender(); },
    }));
}
