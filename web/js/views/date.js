// 티어표 · 종합 / 약점: where every unit stood at the chosen season - overall, or over the
// seasons whose boss was weak to one element - and how long each has been in use.

import { ELEMENTS, assignTier, seasonWeight } from "../model.js";
import { h, elementIcon, ELEMENT_KO, shortDay, tierBadge, sortableTable, int, kst } from "../ui.js";
import {
  unitCard, tierBoard, filterRow, modeSwitch, standingTip, unitInline, provisionalReason, lifeColumns, retiredText, kindTabs,
} from "./common.js";
import { timeStrip } from "./when.js";

const ELEMENT_EN = { Fire: "FIRE", Water: "WATER", Wind: "WIND", Iron: "IRON", Electric: "ELECTRIC" };
const OVERALL_KO = {
  mean: "보스 약점 다섯 가지 성적의 평균",
  frequency: "보스 약점 다섯 가지 성적을 최근 자주 나온 약점일수록 크게 친 평균",
  max: "보스 약점 다섯 가지 중 겪어 본 가장 잘한 성적",
};

export function dateView(app) {
  const { state } = app;
  const view = app.viewAt(app.moment());
  const element = state.view !== "overall" ? state.view : null;
  const root = h("div", { class: "view view-date" });
  root.append(kindTabs(app), timeStrip(app, { weak: element }), hero(app, view, element));
  if (!view.standing.overall.length) {
    root.append(h("div", { class: "panel empty" }, "이때까지 끝난 시즌이 없습니다."));
    return root;
  }
  root.append(h("div", { class: "toolbar" }, filterRow(app), h("div", { class: "toolbar-end" }, modeSwitch(app))));
  root.append(element ? elementBody(app, view, element) : overallBody(app, view));
  return root;
}

// ---------------------------------------------------------------------------

// How the lifespan columns and the grey faces read, with the parameters in force.
function lifeNote(app, table) {
  const { minTier } = app.state.params;
  const retired = retiredText(app.state.params);
  return table
    ? `시즌별 사용 = 시즌 하나가 칸 하나, 칠한 칸은 시즌 티어 ${minTier} 이상인 시즌(색 = 그 시즌 티어) · 수명 = 지금 쓰이는 흐름이 `
      + `언제부터 얼마나 이어졌나 · 은퇴 = ${retired} · 복귀 = 은퇴한 뒤 다시 쓰임. `
    : `흑백 얼굴 = 은퇴(${retired}). `;
}

function overallBody(app, view) {
  const { state, model } = app;
  const rows = view.standing.overall.filter((o) => app.passes(model.units[o.u]));
  const table = state.mode === "table";
  const explain = h("p", { class: "note" },
    "* = 잠정 (겪은 보스 약점이 적거나 자기 속성 시즌을 아직 못 겪음) · ",
    h("span", { class: "heart-text" }, "♥"), " = 애장품을 낀 시즌만으로 매김. ", lifeNote(app, table));
  if (table) return h("div", { class: "panel table-panel" }, overallTable(app, view, rows), explain);
  const items = rows.map((o) => ({ u: o.u, tier: o.tier, value: o.overall, o }));
  return tierBoard(app, items, {
    key: `overall-${state.season ?? "now"}`, cuts: state.params.overallCuts,
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

// One boss weakness: every unit - whatever its element - by its slot for that weakness, the
// part of its overall tier that stands on the seasons whose boss was weak to it.
function weakRows(app, view, element) {
  const e = ELEMENTS.indexOf(element);
  const rows = view.standing.overall.map((o) => ({ u: o.u, o, slot: view.standing.slots.get(o.u)?.[e] || null }))
    .filter((r) => r.slot && app.passes(app.model.units[r.u]));
  const cuts = app.state.params.cuts;
  const seen = rows.filter((r) => r.slot.seasons).sort((a, b) => b.slot.lift - a.slot.lift);
  seen.forEach((r, i) => {
    r.rank = i > 0 && seen[i - 1].slot.lift === r.slot.lift ? seen[i - 1].rank : i + 1;
    r.tier = assignTier(r.slot.lift, cuts);
  });
  return { rows, seen, unseen: rows.filter((r) => !r.slot.seasons) };
}

// The head of the view, as 레이드별 has one: where it stands in time, what it is, how it is
// worked out, how many units each tier holds - and for a weakness, its seasons with their share.
function hero(app, view, element) {
  const { model, state } = app;
  const { params } = state;
  const chosen = state.season != null ? model.bySeason.get(state.season) : null;
  const entry = chosen && app.population().tables.get(chosen.season);
  const t = kst(view.moment);
  const liveNote = view.live.length ? `진행 중 S${view.live.join("·S")} ${shortDay(app.population().tables.get(view.live[0])?.collectedOn)} 수집분까지 (잠정)` : null;
  const status = chosen && entry?.final ? h("span", { class: "status done" }, `S${chosen.season} 종료 · ${t.y}-${t.m}-${t.d}`)
    : liveNote ? h("span", { class: "status live" }, h("i", { class: "pulse", "aria-hidden": "true" }), chosen ? liveNote : `지금 · ${liveNote}`)
      : h("span", { class: "status done" }, "지금");
  const counted = view.standing.counted;
  const mine = element ? counted.filter((c) => c.weak === element) : counted;

  // the tiers, over every unit (the filters below narrow the board only)
  const counts = {};
  let cuts;
  if (element) {
    cuts = params.cuts;
    const e = ELEMENTS.indexOf(element);
    for (const o of view.standing.overall) {
      const slot = view.standing.slots.get(o.u)?.[e];
      if (slot?.seasons) { const k = assignTier(slot.lift, cuts); counts[k] = (counts[k] || 0) + 1; }
    }
  } else {
    cuts = params.overallCuts;
    for (const o of view.standing.overall) counts[o.tier] = (counts[o.tier] || 0) + 1;
  }
  const tiered = Object.values(counts).reduce((a, b) => a + b, 0);

  const first = counted.length ? counted[0].season : null, last = counted.length ? counted[counted.length - 1].season : null;
  const servers = params.servers.length === model.servers.length ? `${model.servers.length}개 서버` : params.servers.join("·");
  return h("section", { class: ["hero", "hero-stand"] },
    element ? h("div", { class: "hero-num hero-el" }, h("small", null, "WEAK"), elementIcon(element, 60, { title: "" }))
      : h("div", { class: "hero-num" }, h("small", null, "SEASON"), h("b", { class: first !== last ? "range" : null }, first === last ? first ?? "–" : `${first}–${last}`)),
    h("div", { class: "hero-main" },
      h("div", { class: "hero-top" }, status),
      h("h2", { class: "hero-title" }, element ? `${ELEMENT_KO[element]} 약점 티어` : "종합 티어",
        h("span", { class: "hero-sub" }, element ? ELEMENT_EN[element] : "OVERALL")),
      h("div", { class: "hero-facts" },
        h("span", { class: "fact" }, h("span", { class: "fact-k" }, "반영"),
          element ? `보스 약점이 ${ELEMENT_KO[element]}인 시즌 ${mine.length}개` : `시즌 ${counted.length}개 (S${first ?? "–"}–S${last ?? "–"})`),
        h("span", { class: "fact" }, h("span", { class: "fact-k" }, "계산"),
          element ? `그 시즌들의 기여도 평균, 최근일수록 크게 (반감기 ${params.halfLifeDays}일)` : OVERALL_KO[params.overall])),
      h("div", { class: "hero-sample muted" }, `표본 ${servers} × 상위 ${params.topN}위 · 니케 ${int(tiered)}명`)),
    h("div", { class: "hero-counts", "aria-label": "티어별 인원" }, cuts.map(([k]) => h("span", { class: "count", dataset: { tier: k } },
      h("b", null, k), h("span", null, counts[k] || 0)))),
    seasonCards(app, view, element));
}

// What each counted season weighs in the tier, for a unit that has met every weakness. Within a
// weakness: its recency weight over the weakness's own. Overall, times the weakness's part: an
// equal part each (mean), or the weakness's recent frequency (frequency: that comes to the
// season's recency weight over every season's). ``max`` counts one weakness a unit, its best:
// the shares within each weakness then.
function seasonShares(view, params, element) {
  const counted = element ? view.standing.counted.filter((c) => c.weak === element) : view.standing.counted;
  const weights = counted.map((c) => seasonWeight(c, view.moment, params));
  const byWeak = new Map();
  counted.forEach((c, i) => byWeak.set(c.weak, (byWeak.get(c.weak) || 0) + weights[i]));
  const all = weights.reduce((a, b) => a + b, 0) || 1;
  return counted.map((c, i) => {
    const within = weights[i] / (byWeak.get(c.weak) || 1);
    const share = element || params.overall === "max" ? within : params.overall === "frequency" ? weights[i] / all : within / byWeak.size;
    return { c, share };
  });
}

// The seasons behind the tier, newest first, each with its share.
function seasonCards(app, view, element) {
  const { params } = app.state;
  const shares = seasonShares(view, params, element);
  if (!shares.length) return h("p", { class: "hero-foot note wi-empty" }, "이때까지 반영된 시즌이 없습니다.");
  const note = element ? `최근일수록 크게 (반감기 ${params.halfLifeDays}일)`
    : params.overall === "max" ? "약점마다 따로, 최근일수록 크게"
      : params.overall === "frequency" ? "최근일수록 크게 (반감기 " + params.halfLifeDays + "일)"
        : "약점 다섯 가지가 같은 몫, 그 안에서 최근일수록 크게";
  const top = Math.max(...shares.map((x) => x.share)) || 1;
  const card = (s, share, live) => {
    const boss = s.bossKo || s.bossEn || "?";
    const pct = share < 0.1 ? (share * 100).toFixed(1) : String(Math.round(share * 100));
    return h("a", { class: ["wb", live && "live"], href: app.link({ view: "raid", season: s.season }), title: `시즌 ${s.season} · ${boss} · 비중 ${pct}%` },
      s.bossImage ? h("img", { class: "wb-img", src: `icons/bosses/${s.bossImage}.webp`, alt: "", width: 44, height: 44, loading: "lazy", decoding: "async" })
        : h("span", { class: "wb-img none", "aria-hidden": "true" }),
      h("span", { class: "wb-text" },
        h("span", { class: "wb-top" }, h("b", null, `S${s.season}`), element ? null : elementIcon(s.weak, 13, { title: `약점 ${ELEMENT_KO[s.weak] || "?"}` }),
          live ? h("span", { class: "pill live" }, "진행 중") : null, h("span", { class: "wb-when muted" }, shortDay(s.start))),
        h("span", { class: "wb-name" }, boss),
        h("span", { class: "wb-share", "aria-label": `비중 ${pct}%` },
          h("i", { style: { width: `${Math.max(3, (share / top) * 70)}%` } }), h("small", null, `${pct}%`))));
  };
  return h("div", { class: "hero-foot" },
    h("div", { class: "hero-foot-k" }, h("span", { class: "fact-k" }, "시즌별 비중"), h("span", { class: "muted small" }, note)),
    h("div", { class: "wb-list" }, [...shares].reverse().map(({ c, share }) => card(app.model.bySeason.get(c.season), share, c.live))));
}

function elementBody(app, view, element) {
  const { state, model } = app;
  const ko = ELEMENT_KO[element];
  const { rows, seen, unseen } = weakRows(app, view, element);
  const table = state.mode === "table";
  const explain = h("p", { class: "note" },
    `▶ = ${ko} 니케. `, h("span", { class: "heart-text" }, "♥"), " = 애장품을 낀 시즌만으로 매김. ", lifeNote(app, table));
  if (table) return h("div", { class: "panel table-panel" }, elementTable(app, view, rows, element), explain);
  const board = tierBoard(app, seen.map((r) => ({ u: r.u, tier: r.tier, value: r.slot.lift, r })), {
    key: `element-${element}-${state.season ?? "now"}`,
    card: (it) => unitCard(app, it.u, {
      value: it.value, tier: it.tier, heart: it.r.o.treasure, retired: view.life.get(it.u)?.retired,
      extra: it.r.slot.own ? h("span", { class: "tag own-tag", title: `${ko} 니케 — 자기 속성 약점` }, `▶ ${ko}`) : null,
      tip: () => standingTip(app, it.u, view, { element }),
    }),
    note: explain,
  });
  if (unseen.length) {
    board.insertBefore(h("section", { class: "tier-row unseen", "aria-label": `미관측 ${unseen.length}명` },
      h("div", { class: "tier-label" }, h("span", { class: "tier-letter small" }, "미관측"), h("span", { class: "tier-count" }, `${unseen.length}명`)),
      h("div", { class: "cards" }, unseen.map((r) => unitCard(app, r.u, {
        tier: "D", dim: true, heart: r.o.treasure,
        tip: () => standingTip(app, r.u, view, { element }),
      })), h("span", { class: "row-note muted" }, `출시${unseen.some((r) => r.o.treasure) ? "·애장품" : ""} 뒤 ${ko} 약점 시즌을 아직 못 겪음`))),
    board.lastChild);
  }
  return board;
}

function elementTable(app, view, rows, element) {
  const { state, model } = app;
  const ko = ELEMENT_KO[element];
  const sort = state.sort.element || { key: "lift", dir: "desc" };
  const columns = [
    { key: "rank", label: "#", num: true, sort: (r) => r.rank, firstDir: "asc", cell: (r) => r.rank ?? "–" },
    { key: "unit", label: "니케", head: true, sort: (r) => model.units[r.u].ko, firstDir: "asc",
      cell: (r) => unitInline(app, r.u, { sub: r.slot.own ? `▶ ${ko} 니케` : null }) },
    { key: "lift", label: `${ko} 약점`, title: `${ko} 약점 시즌들의 기여도 (최근일수록 크게)`, sort: (r) => (r.slot.seasons ? r.slot.lift : null),
      cell: (r) => (r.slot.seasons ? tierBadge(r.tier, r.slot.lift) : h("span", { class: "muted" }, "미관측")) },
    { key: "seasons", label: "약점 시즌", title: `겪은 ${ko} 약점 시즌 수`, num: true, sort: (r) => r.slot.seasons, cell: (r) => `${r.slot.seasons}번` },
    { key: "overall", label: "종합", sort: (r) => r.o.overall, cell: (r) => h("span", null, tierBadge(r.o.tier, r.o.overall),
      r.o.provisional ? h("sup", { class: "muted" }, "*") : null, h("span", { class: "muted" }, ` ${r.o.rank}위`)) },
    ...lifeColumns(app, view),
  ];
  return sortableTable(columns, rows, {
    sortKey: sort.key, sortDir: sort.dir, caption: `${ko} 약점 티어 비교표`,
    onSort: (key, dir) => { state.sort.element = { key, dir }; app.rerender(); },
  });
}
