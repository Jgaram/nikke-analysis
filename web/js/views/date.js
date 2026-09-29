// 티어표 · 종합 / 약점: where every unit stood on a day - overall, or when the boss is weak
// to one element (every unit, whatever its own element) - and how long each has been in use.

import { ELEMENTS, assignTier, seasonWeight } from "../model.js";
import {
  h, elementIcon, ELEMENT_KO, day, shortDay, todayKst, noonKst, tierBadge, sortableTable, kst,
} from "../ui.js";
import {
  unitCard, tierBoard, filterRow, modeSwitch, standingTip, unitInline, provisionalReason, lifeColumns, retiredText, kindTabs,
} from "./common.js";

const OVERALL_KO = {
  mean: "보스 약점 다섯 가지 성적의 평균",
  frequency: "보스 약점 다섯 가지 성적을 최근 자주 나온 약점일수록 크게 친 평균",
  max: "보스 약점 다섯 가지 중 겪어 본 가장 잘한 성적",
};
const FIRST_DAY = "2023-05-18"; // the first season's end

const DAY_MS = 86400000;
const RAID_AFTER_DAYS = 21; // an anniversary's raid opens within three weeks of the day, if not on it

// Every half anniversary of the launch - 0.5주년, 1주년, 1.5주년, ... - as {label, date, season},
// dated the day its Solo Raid was over so that raid counts: the raid open on the anniversary,
// else the first to open in the three weeks after it. The date is the first day whose noon
// (the moment a day is read at) is past the raid's end. An anniversary shows up once its raid
// is over by ``today``; one with no raid in those three weeks keeps its own day, once they
// have passed. None comes before the first season's end.
export function anniversaries(launch, seasons, today) {
  const t = kst(launch);
  const [y, m, d] = [Number(t.y), Number(t.m), Number(t.d)];
  const dated = seasons.filter((s) => s.start != null).sort((a, b) => a.start - b.start);
  const out = [];
  for (let half = 1; half <= 200; half++) {
    const months = m - 1 + 6 * half;
    const year = y + Math.floor(months / 12), month = (months % 12) + 1;
    const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const on = `${year}-${String(month).padStart(2, "0")}-${String(Math.min(d, last)).padStart(2, "0")}`;
    if (on > today) break;
    const noon = noonKst(on);
    const raid = dated.find((s) => s.start <= noon && (s.end == null || s.end >= noon))
      || dated.find((s) => s.start > noon && s.start <= noon + RAID_AFTER_DAYS * DAY_MS) || null;
    let date;
    if (raid) {
      if (raid.end == null) continue; // still on, or its end not known yet
      date = day(raid.end);
      if (noonKst(date) < raid.end) date = day(raid.end + DAY_MS);
    } else {
      if (day(noon + RAID_AFTER_DAYS * DAY_MS) > today) continue; // its raid may still open
      date = on;
    }
    if (date > today || date < FIRST_DAY) continue;
    out.push({ label: half % 2 ? `${(half - 1) / 2}.5주년` : `${half / 2}주년`, date, season: raid ? raid.season : null });
  }
  return out;
}

export function dateView(app) {
  const { state } = app;
  const moment = app.moment();
  const view = app.viewAt(moment);
  const root = h("div", { class: "view view-date" });
  root.append(kindTabs(app), dateBar(app), context(app, view));
  if (state.view !== "overall") root.append(weakBosses(app, view, state.view));
  if (!view.standing.overall.length) {
    root.append(h("div", { class: "panel empty" }, "이 날짜까지 끝난 시즌이 없습니다. 첫 시즌은 2023-05-18 에 끝났습니다."));
    return root;
  }
  root.append(h("div", { class: "toolbar" }, filterRow(app), h("div", { class: "toolbar-end" }, modeSwitch(app))));
  root.append(state.view === "overall" ? overallBody(app, view) : elementBody(app, view, state.view));
  return root;
}

// The day a view is read at: a date field, today, the half anniversaries and the days a
// season ended. The date tab and the unit tab share it (and the day, through the address).
export function dateBar(app) {
  const today = todayKst();
  const value = app.state.date || today;
  const presets = anniversaries(app.model.launch, app.model.seasons, today);
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
      presets.map((p) => {
        const s = p.season != null ? app.model.bySeason.get(p.season) : null;
        const title = s ? `${p.label} 솔로 레이드(시즌 ${s.season} ${s.bossKo || s.bossEn || ""})가 끝난 ${p.date} 기준 — 그 레이드까지 반영`
          : `${p.label} (${p.date})`;
        return h("button", { type: "button", class: ["preset", app.state.date === p.date && "on"], title, onclick: () => set(p.date) }, p.label);
      }),
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
  return h("a", { class: "around", href: app.seasonHref(s.season) },
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
    `종합 티어 = ${OVERALL_KO[state.params.overall]}. 약점은 니케의 속성이 아니라 보스 기준이다 — 다른 속성의 니케도 그 약점 덱에 쓰이므로. `,
    "* = 잠정 (겪은 보스 약점이 적거나 자기 속성 시즌을 아직 못 겪음) · ",
    h("span", { class: "heart-text" }, "♥"), " = 애장품을 낀 시즌만으로 매김. ", lifeNote(app, table));
  if (table) return h("div", { class: "panel table-panel" }, overallTable(app, view, rows), explain);
  const items = rows.map((o) => ({ u: o.u, tier: o.tier, value: o.overall, o }));
  return tierBoard(app, items, {
    key: `overall-${state.date || "now"}`, cuts: state.params.overallCuts,
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

// What a weakness tier stands on: the Solo Raid bosses weak to that element, newest first, each
// with its share of the recency weighting at the chosen day - and the next such boss, if it is
// on the calendar. The tier is the boss's weakness, not the units' element.
function weakBosses(app, view, element) {
  const ko = ELEMENT_KO[element];
  const params = app.state.params;
  const counted = view.standing.counted.filter((c) => c.weak === element);
  const weights = counted.map((c) => seasonWeight(c, view.moment, params));
  const total = weights.reduce((a, b) => a + b, 0) || 1;
  const next = app.model.seasons.find((s) => s.weak === element && s.start != null && s.start > view.moment
    && !counted.some((c) => c.season === s.season)) || null;
  const card = (s, { share = null, live = false, upcoming = false } = {}) => {
    const boss = s.bossKo || s.bossEn || "?";
    return h("a", {
      class: ["wb", live && "live", upcoming && "upcoming"], href: app.seasonHref(s.season),
      title: `시즌 ${s.season} · ${boss} · ${day(s.start)}${upcoming ? " 시작 예정 — 아직 반영 안 됨" : share != null ? ` · 이 티어의 ${Math.round(share * 100)}%` : ""}`,
    },
    s.bossImage ? h("img", { class: "wb-img", src: `icons/bosses/${s.bossImage}.webp`, alt: "", width: 44, height: 44, loading: "lazy", decoding: "async" })
      : h("span", { class: "wb-img none", "aria-hidden": "true" }),
    h("span", { class: "wb-text" },
      h("span", { class: "wb-top" }, h("b", null, `S${s.season}`), live ? h("span", { class: "pill live" }, "진행 중") : null,
        upcoming ? h("span", { class: "tag" }, "다음") : null),
      h("span", { class: "wb-name" }, boss),
      share != null ? h("span", { class: "wb-share", "aria-label": `반영 비중 ${Math.round(share * 100)}%` },
        h("i", { style: { width: `${Math.max(4, share * 100)}%` } }), h("small", null, `${Math.round(share * 100)}%`))
        : h("span", { class: "wb-when muted" }, upcoming ? `${shortDay(s.start)} 시작` : shortDay(s.start))));
  };
  const cards = counted.map((c, i) => ({ c, share: weights[i] / total })).reverse()
    .map(({ c, share }) => card(app.model.bySeason.get(c.season), { share, live: c.live }));
  return h("section", { class: "panel weak-intro" },
    h("div", { class: "wi-head" },
      h("span", { class: "wi-icon" }, elementIcon(element, 26, { title: "" })),
      h("div", { class: "wi-text" },
        h("h3", null, `보스 약점이 ${ko}인 솔로 레이드 ${counted.length}시즌으로 매긴 티어`),
        h("p", null, `${ko} 니케의 티어가 아닙니다. 아래 보스들을 상대로 상위 랭커가 쓴 니케를, 속성과 상관없이 모두 매깁니다. `
          + `최근 시즌일수록 크게 칩니다(막대 = 이 티어에서 그 시즌의 비중, 반감기 ${params.halfLifeDays}일).`))),
    counted.length || next
      ? h("div", { class: "wb-list" }, next ? card(next, { upcoming: true }) : null, cards)
      : h("p", { class: "note wi-empty" }, `이 날짜까지 보스 약점이 ${ko}인 시즌이 없습니다.`));
}

function elementBody(app, view, element) {
  const { state, model } = app;
  const ko = ELEMENT_KO[element];
  const { rows, seen, unseen } = weakRows(app, view, element);
  const seasons = view.standing.counted.filter((c) => c.weak === element)
    .map((c) => (c.live ? `${c.season}(진행 중)` : String(c.season)));
  const table = state.mode === "table";
  const explain = h("p", { class: "note" },
    `${ko} 약점 티어 = 보스 약점이 ${ko}이던 시즌${seasons.length ? `(${seasons.join(" · ")})` : ""}의 기여도를 최근일수록 크게 친 평균 — `,
    "종합 티어를 이루는 보스 약점별 다섯 칸 중 하나. 니케 속성과 무관하게 모든 니케가 들어서, 다른 속성이라도 이 약점 덱에 쓰이면 높다. ",
    "▶ = 이 속성의 니케(자기 속성 약점). ", h("span", { class: "heart-text" }, "♥"), " = 애장품을 낀 시즌만으로 매김. ", lifeNote(app, table));
  if (table) return h("div", { class: "panel table-panel" }, elementTable(app, view, rows, element), explain);
  const board = tierBoard(app, seen.map((r) => ({ u: r.u, tier: r.tier, value: r.slot.lift, r })), {
    key: `element-${element}-${state.date || "now"}`,
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
