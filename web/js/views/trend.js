// 티어 변화 · 니케 비교: units side by side over the seasons - their overall tier once
// each season was over, or, with a boss weakness chosen, their lift in each season of that
// weakness. The frame of one unit's page: the chosen day, a chart, the table under it.
// The units compared (state.compare, up to COMPARE_MAX) are picked from the same grid
// as one unit is (under the chips, folded once there are units to show), or from the
// table's first column.

import { assignTier, ELEMENTS } from "../model.js";
import {
  h, num, int, face, elementIcon, ELEMENT_KO, tierBadge, sortableTable, segmented, unitName, day, pendingLabel,
} from "../ui.js";
import { trendTabs, unitInline, lent } from "./common.js";
import { timeStrip } from "./when.js";
import { unitPicker } from "./pick.js";
import { seriesChart } from "../chart.js";

export const COMPARE_MAX = 20;
const PICKER = "cmp:picker"; // state.expanded: the picker open while units are compared
const START = 10; // "start with the best N"

// The chosen season's moment, marked on the chart (now marks nothing).
const dayOf = (app) => app.pinned();

export function compareView(app) {
  const { model, state } = app;
  const pop = app.population();
  const weak = state.weak;
  const picked = state.compare;
  const view = app.viewAt(app.moment());

  // the units that start a comparison: the best overall now, or the best in this weakness
  const e = weak ? ELEMENTS.indexOf(weak) : -1;
  const best = (weak
    ? view.standing.overall.map((o) => ({ u: o.u, v: view.standing.slots.get(o.u)?.[e] }))
      .filter((r) => r.v?.seasons).sort((a, b) => b.v.lift - a.v.lift).map((r) => r.u)
    : view.standing.overall.map((o) => o.u)).slice(0, START);

  const count = (el) => model.seasons.filter((s) => s.weak === el && pop.tables.has(s.season)).length;
  const root = h("div", { class: "view view-trend" }, trendTabs(app), timeStrip(app, { compact: true }),
    h("div", { class: "toolbar" }, segmented([
      { value: null, label: "전체", title: "모든 시즌 · 종합 티어" },
      ...ELEMENTS.map((el) => ({
        value: el, label: ELEMENT_KO[el], icon: elementIcon(el, 16, { title: "" }),
        title: `보스 약점이 ${ELEMENT_KO[el]}인 시즌 ${count(el)}개 · 그 시즌 기여도`,
      })),
    ], weak, (v) => app.go({ weak: v }, { replace: true }), { class: "viewtabs", label: "보스 약점" })));

  const chips = chosen(app, picked, best);
  root.append(chips.panel);

  const open = !picked.length || state.expanded.has(PICKER);
  const toggle = (u) => app.go({ compare: picked.includes(u) ? app.withoutCompared(u) : app.withCompared(u) }, { replace: true });
  const picker = h("section", { class: ["cmp-picker", !open && "closed"] },
    h("button", {
      type: "button", class: "cmp-picker-head", "aria-expanded": String(open),
      onclick: () => { if (open) state.expanded.delete(PICKER); else state.expanded.add(PICKER); app.rerender(); },
      disabled: !picked.length, // with none compared the grid stays open
    }, h("b", null, "니케 고르기"), picked.length ? h("span", { class: "muted small" }, open ? "접기 ▴" : "펼치기 ▾") : null),
    open ? unitPicker(app, {
      sub: `${picked.length}/${COMPARE_MAX}명 골랐음`, fold: "cmp:bottom",
      enter: (u) => { state.expanded.add(PICKER); toggle(u); }, note: `✓ = 비교 중. ${COMPARE_MAX}명까지.`,
      // picking from the grid keeps it open for the next one
      pick: (u) => ({
        on: picked.includes(u), onclick: () => { state.expanded.add(PICKER); toggle(u); },
        href: app.link({ compare: picked.includes(u) ? app.withoutCompared(u) : app.withCompared(u) }),
      }),
    }) : null);

  if (!picked.length) {
    root.append(picker);
    return root;
  }
  const body = weak ? weakBody(app, weak, picked, toggle) : overallBody(app, picked);
  root.append(picker, ...body.chart ? [body.chart] : [], ...body.rest);
  if (body.spot) chips.spot(body.spot);
  return root;
}

// The units compared: a chip each (hover lights its line; × takes it out), 비우기, and the
// way to start from the best ten.
function chosen(app, picked, best) {
  const { model } = app;
  let chart = null;
  const chips = picked.map((u) => {
    const unit = model.units[u];
    const chip = h("span", { class: "cmp-chip", dataset: { el: unit.element || "none" } },
      h("a", { href: app.unitHref(unit.id), class: "cmp-chip-name" }, face(unit, 24), unitName(unit)),
      h("button", {
        type: "button", class: "cmp-chip-x", "aria-label": `${unitName(unit)} 빼기`,
        onclick: () => app.go({ compare: app.withoutCompared(u) }, { replace: true }),
      }, "×"));
    chip.addEventListener("pointerenter", () => chart?.spotlight(u));
    chip.addEventListener("pointerleave", () => chart?.spotlight(null));
    return chip;
  });
  const panel = h("section", { class: "panel cmp-chooser" },
    h("div", { class: "panel-head" }, h("h3", null, "비교할 니케", h("span", { class: "muted" }, ` ${picked.length}/${COMPARE_MAX}`)),
      h("span", { class: "cmp-actions" },
        best.length ? h("button", {
          type: "button", class: "btn small", title: "지금 목록을 이 니케들로 바꾼다",
          onclick: () => app.go({ compare: best }, { replace: true }),
        }, `${app.state.weak ? `${ELEMENT_KO[app.state.weak]} 약점` : "종합"} 상위 ${best.length}명으로`) : null,
        picked.length ? h("button", {
          type: "button", class: "btn small ghost", onclick: () => app.go({ compare: [] }, { replace: true }),
        }, "모두 비우기") : null)),
    picked.length ? h("div", { class: "cmp-row" }, chips)
      : h("p", { class: "note cmp-empty" }, "아래 목록에서 얼굴을 눌러 넣거나, 위 버튼으로 상위 니케부터 시작하세요. 니케 화면의 “+ 비교에 추가” 로도 넣을 수 있습니다."));
  return { panel, spot: (c) => { chart = c; } };
}

const chartPanel = (title, sub, chart) => h("section", { class: "panel chart-panel" },
  h("div", { class: "panel-head" }, h("h3", null, title), h("span", { class: "muted small" }, sub)), chart);

const LEGEND = "선 색 = 니케 속성 · 끝의 얼굴에 마우스를 올리면 그 선만, 누르면 그 니케로";

// 전체: the overall tier of each, once each season was over.
function overallBody(app, picked) {
  const { model, state } = app;
  const pop = app.population();
  const history = app.history();
  const summary = pop.summary;
  const first = summary.findIndex((s) => picked.some((u) => s.byUnit.has(u)));
  const seasons = first < 0 ? [] : summary.slice(first);
  if (!seasons.length) return { rest: [h("div", { class: "panel empty" }, "고른 니케가 치른 시즌이 아직 없습니다.")] };
  const at = (s, u) => history.get(s.season)?.get(u) || null;
  const series = picked.map((u) => ({
    u,
    values: seasons.map((s) => { const x = at(s, u); return x && !Number.isNaN(x.overall) ? x.overall : null; }),
    faint: seasons.map((s) => Boolean(at(s, u)?.borrowed)),
    breakAt: seasons.findIndex((s) => s.byUnit.get(u)?.treasure),
  }));
  const chart = seriesChart(app, {
    points: seasons.map((season) => ({ season })), series, cuts: state.params.overallCuts, at: dayOf(app),
    valueLabel: "시즌 끝의 종합 티어",
    ariaLabel: `${picked.map((u) => unitName(model.units[u])).join(", ")}의 시즌별 종합 티어. 아래 표에 같은 값이 있습니다.`,
  });

  const rows = [...seasons].reverse();
  const columns = [
    { key: "season", label: "시즌", num: true, head: true, sort: (s) => s.season,
      cell: (s) => h("a", { class: "link", href: app.seasonHref(s.season) }, `S${s.season}`) },
    { key: "boss", label: "보스 · 약점", sort: (s) => s.weak, cell: (s) => h("span", { class: "boss-cell" },
      h("span", { class: "boss-name" }, s.info.bossKo || s.info.bossEn || "?"), elementIcon(s.weak, 15),
      !s.final ? h("span", { class: "pill live" }, pendingLabel(s.end)) : null) },
    ...picked.map((u) => {
      const unit = model.units[u];
      return {
        key: `u${u}`, title: unitName(unit), sort: (s) => at(s, u)?.overall,
        label: h("span", { class: "ser-head" }, face(unit, 22), h("span", null, unitName(unit))),
        cell: (s) => {
          const x = at(s, u);
          if (!x || Number.isNaN(x.overall)) return h("span", { class: "muted" }, s.byUnit.has(u) ? "–" : "");
          return h("span", lent(x), tierBadge(x.overallTier, x.overall),
            x.provisional ? h("sup", { class: "muted" }, "?") : null,
            s.byUnit.get(u)?.elementMatch ? h("b", { class: "own-mark", title: "자기 속성 약점 시즌" }, "▶") : null);
        },
      };
    }),
  ];
  const sort = state.sort.compareUnits || { key: "season", dir: "desc" };
  return {
    chart: chartPanel("종합 티어 변화", `선의 값 = 그 시즌이 끝났을 때의 종합 티어 · 배경 띠 = 종합 컷 · ♥ = 애장품부터 다시 매김${
      series.some((sr) => sr.faint.some(Boolean)) ? " · 흐린 선 = 그때 못 겪은 쪽을 나중 시즌 기록으로 채운 종합" : ""} · ${LEGEND}`, chart),
    spot: chart,
    rest: [h("section", { class: "panel table-panel compare-panel" },
      h("div", { class: "panel-head" }, h("h3", null, "시즌별 종합 티어"), h("span", { class: "muted small" }, `${rows.length}시즌`)),
      sortableTable(columns, rows, {
        sortKey: sort.key, sortDir: sort.dir, caption: "고른 니케의 시즌별 종합 티어",
        onSort: (key, dir) => { state.sort.compareUnits = { key, dir }; app.rerender(); },
      }),
      h("p", { class: "note" }, "칸 = 그 시즌이 끝났을 때의 종합 티어 (진행 중 시즌은 지금까지) · ? = 잠정 · ▶ = 그 니케의 자기 속성 약점 시즌 · "
        + "빈칸 = 그땐 없던 니케 · 애장품을 낀 뒤로는 애장품을 낀 시즌만으로 다시 매긴다."))],
  };
}

// One weakness: each unit's lift in every season of it, and the table of every unit.
function weakBody(app, weak, picked, toggle) {
  const { model, state } = app;
  const pop = app.population();
  const ko = ELEMENT_KO[weak];
  const cuts = state.params.cuts;
  const seasons = model.seasons.filter((s) => s.weak === weak && pop.tables.has(s.season)).map((s) => pop.tables.get(s.season));
  if (!seasons.length) return { rest: [h("div", { class: "panel empty" }, `${ko} 약점 시즌이 아직 없습니다.`)] };
  const bySeason = new Map(seasons.map((s) => [s.season, s.byUnit]));
  const used = new Set(picked);
  for (const rows of bySeason.values()) for (const r of rows.values()) if (r.rankers > 0) used.add(r.u);
  const view = app.viewAt(app.moment());
  const e = ELEMENTS.indexOf(weak);
  const units = [...used].filter((u) => picked.includes(u) || app.passes(model.units[u])).map((u) => {
    const slot = view.standing.slots.get(u)?.[e] || null;
    let fielded = 0;
    for (const rows of bySeason.values()) if (rows.get(u)?.rankers > 0) fielded++;
    return { u, slot, fielded };
  });
  const on = new Set(picked);
  const chart = seriesChart(app, {
    points: seasons.map((season) => ({ season })),
    series: picked.map((u) => ({ u, breakAt: -1, values: seasons.map((s) => bySeason.get(s.season).get(u)?.lift ?? null) })),
    cuts, at: dayOf(app), valueLabel: "그 시즌 기여도",
    ariaLabel: `${ko} 약점 시즌들의 기여도: ${picked.map((u) => unitName(model.units[u])).join(", ")}. 아래 표에 같은 값이 있습니다.`,
  });

  const newest = [...seasons].reverse();
  const sort = state.sort.compare || { key: "slot", dir: "desc" };
  const columns = [
    // the unit stays in view while the seasons scroll sideways (on a phone, its face only)
    { key: "unit", label: "니케", head: true, sort: (r) => model.units[r.u].ko || model.units[r.u].en, firstDir: "asc",
      cell: (r) => unitInline(app, r.u) },
    { key: "pick", label: "비교", title: "그래프에 넣고 빼기", sort: (r) => (on.has(r.u) ? 0 : 1), firstDir: "asc",
      cell: (r) => h("button", {
        type: "button", class: ["pick-btn", on.has(r.u) && "on"], "aria-pressed": String(on.has(r.u)),
        "aria-label": `${unitName(model.units[r.u])} ${on.has(r.u) ? "그래프에서 빼기" : "그래프에 넣기"}`,
        onclick: () => toggle(r.u),
      }, on.has(r.u) ? "✓" : "+") },
    { key: "slot", label: `${ko} 약점 종합`,
      title: `보정 기여도: 고른 시즌 기준, ${ko} 약점 시즌들의 기여도 추세선을 그 시점에서 읽은 값 — 종합 티어를 이루는 다섯 칸 중 하나`,
      sort: (r) => r.slot?.lift, cell: (r) => {
        if (!r.slot) return h("span", { class: "muted" }, "–");
        if (!r.slot.seasons) return h("span", { class: "muted", title: "애장품 뒤로는 이 약점 시즌을 아직 못 겪어 채운 값" }, `(${num(r.slot.lift)})`);
        return tierBadge(assignTier(r.slot.lift, cuts), r.slot.lift);
      } },
    { key: "fielded", label: "쓰인", num: true, title: `상위 랭커가 쓴 ${ko} 약점 시즌 수`, sort: (r) => r.fielded,
      cell: (r) => h("span", null, int(r.fielded), h("span", { class: "muted" }, `/${seasons.length}`)) },
    ...newest.map((s) => ({
      key: `s${s.season}`, class: "cmp-season",
      title: `시즌 ${s.season} · ${s.info.bossKo || s.info.bossEn || "?"} · ${day(s.start)}${s.final ? "" : ` · ${pendingLabel(s.end)}`}`,
      label: h("span", { class: "cmp-head" },
        s.info.bossImage ? h("img", { src: `icons/bosses/${s.info.bossImage}.webp`, alt: "", width: 28, height: 28, loading: "lazy" }) : null,
        h("span", null, `S${s.season}`)),
      sort: (r) => bySeason.get(s.season).get(r.u)?.lift,
      cell: (r) => {
        const row = bySeason.get(s.season).get(r.u);
        if (!row) return h("span", { class: "muted", title: "그 시즌엔 아직 없던 니케" }, "");
        if (!row.rankers) return h("span", { class: "muted", title: "안 씀" }, "·");
        return h("span", { class: "cmp-cell" }, tierBadge(assignTier(row.lift, cuts), row.lift),
          row.treasure ? h("span", { class: "heart-text", title: "애장품을 끼고 치른 시즌" }, "♥") : null);
      },
    })),
  ];
  return {
    chart: chartPanel(`${ko} 약점 시즌 기여도`, `선의 값 = 그 시즌 기여도 · 배경 띠 = 시즌 티어 컷 · ${LEGEND}`, chart),
    spot: chart,
    rest: [h("section", { class: "panel table-panel compare-panel" },
      h("div", { class: "panel-head" }, h("h3", null, `${ko} 약점 시즌 나란히`), h("span", { class: "muted small" }, `${seasons.length}시즌 · 니케 ${units.length}명`)),
      sortableTable(columns, units, {
        sortKey: sort.key, sortDir: sort.dir, caption: `${ko} 약점 시즌 나란히`,
        onSort: (key, dir) => { state.sort.compare = { key, dir }; app.rerender(); },
        rowAttrs: (r) => ({ class: on.has(r.u) ? "picked-row" : null }),
      }),
      h("p", { class: "note" },
        `${ko} 약점 시즌 ${seasons.length}개를 최근 시즌부터 나란히. 칸 = 그 시즌 기여도와 시즌 티어 · · = 안 씀 · 빈칸 = 그땐 없던 니케 · `,
        h("span", { class: "heart-text" }, "♥"), " = 애장품을 끼고 치른 시즌. ",
        `${ko} 약점 종합 = 종합 티어를 이루는 칸 하나(고른 시즌 기준, 시즌 기록의 추세를 그 시점에서 읽은 값). `
          + "괄호 = 애장품 뒤로는 아직 못 겪어 채운 값. 비교 열의 + 로 그래프에 넣고 뺀다."))],
  };
}
