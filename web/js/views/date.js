// 날짜별 티어: where every unit stood on a day - overall, or in one element - and
// how long each has been in use.

import { ELEMENTS } from "../model.js";
import {
  h, elementIcon, ELEMENT_KO, day, shortDay, todayKst, tierBadge, sortableTable, segmented, kst,
} from "../ui.js";
import {
  unitCard, tierBoard, filterRow, modeSwitch, standingTip, unitInline, provisionalReason, lifeColumns, duration,
} from "./common.js";

const OVERALL_KO = {
  mean: "보스 약점 다섯 가지 성적의 평균",
  frequency: "보스 약점 다섯 가지 성적을 최근 자주 나온 약점일수록 크게 친 평균",
  max: "보스 약점 다섯 가지 중 겪어 본 가장 잘한 성적",
};
const FIRST_DAY = "2023-05-18"; // the first season's end

export function dateView(app) {
  const { state } = app;
  const moment = app.moment();
  const view = app.viewAt(moment);
  const root = h("div", { class: "view view-date" });
  root.append(dateBar(app), context(app, view), viewTabs(app));
  if (!view.standing.overall.length) {
    root.append(h("div", { class: "panel empty" }, "이 날짜까지 끝난 시즌이 없습니다. 첫 시즌은 2023-05-18 에 끝났습니다."));
    return root;
  }
  root.append(h("div", { class: "toolbar" }, filterRow(app), h("div", { class: "toolbar-end" }, modeSwitch(app))));
  root.append(state.view === "overall" ? overallBody(app, view) : elementBody(app, view, state.view));
  return root;
}

function dateBar(app) {
  const today = todayKst();
  const value = app.state.date || today;
  const launch = new Date(app.model.launch);
  const presets = [];
  for (let n = 1; n < 10; n++) {
    const d = `${launch.getUTCFullYear() + n}-11-04`;
    if (d > today) break;
    presets.push({ label: `${n}주년`, date: d });
  }
  const set = (date) => app.go({ date: date === today ? null : date }, { replace: true });
  const finals = app.population().summary.filter((s) => s.final);
  return h("div", { class: "datebar" },
    h("label", { class: "date-field" },
      h("span", { class: "fact-k" }, "기준일"),
      h("input", {
        type: "date", value, min: FIRST_DAY, max: today, "aria-label": "기준일",
        onchange: (e) => { if (e.target.value) set(e.target.value); },
      })),
    h("div", { class: "presets" },
      h("button", { type: "button", class: ["preset", !app.state.date && "on"], onclick: () => set(today) }, "오늘"),
      presets.map((p) => h("button", { type: "button", class: ["preset", app.state.date === p.date && "on"], onclick: () => set(p.date) }, p.label)),
      h("select", {
        class: "preset-select", "aria-label": "시즌이 끝난 날로",
        onchange: (e) => { if (e.target.value) set(e.target.value); },
      },
      h("option", { value: "" }, "시즌 끝난 날로…"),
      [...finals].reverse().map((s) => {
        const d = day(s.end);
        return h("option", { value: d, selected: app.state.date === d }, `시즌 ${s.season} 끝 (${d})`);
      }))));
}

function seasonChip(app, label, s, extra) {
  if (!s) return null;
  return h("a", { class: "around", href: app.href("season", s.season) },
    h("span", { class: "fact-k" }, label), h("b", null, `S${s.season}`), s.bossKo || s.bossEn || "?",
    elementIcon(s.weak, 15), extra ? h("span", { class: "muted" }, extra) : null);
}

function span(view) {
  const parts = [];
  if (view.final.length) parts.push(view.final.length > 1 ? `끝난 시즌 ${view.final[0]}–${view.final[view.final.length - 1]}` : `끝난 시즌 ${view.final[0]}`);
  else parts.push("끝난 시즌 없음");
  if (view.live.length) parts.push(`진행 중 시즌 ${view.live.join("·")}(잠정)`);
  return parts.join(" + ");
}

function context(app, view) {
  const t = kst(view.moment);
  const now = !app.state.date || app.state.date === todayKst();
  const around = view.around;
  const pop = app.population();
  const live = around.current && pop.tables.get(around.current.season);
  const note = around.current
    ? (live && !live.final && view.live.includes(around.current.season) ? `${shortDay(live.collectedOn)} 수집분 반영` : "아직 반영 안 됨")
    : null;
  return h("section", { class: "context" },
    h("div", { class: "context-when" },
      h("b", null, `${t.y}-${t.m}-${t.d}`), h("span", { class: "muted" }, now ? " 지금" : " 정오(KST)"), " 기준",
      h("span", { class: "sep" }), h("span", null, span(view))),
    h("div", { class: "context-around" },
      seasonChip(app, "진행 중", around.current, note),
      seasonChip(app, "직전", around.previous),
      seasonChip(app, "다음", around.next)));
}

function viewTabs(app) {
  return segmented([
    { value: "overall", label: "종합 티어" },
    ...ELEMENTS.map((e) => ({ value: e, label: ELEMENT_KO[e], icon: elementIcon(e, 16, { title: "" }) })),
  ], app.state.view, (v) => app.go({ view: v }, { replace: true }), { class: "viewtabs", label: "티어 종류" });
}

// ---------------------------------------------------------------------------

// How the lifespan columns and the grey faces read, with the parameters in force.
function lifeNote(app, table) {
  const { minUsage, retireAfterDays } = app.state.params;
  const min = Math.round(minUsage * 100);
  const retired = `마지막으로 쓰인 시즌이 끝나고 ${duration(retireAfterDays)} 동안 상위 랭커 ${min}% 넘게 쓴 시즌이 없음`;
  return table
    ? `시즌별 사용 = 시즌 하나가 칸 하나, 칠한 칸은 상위 랭커 ${min}% 이상이 쓴 시즌(진할수록 많이) · 수명 = 지금 쓰이는 흐름이 `
      + `언제부터 얼마나 이어졌나 · 은퇴 = ${retired}, 그 뒤 다시 쓰이면 복귀. `
    : `흑백 얼굴 = 은퇴(${retired}). `;
}

function overallBody(app, view) {
  const { state, model } = app;
  const rows = view.standing.overall.filter((o) => app.passes(model.units[o.u]));
  const table = state.mode === "table";
  const explain = h("p", { class: "note" },
    `종합 티어 = ${OVERALL_KO[state.params.overall]}. 약점은 니케의 속성이 아니라 보스 기준이다 — 서포터는 받쳐 주는 덱의 속성을 따라가므로. `,
    "* = 잠정 (겪은 보스 약점이 적거나 자기 속성 시즌을 아직 못 겪음) · ",
    h("span", { class: "heart-text" }, "♥"), " = 애장품을 낀 시즌만으로 매김. ", lifeNote(app, table));
  if (table) return h("div", { class: "panel table-panel" }, overallTable(app, view, rows), explain);
  const items = rows.map((o) => ({ u: o.u, tier: o.tier, value: o.overall, o }));
  return tierBoard(app, items, {
    key: `overall-${state.date || "now"}`,
    card: (it) => unitCard(app, it.u, {
      value: it.value, tier: it.tier, provisional: it.o.provisional, heart: it.o.treasure,
      retired: view.life.get(it.u)?.retired, tip: () => standingTip(app, it.u, view),
    }),
    note: explain,
  });
}

function overallTable(app, view, rows) {
  const { state } = app;
  const sort = state.sort.overall || { key: "overall", dir: "desc" };
  const mine = new Map();
  for (const r of view.standing.elements) {
    if (!mine.has(r.u)) mine.set(r.u, []);
    mine.get(r.u).push(r);
  }
  const columns = [
    { key: "rank", label: "#", num: true, sort: (o) => o.rank, firstDir: "asc", cell: (o) => o.rank },
    { key: "unit", label: "니케", head: true, sort: (o) => app.model.units[o.u].ko, firstDir: "asc", cell: (o) => unitInline(app, o.u) },
    { key: "overall", label: "종합", sort: (o) => o.overall,
      cell: (o) => h("span", null, tierBadge(o.tier, o.overall), o.provisional ? h("sup", { class: "muted", title: provisionalReason(o, view.standing.slots.get(o.u), state.params) }, "*") : null) },
    { key: "element", label: "속성 티어", title: "그 니케가 속한 속성에서의 티어", sort: (o) => Math.max(...(mine.get(o.u) || []).map((r) => (r.seasons ? r.lift : -1))),
      cell: (o) => h("span", { class: "el-tiers" }, (mine.get(o.u) || []).map((r) => h("span", { class: "el-tier" },
        elementIcon(r.element, 14), r.seasons ? tierBadge(r.tier, r.lift) : h("span", { class: "muted" }, "미관측")))) },
    ...lifeColumns(app, view),
  ];
  return sortableTable(columns, rows, {
    sortKey: sort.key, sortDir: sort.dir, caption: "종합 티어 비교표",
    onSort: (key, dir) => { state.sort.overall = { key, dir }; app.rerender(); },
  });
}

// ---------------------------------------------------------------------------

function elementBody(app, view, element) {
  const { state, model } = app;
  const rows = view.standing.elements.filter((r) => r.element === element && app.passes(model.units[r.u]));
  const seasons = view.standing.counted.filter((c) => c.weak === element)
    .map((c) => (c.live ? `${c.season}(진행 중)` : String(c.season)));
  const unseen = rows.filter((r) => !r.seasons);
  const table = state.mode === "table";
  const explain = h("p", { class: "note" },
    `${ELEMENT_KO[element]} 속성 티어 = 보스 약점이 ${ELEMENT_KO[element]}이던 시즌${seasons.length ? `(${seasons.join(" · ")})` : ""}의 기여도를 최근일수록 크게 친 평균. `,
    "얼굴 옆 속성 아이콘이 다르면 스킬로 이 속성 우월 코드를 가진 니케. ",
    h("span", { class: "heart-text" }, "♥"), " = 애장품을 낀 시즌만으로 매김. ", lifeNote(app, table));
  if (table) return h("div", { class: "panel table-panel" }, elementTable(app, view, rows, element), explain);
  const observed = rows.filter((r) => r.seasons);
  const board = tierBoard(app, observed.map((r) => ({ u: r.u, tier: r.tier, value: r.lift, r })), {
    key: `element-${element}-${state.date || "now"}`,
    card: (it) => unitCard(app, it.u, {
      value: it.value, tier: it.tier, heart: it.r.treasure, retired: view.life.get(it.u)?.retired,
      extra: it.r.source === "skill" ? h("span", { class: "tag", title: `스킬로 ${ELEMENT_KO[element]} 우월 코드도 가진 니케` }, `스킬 · 본래 ${ELEMENT_KO[model.units[it.u].element]}`) : null,
      tip: () => standingTip(app, it.u, view, { element }),
    }),
    note: explain,
  });
  if (unseen.length) {
    board.insertBefore(h("section", { class: "tier-row unseen", "aria-label": `미관측 ${unseen.length}명` },
      h("div", { class: "tier-label" }, h("span", { class: "tier-letter small" }, "미관측"), h("span", { class: "tier-count" }, `${unseen.length}명`)),
      h("div", { class: "cards" }, unseen.map((r) => unitCard(app, r.u, {
        tier: "D", dim: true, heart: r.treasure,
        tip: () => standingTip(app, r.u, view, { element }),
      })), h("span", { class: "row-note muted" }, `출시${unseen.some((r) => r.treasure) ? "·애장품" : ""} 뒤 ${ELEMENT_KO[element]} 약점 시즌을 아직 못 겪음`))),
    board.lastChild);
  }
  return board;
}

function elementTable(app, view, rows, element) {
  const { state, model } = app;
  const sort = state.sort.element || { key: "lift", dir: "desc" };
  const columns = [
    { key: "rank", label: "#", num: true, sort: (r) => r.rank, firstDir: "asc", cell: (r) => r.rank ?? "–" },
    { key: "unit", label: "니케", head: true, sort: (r) => model.units[r.u].ko, firstDir: "asc",
      cell: (r) => unitInline(app, r.u, { sub: r.source === "skill" ? `스킬 · 본래 ${ELEMENT_KO[model.units[r.u].element]}` : null }) },
    { key: "lift", label: `${ELEMENT_KO[element]} 티어`, sort: (r) => (r.seasons ? r.lift : null),
      cell: (r) => (r.seasons ? tierBadge(r.tier, r.lift) : h("span", { class: "muted" }, "미관측")) },
    { key: "seasons", label: "약점 시즌", title: `겪은 ${ELEMENT_KO[element]} 약점 시즌 수`, num: true, sort: (r) => r.seasons, cell: (r) => `${r.seasons}번` },
    { key: "overall", label: "종합", sort: (r) => view.standing.overallByUnit.get(r.u)?.overall, cell: (r) => {
      const o = view.standing.overallByUnit.get(r.u);
      return o ? h("span", null, tierBadge(o.tier, o.overall), o.provisional ? h("sup", { class: "muted" }, "*") : null,
        h("span", { class: "muted" }, ` ${o.rank}위`)) : "–";
    } },
    ...lifeColumns(app, view),
  ];
  return sortableTable(columns, rows, {
    sortKey: sort.key, sortDir: sort.dir, caption: `${ELEMENT_KO[element]} 속성 티어 비교표`,
    onSort: (key, dir) => { state.sort.element = { key, dir }; app.rerender(); },
  });
}

