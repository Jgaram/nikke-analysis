// 티어 변화 · 니케 비교 and 약점별 시즌: units side by side over the seasons. The same
// frame as one unit's page - the chosen day, a chart, the table under it - and one list
// of units compared (state.compare, in colour slots), shared by the two views.

import { assignTier, ELEMENTS } from "../model.js";
import {
  h, num, int, face, elementIcon, ELEMENT_KO, tierBadge, sortableTable, segmented, unitName, todayKst, day,
} from "../ui.js";
import { trendTabs, unitSearch, unitInline } from "./common.js";
import { dateBar } from "./date.js";
import { seriesChart } from "../chart.js";

export const COMPARE_MAX = 5;

// The units compared, each with its colour slot.
function compared(app) {
  return app.state.compare.map((u, slot) => (u == null ? null : { u, slot })).filter(Boolean);
}

const swatch = (slot) => h("i", { class: `sw line ser s${slot + 1}`, "aria-hidden": "true" });

// The chosen day, marked on the charts (today marks nothing).
const dayOf = (app) => (app.state.date && app.state.date !== todayKst() ? app.moment() : null);

// ---------------------------------------------------------------------------
// 니케 비교: the overall tier of each unit compared, once each season was over

export function compareView(app) {
  const { model, state } = app;
  const pop = app.population();
  const history = app.history();
  const picked = compared(app);
  const root = h("div", { class: "view view-trend" }, trendTabs(app), dateBar(app), chooser(app, picked));
  if (!picked.length) return root;

  // the seasons from the first any of them played to the latest
  const summary = pop.summary;
  const first = summary.findIndex((s) => picked.some((p) => s.byUnit.has(p.u)));
  const seasons = first < 0 ? [] : summary.slice(first);
  if (!seasons.length) {
    root.append(h("div", { class: "panel empty" }, "고른 니케가 치른 시즌이 아직 없습니다."));
    return root;
  }
  const at = (s, u) => history.get(s.season)?.get(u) || null;
  const series = picked.map((p) => {
    const values = seasons.map((s) => {
      const x = at(s, p.u);
      return x && !Number.isNaN(x.overall) ? x.overall : null;
    });
    const breakAt = seasons.findIndex((s) => s.byUnit.get(p.u)?.treasure);
    return { ...p, values, breakAt };
  });
  const cuts = state.params.overallCuts;
  root.append(h("section", { class: "panel chart-panel" },
    h("div", { class: "panel-head" }, h("h3", null, "종합 티어 변화"),
      h("span", { class: "muted small" }, "선의 값 = 그 시즌이 끝났을 때의 종합 티어 · 배경 띠 = 종합 컷 · ♥ = 애장품부터 다시 매김")),
    seriesChart(app, {
      points: seasons.map((season) => ({ season })), series, cuts, at: dayOf(app),
      valueLabel: "그 시즌이 끝났을 때의 종합 티어",
      ariaLabel: `${picked.map((p) => unitName(model.units[p.u])).join(", ")}의 시즌별 종합 티어. 아래 표에 같은 값이 있습니다.`,
    })));

  // the table: a season a row, newest first, a unit a column
  const rows = [...seasons].reverse();
  const columns = [
    { key: "season", label: "시즌", num: true, head: true, sort: (s) => s.season,
      cell: (s) => h("a", { class: "link", href: app.seasonHref(s.season) }, `S${s.season}`) },
    { key: "boss", label: "보스 · 약점", sort: (s) => s.weak, cell: (s) => h("span", { class: "boss-cell" },
      h("span", { class: "boss-name" }, s.info.bossKo || s.info.bossEn || "?"), elementIcon(s.weak, 15),
      !s.final ? h("span", { class: "pill live" }, "진행 중") : null) },
    ...picked.map((p) => {
      const unit = model.units[p.u];
      return {
        key: `u${p.u}`, title: unitName(unit), sort: (s) => at(s, p.u)?.overall,
        label: h("span", { class: "ser-head" }, swatch(p.slot), face(unit, 22), h("span", null, unitName(unit))),
        cell: (s) => {
          const x = at(s, p.u);
          if (!x || Number.isNaN(x.overall)) return h("span", { class: "muted" }, s.byUnit.has(p.u) ? "–" : "");
          return h("span", null, tierBadge(x.overallTier, x.overall),
            x.provisional ? h("sup", { class: "muted" }, "*") : null,
            s.byUnit.get(p.u)?.elementMatch ? h("b", { class: "own-mark", title: "자기 속성 약점 시즌" }, "▶") : null);
        },
      };
    }),
  ];
  const sort = state.sort.compareUnits || { key: "season", dir: "desc" };
  root.append(h("section", { class: "panel table-panel" },
    h("div", { class: "panel-head" }, h("h3", null, "시즌별 종합 티어"), h("span", { class: "muted small" }, `${rows.length}시즌`)),
    sortableTable(columns, rows, {
      sortKey: sort.key, sortDir: sort.dir, caption: "고른 니케의 시즌별 종합 티어",
      onSort: (key, dir) => { state.sort.compareUnits = { key, dir }; app.rerender(); },
    }),
    h("p", { class: "note" }, "칸 = 그 시즌이 끝났을 때의 종합 티어 (진행 중 시즌은 지금까지) · * = 잠정 · ▶ = 그 니케의 자기 속성 약점 시즌 · "
      + "빈칸 = 그땐 없던 니케 · 애장품을 낀 뒤로는 애장품을 낀 시즌만으로 다시 매긴다.")));
  return root;
}

// The units compared as chips (each out with its ×), a search to add one, and - with none
// yet - a start from the top of the overall tier.
function chooser(app, picked) {
  const { model, state } = app;
  const full = state.compare.filter((u) => u != null).length >= COMPARE_MAX && !state.compare.includes(null);
  const chips = picked.map((p) => {
    const unit = model.units[p.u];
    return h("span", { class: "cmp-chip" }, swatch(p.slot),
      h("a", { href: app.unitHref(unit.id), class: "cmp-chip-name" }, face(unit, 24), unitName(unit)),
      h("button", {
        type: "button", class: "cmp-chip-x", "aria-label": `${unitName(unit)} 빼기`,
        onclick: () => app.go({ compare: app.withoutCompared(p.u) }, { replace: true }),
      }, "×"));
  });
  const skip = new Set(picked.map((p) => p.u));
  const view = app.viewAt(app.moment());
  const top = view.standing.overall.slice(0, COMPARE_MAX).map((o) => o.u);
  return h("section", { class: "panel cmp-chooser" },
    h("div", { class: "panel-head" }, h("h3", null, "비교할 니케"),
      h("span", { class: "muted small" }, `${COMPARE_MAX}명까지 · 색은 빼기 전까지 그 니케를 따라간다 · 약점별 시즌 보기와 같은 목록`)),
    h("div", { class: "cmp-row" }, chips,
      full ? h("span", { class: "muted small" }, "5명이 다 찼습니다 — 한 명을 빼면 더할 수 있습니다")
        : unitSearch(app, { placeholder: "니케 더하기 (한글·영문)", skip, choose: (u) => app.go({ compare: app.withCompared(u) }, { replace: true }) })),
    !picked.length ? h("p", { class: "note" }, "위에서 니케를 찾아 더하거나 ",
      h("button", { type: "button", class: "btn small", onclick: () => app.go({ compare: top }, { replace: true }) },
        `고른 날 종합 상위 ${top.length}명으로 시작`),
      ". 니케 화면의 “+ 비교에 추가” 로도 더할 수 있다.") : null);
}

// ---------------------------------------------------------------------------
// 약점별 시즌: every season whose boss was weak to one element, side by side

export function weakView(app) {
  const { model, state } = app;
  const pop = app.population();
  const latest = pop.summary.length ? pop.summary[pop.summary.length - 1].weak : ELEMENTS[0];
  const weak = state.weak ?? latest;
  const ko = ELEMENT_KO[weak];
  const cuts = state.params.cuts;
  const seasons = model.seasons.filter((s) => s.weak === weak && pop.tables.has(s.season)).map((s) => pop.tables.get(s.season));
  const bySeason = new Map(seasons.map((s) => [s.season, s.byUnit]));
  const used = new Set();
  for (const rows of bySeason.values()) for (const r of rows.values()) if (r.rankers > 0) used.add(r.u);
  const view = app.viewAt(app.moment());
  const e = ELEMENTS.indexOf(weak);
  const units = [...used].filter((u) => app.passes(model.units[u])).map((u) => {
    const slot = view.standing.slots.get(u)?.[e] || null;
    let fielded = 0;
    for (const rows of bySeason.values()) if (rows.get(u)?.rankers > 0) fielded++;
    return { u, slot, fielded };
  });

  // the units drawn: the ones compared, or - none compared - the five best in this weakness now
  const explicit = compared(app);
  const best = [...units].sort((a, b) => (b.slot?.lift ?? -1) - (a.slot?.lift ?? -1)).slice(0, COMPARE_MAX).map((r) => r.u);
  const drawn = explicit.length ? explicit : best.map((u, slot) => ({ u, slot }));
  const slotOf = new Map(drawn.map((d) => [d.u, d.slot]));
  // pressing a row: in or out of the list - starting from the five shown when none were compared
  const toggle = (u) => {
    const base = explicit.length ? state.compare : best;
    app.go({ compare: base.includes(u) ? app.withoutCompared(u, base) : app.withCompared(u, base) }, { replace: true });
  };

  const count = (el) => model.seasons.filter((s) => s.weak === el && pop.tables.has(s.season)).length;
  const root = h("div", { class: "view view-trend" }, trendTabs(app), dateBar(app),
    h("div", { class: "toolbar" }, segmented(ELEMENTS.map((el) => ({
      value: el, label: ELEMENT_KO[el], icon: elementIcon(el, 16, { title: "" }), title: `${ELEMENT_KO[el]} 약점 시즌 ${count(el)}개`,
    })), weak, (v) => app.go({ weak: v }, { replace: true }), { class: "viewtabs", label: "보스 약점" })));
  if (!seasons.length) {
    root.append(h("div", { class: "panel empty" }, `${ko} 약점 시즌이 아직 없습니다.`));
    return root;
  }

  root.append(h("section", { class: "panel chart-panel" },
    h("div", { class: "panel-head" }, h("h3", null, `${ko} 약점 시즌 기여도`),
      h("span", { class: "muted small" }, explicit.length ? "비교 목록의 니케 · 아래 표에서 행을 눌러 넣고 빼기"
        : `비교 목록이 비어 지금 ${ko} 약점 칸 상위 ${drawn.length}명 · 아래 표에서 행을 눌러 바꾸기`)),
    seriesChart(app, {
      points: seasons.map((season) => ({ season })),
      series: drawn.map((d) => ({ ...d, breakAt: -1, values: seasons.map((s) => bySeason.get(s.season).get(d.u)?.lift ?? null) })),
      cuts, at: dayOf(app), valueLabel: "그 시즌 기여도 (시즌 티어)",
      ariaLabel: `${ko} 약점 시즌들의 기여도: ${drawn.map((d) => unitName(model.units[d.u])).join(", ")}. 아래 표에 같은 값이 있습니다.`,
    })));

  const newest = [...seasons].reverse();
  const sort = state.sort.compare || { key: "slot", dir: "desc" };
  const columns = [
    { key: "pick", label: "비교", title: "그래프에 넣고 빼기", sort: (r) => (slotOf.has(r.u) ? 0 : 1), firstDir: "asc",
      cell: (r) => h("button", {
        type: "button", class: ["pick-btn", slotOf.has(r.u) && "on"], "aria-pressed": String(slotOf.has(r.u)),
        "aria-label": `${unitName(model.units[r.u])} ${slotOf.has(r.u) ? "그래프에서 빼기" : "그래프에 넣기"}`,
        onclick: () => toggle(r.u),
      }, slotOf.has(r.u) ? swatch(slotOf.get(r.u)) : "+") },
    { key: "unit", label: "니케", head: true, sort: (r) => model.units[r.u].ko || model.units[r.u].en, firstDir: "asc",
      cell: (r) => unitInline(app, r.u) },
    { key: "slot", label: `${ko} 약점 종합`,
      title: `고른 날 기준, ${ko} 약점 시즌들의 기여도를 최근일수록 크게 친 평균 — 종합 티어를 이루는 다섯 칸 중 하나. `
        + "니케의 속성이 아니라 보스 약점 기준이라 다른 속성 니케도 든다",
      sort: (r) => r.slot?.lift, cell: (r) => {
        if (!r.slot) return h("span", { class: "muted" }, "–");
        if (!r.slot.seasons) return h("span", { class: "muted", title: "애장품 뒤로는 이 약점 시즌을 아직 못 겪어 채운 값" }, `(${num(r.slot.lift)})`);
        return tierBadge(assignTier(r.slot.lift, cuts), r.slot.lift);
      } },
    { key: "fielded", label: "쓰인", num: true, title: `상위 랭커가 쓴 ${ko} 약점 시즌 수`, sort: (r) => r.fielded,
      cell: (r) => h("span", null, int(r.fielded), h("span", { class: "muted" }, `/${seasons.length}`)) },
    ...newest.map((s) => ({
      key: `s${s.season}`, class: "cmp-season",
      title: `시즌 ${s.season} · ${s.info.bossKo || s.info.bossEn || "?"} · ${day(s.start)}${s.final ? "" : " · 진행 중"}`,
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
  root.append(h("section", { class: "panel table-panel compare-panel" },
    h("div", { class: "panel-head" }, h("h3", null, `${ko} 약점 시즌 나란히`), h("span", { class: "muted small" }, `${seasons.length}시즌 · 니케 ${units.length}명`)),
    sortableTable(columns, units, {
      sortKey: sort.key, sortDir: sort.dir, caption: `${ko} 약점 시즌 나란히`,
      onSort: (key, dir) => { state.sort.compare = { key, dir }; app.rerender(); },
      rowAttrs: (r) => ({ class: slotOf.has(r.u) ? "picked-row" : null }),
    }),
    h("p", { class: "note" },
      `${ko} 약점 시즌 ${seasons.length}개를 최근 시즌부터 나란히. 칸 = 그 시즌 기여도와 시즌 티어 · · = 안 씀 · 빈칸 = 그땐 없던 니케 · `,
      h("span", { class: "heart-text" }, "♥"), " = 애장품을 끼고 치른 시즌. ",
      `${ko} 약점 종합 = 종합 티어를 이루는 칸 하나(고른 날 기준, 최근 시즌일수록 크게). 니케 속성이 아니라 보스 약점 기준이라 `
        + "다른 속성 니케도 든다. 괄호 = 애장품 뒤로는 아직 못 겪어 채운 값. 첫 열의 + 로 그래프에 넣고 뺀다 (니케 비교와 같은 목록).")));
  return root;
}
