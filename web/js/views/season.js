// 시즌별 티어: one Solo Raid season, every unit by its lift that season - or, with a weakness
// chosen, every season of that weakness side by side (모아 보기).

import { assignTier, ELEMENTS } from "../model.js";
import {
  h, num, pct, int, elementIcon, ELEMENT_KO, shortDay, tierBadge, deckSplit, sortableTable, toggle, kst,
} from "../ui.js";
import { unitCard, tierBoard, filterRow, modeSwitch, seasonTip, unitInline } from "./common.js";

const END_KO = { suspended: "중단", extended: "연장", superseded: "일정 변경", scheduled: "" };

export function seasonView(app) {
  const { model, state } = app;
  const pop = app.population();
  const number = state.season ?? app.latestSeason();
  const info = model.bySeason.get(number);
  const entry = pop.tables.get(number) || null;
  const root = h("div", { class: "view view-season" });
  root.append(strip(app, number, pop), header(app, info, entry));
  if (!entry) {
    root.append(h("div", { class: "panel empty" }, "고른 표본(서버)에 이 시즌 랭킹이 없습니다."));
    return root;
  }

  const cuts = state.params.cuts;
  const rows = entry.rows.filter((r) => app.passes(model.units[r.u]));
  const unused = rows.filter((r) => r.rankers === 0).length;
  const shown = state.showUnused ? rows : rows.filter((r) => r.rankers > 0);
  const compare = state.mode === "compare" && state.weak;

  root.append(h("div", { class: "toolbar" },
    filterRow(app),
    h("div", { class: "toolbar-end" },
      unused && !compare ? toggle(`안 쓴 니케 ${unused}명도`, state.showUnused, (v) => { state.showUnused = v; app.rerender(); }) : null,
      modeSwitch(app, { compare: Boolean(state.weak) }))));

  if (compare) {
    root.append(compareTable(app, pop, state.weak));
    return root;
  }
  if (state.mode === "table") {
    root.append(seasonTable(app, entry, shown));
    return root;
  }
  const items = shown.map((r) => ({ u: r.u, tier: assignTier(r.lift, cuts), value: r.lift, row: r }));
  root.append(tierBoard(app, items, {
    key: `season-${number}`,
    card: (it) => unitCard(app, it.u, {
      value: it.value, tier: it.tier, heart: it.row.treasure, dim: it.row.rankers === 0,
      tip: () => seasonTip(app, it.row, entry),
    }),
    note: h("p", { class: "note" },
      "숫자 = 그 시즌 기여도: 상위 랭커의 대미지를 덱에 든 니케끼리 나눈 몫, 25명이 똑같이 나누면 1.0. ",
      h("span", { class: "heart-text" }, "♥"), " = 애장품을 끼고 치른 시즌. 얼굴을 누르면 그 니케의 티어 변화로."),
  }));
  return root;
}

// The season strip. With a weakness chosen (``state.weak``) it holds that weakness's seasons only,
// and the steps go from one of them to the next.
function strip(app, selected, pop) {
  const weak = app.state.weak;
  const seasons = weak ? app.model.seasons.filter((s) => s.weak === weak || s.season === selected) : app.model.seasons;
  const index = seasons.findIndex((s) => s.season === selected);
  const list = h("div", { class: "strip-list" }, seasons.map((s) => {
    const entry = pop.tables.get(s.season);
    const boss = s.bossKo || s.bossEn || "?";
    return h("a", {
      class: ["schip", s.season === selected && "on", !entry && "off", entry && !entry.final && "live"],
      href: app.href("season", s.season), "aria-current": s.season === selected ? "true" : null,
      title: `시즌 ${s.season} · ${boss} · 약점 ${ELEMENT_KO[s.weak] || "?"}${entry && !entry.final ? " · 진행 중" : ""}`,
    }, h("span", { class: "schip-n" }, s.season),
    s.bossImage ? h("img", { class: "schip-boss", src: `icons/bosses/${s.bossImage}.webp`, alt: "", width: 36, height: 36, loading: "lazy", decoding: "async" })
      : h("span", { class: "schip-boss none", "aria-hidden": "true" }),
    elementIcon(s.weak, 14, { title: "" }));
  }));
  // The chosen season goes to the middle: the strip slides there from where the one on
  // screen was, or starts there when the season tab is just opened.
  const before = document.querySelector(".view-season .strip-list")?.scrollLeft;
  requestAnimationFrame(() => {
    const on = list.querySelector(".schip.on");
    if (!on) return;
    const left = on.offsetLeft - (list.clientWidth - on.offsetWidth) / 2;
    if (before == null) { list.scrollLeft = left; return; }
    list.scrollLeft = before;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    list.scrollTo({ left, behavior: still ? "auto" : "smooth" });
  });
  const step = (d, label) => {
    const target = seasons[index + d];
    return target ? h("a", { class: "strip-step", href: app.href("season", target.season), "aria-label": label }, d < 0 ? "‹" : "›")
      : h("span", { class: "strip-step off", "aria-hidden": "true" }, d < 0 ? "‹" : "›");
  };
  const only = weak ? h("button", {
    type: "button", class: "strip-only", title: `${ELEMENT_KO[weak]} 약점 시즌만 보는 중 · 누르면 전체 시즌`,
    "aria-label": `${ELEMENT_KO[weak]} 약점 시즌만 보는 중, 누르면 전체 시즌`,
    onclick: () => app.go({ weak: null, mode: app.state.mode === "compare" ? "tiers" : app.state.mode }, { replace: true }),
  }, elementIcon(weak, 15, { title: "" }), h("span", { class: "strip-only-n" }, `${seasons.length}`), h("span", { "aria-hidden": "true" }, "×"))
    : null;
  const label = weak ? `${ELEMENT_KO[weak]} 약점 시즌 고르기` : "시즌 고르기";
  return h("nav", { class: ["strip", weak && "filtered"], "aria-label": label },
    only, step(-1, weak ? `이전 ${ELEMENT_KO[weak]} 약점 시즌` : "이전 시즌"), list,
    step(1, weak ? `다음 ${ELEMENT_KO[weak]} 약점 시즌` : "다음 시즌"));
}

function period([start, end, reason], first) {
  const a = kst(start);
  const from = first ? `${a.y}-${a.m}-${a.d} ${a.hh}:${a.mm}` : `${a.m}/${a.d} ${a.hh}:${a.mm}`;
  const to = end != null ? (() => { const b = kst(end); return `${b.m}/${b.d} ${b.hh}:${b.mm}`; })() : "추후 안내";
  return `${from} ~ ${to}${END_KO[reason] ? ` (${END_KO[reason]})` : ""}`;
}

function header(app, info, entry) {
  const cuts = app.state.params.cuts;
  const boss = info.bossKo || info.bossEn || "?";
  const status = entry ? (entry.final ? h("span", { class: "status done" }, "종료")
    : h("span", { class: "status live" }, h("i", { class: "pulse", "aria-hidden": "true" }), `진행 중 · ${shortDay(entry.collectedOn)} 수집분까지 (잠정)`))
    : h("span", { class: "status" }, "랭킹 없음");
  const counts = {};
  let used = 0;
  if (entry) {
    for (const r of entry.rows) {
      if (!r.rankers) continue;
      used++;
      const t = assignTier(r.lift, cuts);
      counts[t] = (counts[t] || 0) + 1;
    }
  }
  const all = entry && entry.servers.length === app.model.servers.length;
  const sample = entry ? `${all ? `${entry.servers.length}개 서버` : entry.servers.join("·")} × 상위 ${app.state.params.topN}위 = ${int(entry.rankers)}명 · 덱 ${int(entry.decks)}개` : null;
  return h("section", { class: ["hero", info.bossImage && "has-boss"] },
    h("div", { class: "hero-num" }, h("small", null, "SEASON"), h("b", null, info.season)),
    info.bossImage ? h("img", {
      class: "hero-boss", src: `icons/bosses/${info.bossImage}.webp`, alt: "", width: 256, height: 256, decoding: "async",
    }) : null,
    h("div", { class: "hero-main" },
      h("div", { class: "hero-top" }, status, info.disrupted ? h("span", { class: "status warn" }, "일정 변동 있음") : null),
      h("h2", { class: "hero-title" }, boss, info.bossKo && info.bossEn ? h("span", { class: "hero-sub" }, info.bossEn) : null),
      h("div", { class: "hero-facts" },
        h("span", { class: "fact" }, h("span", { class: "fact-k" }, "보스"), elementIcon(info.bossElement, 18), ELEMENT_KO[info.bossElement] || "?"),
        weakFact(app, info.weak),
        info.periods.length ? h("span", { class: "fact" }, h("span", { class: "fact-k" }, "기간"),
          info.periods.map((p, i) => h("span", { class: "period" }, period(p, i === 0)))) : null),
      sample ? h("div", { class: "hero-sample muted" }, `표본 ${sample} · 니케 ${int(used)}명 사용 (당시 ${int(entry.rows.length)}명 중)`) : null),
    entry ? h("div", { class: "hero-counts", "aria-label": "시즌 티어별 인원" }, cuts.map(([t]) => h("span", { class: "count", dataset: { tier: t } },
      h("b", null, t), h("span", null, counts[t] || 0)))) : null);
}

// The boss's weakness; pressing it keeps the strip to the seasons of that weakness (and back).
function weakFact(app, weak) {
  const inner = [h("span", { class: "fact-k" }, "약점"), elementIcon(weak, 18), h("b", null, ELEMENT_KO[weak] || "?")];
  if (!ELEMENT_KO[weak]) return h("span", { class: "fact" }, inner);
  const on = app.state.weak === weak;
  return h("button", {
    type: "button", class: "fact fact-btn", "aria-pressed": String(on),
    title: on ? "전체 시즌 보기" : `${ELEMENT_KO[weak]} 약점 시즌만 모아 보기`,
    onclick: () => app.go(on ? { weak: null, mode: app.state.mode === "compare" ? "tiers" : app.state.mode } : { weak },
      { replace: true }),
  }, inner, h("span", { class: "fact-more" }, on ? "모아 보는 중" : "시즌만 보기"));
}

// 모아 보기: every season whose boss was weak to ``weak``, side by side, newest first - each unit's
// lift in each - with the unit's standing in that weakness now: the slot of its overall tier for
// it (the recent-weighted mean over those seasons), whatever the unit's own element.
function compareTable(app, pop, weak) {
  const { model, state } = app;
  const cuts = state.params.cuts;
  const ko = ELEMENT_KO[weak];
  const seasons = model.seasons.filter((s) => s.weak === weak && pop.tables.has(s.season)).reverse();
  const bySeason = new Map(seasons.map((s) => [s.season, new Map(pop.tables.get(s.season).rows.map((r) => [r.u, r]))]));
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
  const sort = state.sort.compare || { key: "slot", dir: "desc" };
  const columns = [
    { key: "unit", label: "니케", head: true, sort: (r) => model.units[r.u].ko || model.units[r.u].en, firstDir: "asc",
      cell: (r) => unitInline(app, r.u) },
    { key: "slot", label: `${ko} 약점 종합`,
      title: `지금 기준, ${ko} 약점 시즌들의 기여도를 최근일수록 크게 친 평균 — 종합 티어를 이루는 다섯 칸 중 하나. `
        + "니케의 속성이 아니라 보스 약점 기준이라 다른 속성 서포터도 든다",
      sort: (r) => r.slot?.lift, cell: (r) => {
        if (!r.slot) return h("span", { class: "muted" }, "–");
        if (!r.slot.seasons) return h("span", { class: "muted", title: "애장품 뒤로는 이 약점 시즌을 아직 못 겪어 채운 값" }, `(${num(r.slot.lift)})`);
        return tierBadge(assignTier(r.slot.lift, cuts), r.slot.lift);
      } },
    { key: "fielded", label: "쓰인", num: true, title: `상위 랭커가 쓴 ${ko} 약점 시즌 수`, sort: (r) => r.fielded,
      cell: (r) => h("span", null, int(r.fielded), h("span", { class: "muted" }, `/${seasons.length}`)) },
    ...seasons.map((s) => ({
      key: `s${s.season}`, class: "cmp-season",
      title: `시즌 ${s.season} · ${s.bossKo || s.bossEn || "?"}${pop.tables.get(s.season).final ? "" : " · 진행 중"}`,
      label: h("span", { class: "cmp-head" },
        s.bossImage ? h("img", { src: `icons/bosses/${s.bossImage}.webp`, alt: "", width: 28, height: 28, loading: "lazy" }) : null,
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
  return h("div", { class: "panel table-panel compare-panel" },
    sortableTable(columns, units, {
      sortKey: sort.key, sortDir: sort.dir, caption: `${ko} 약점 시즌 모아 보기`,
      onSort: (key, dir) => { state.sort.compare = { key, dir }; app.rerender(); },
    }),
    h("p", { class: "note" },
      `${ko} 약점 시즌 ${seasons.length}개를 최근 시즌부터 나란히. 칸 = 그 시즌 기여도와 시즌 티어 · · = 안 씀 · 빈칸 = 그땐 없던 니케 · `,
      h("span", { class: "heart-text" }, "♥"), " = 애장품을 끼고 치른 시즌. ",
      `${ko} 약점 종합 = 종합 티어를 이루는 칸 하나(지금 기준, 최근 시즌일수록 크게). 니케 속성이 아니라 보스 약점 기준이라 `
        + "다른 속성 서포터도 든다. 괄호 = 애장품 뒤로는 아직 못 겪어 채운 값. 열 이름을 누르면 정렬."));
}

function seasonTable(app, entry, rows) {
  const { state } = app;
  const cuts = state.params.cuts;
  const history = app.history().get(entry.season) || new Map();
  const liftRank = new Map();
  [...entry.rows].sort((a, b) => b.lift - a.lift).forEach((r, i, all) => {
    liftRank.set(r.u, i > 0 && all[i - 1].lift === r.lift ? liftRank.get(all[i - 1].u) : i + 1);
  });
  const sort = state.sort.season || { key: "lift", dir: "desc" };
  const columns = [
    { key: "rank", label: "#", num: true, sort: (r) => liftRank.get(r.u), firstDir: "asc", cell: (r) => liftRank.get(r.u) },
    { key: "unit", label: "니케", head: true, sort: (r) => app.model.units[r.u].ko || app.model.units[r.u].en, firstDir: "asc",
      cell: (r) => unitInline(app, r.u, { sub: r.treasure ? "♥ 애장품" : null }) },
    { key: "lift", label: "기여도", title: "그 시즌 기여도와 시즌 티어", sort: (r) => r.lift,
      cell: (r) => tierBadge(assignTier(r.lift, cuts), r.lift) },
    { key: "rankers", label: "사용", title: "그 니케를 쓴 랭커 수와 비율", num: true, sort: (r) => r.rankers,
      cell: (r) => (r.rankers ? h("span", null, int(r.rankers), h("span", { class: "muted" }, ` ${pct(r.usageRate)}`)) : "–") },
    { key: "split", label: "덱 분포", title: "쓴 사람 중 몇 번째로 센 덱에 넣었나 (1덱 = 가장 센 덱)", sort: (r) => r.rankers ? -r.avgDeck : null,
      cell: (r) => deckSplit(r.inDeck, r.rankers) },
    { key: "main", label: "1덱", num: true, title: "쓴 사람 중 가장 센 덱에 넣은 비율", sort: (r) => (r.rankers ? r.inDeck[0] / r.rankers : null),
      cell: (r) => (r.rankers ? pct(r.inDeck[0] / r.rankers) : "–") },
    { key: "avg", label: "평균 덱", num: true, sort: (r) => (r.rankers ? r.avgDeck : null), firstDir: "asc", cell: (r) => (r.rankers ? num(r.avgDeck) : "–") },
    { key: "element", label: "속성 티어", title: "그 시즌이 끝났을 때의 속성 티어 (보스 약점이 이 니케의 속성인 시즌만)",
      sort: (r) => history.get(r.u)?.elementLift, cell: (r) => {
        const x = history.get(r.u);
        return x && x.counted && !Number.isNaN(x.elementLift) ? tierBadge(x.elementTier, x.elementLift) : h("span", { class: "muted" }, "–");
      } },
    { key: "overall", label: "종합 티어", title: "그 시즌이 끝났을 때의 종합 티어", sort: (r) => history.get(r.u)?.overall,
      cell: (r) => {
        const x = history.get(r.u);
        return x && !Number.isNaN(x.overall) ? h("span", null, tierBadge(x.overallTier, x.overall), x.provisional ? h("sup", { class: "muted" }, "*") : null)
          : h("span", { class: "muted" }, "–");
      } },
  ];
  return h("div", { class: "panel table-panel" },
    sortableTable(columns, rows, {
      sortKey: sort.key, sortDir: sort.dir, caption: `시즌 ${entry.season} 니케별 기여도`,
      onSort: (key, dir) => { state.sort.season = { key, dir }; app.rerender(); },
      rowAttrs: (r) => ({ class: r.rankers ? null : "dim" }),
    }),
    h("p", { class: "note" }, "속성·종합 티어 = 그 시즌이 끝났을 때 기준 (진행 중 시즌은 지금까지). * = 잠정. 열 이름을 누르면 정렬."));
}
