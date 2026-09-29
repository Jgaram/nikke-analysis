// 티어표 · 레이드별: one Solo Raid season, every unit by its lift that season. The seasons of
// one weakness side by side are 티어 변화 · 니케 비교 with that weakness (trend.js).

import { assignTier } from "../model.js";
import {
  h, num, pct, int, elementIcon, ELEMENT_KO, shortDay, tierBadge, deckSplit, sortableTable, toggle, kst,
} from "../ui.js";
import { unitCard, tierBoard, filterRow, modeSwitch, seasonTip, unitInline, kindTabs } from "./common.js";
import { timeStrip } from "./when.js";

const END_KO = { suspended: "중단", extended: "연장", superseded: "일정 변경", scheduled: "" };

export function seasonView(app) {
  const { model, state } = app;
  const pop = app.population();
  const number = state.season ?? app.latestSeason();
  const info = model.bySeason.get(number);
  const entry = pop.tables.get(number) || null;
  const root = h("div", { class: "view view-season" });
  root.append(kindTabs(app), timeStrip(app), header(app, info, entry));
  if (!entry) {
    root.append(h("div", { class: "panel empty" }, "고른 표본(서버)에 이 시즌 랭킹이 없습니다."));
    return root;
  }

  const cuts = state.params.cuts;
  const rows = entry.rows.filter((r) => app.passes(model.units[r.u]));
  const unused = rows.filter((r) => r.rankers === 0).length;
  const shown = state.showUnused ? rows : rows.filter((r) => r.rankers > 0);

  root.append(h("div", { class: "toolbar" },
    filterRow(app),
    h("div", { class: "toolbar-end" },
      unused ? toggle(`안 쓴 니케 ${unused}명도`, state.showUnused, (v) => { state.showUnused = v; app.rerender(); }) : null,
      modeSwitch(app))));
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

// The boss's weakness: pressing it goes to that weakness's tier as of this season; beside it,
// the way to those seasons side by side (티어 변화 · 니케 비교 with that weakness).
function weakFact(app, weak) {
  const inner = [h("span", { class: "fact-k" }, "약점"), elementIcon(weak, 18), h("b", null, ELEMENT_KO[weak] || "?")];
  if (!ELEMENT_KO[weak]) return h("span", { class: "fact" }, inner);
  return h("span", { class: "fact-pair" },
    h("a", { class: "fact fact-btn", href: app.tierHref(weak), title: `이 시즌까지의 ${ELEMENT_KO[weak]} 약점 티어로` },
      inner, h("span", { class: "fact-more" }, "약점 티어 ›")),
    h("a", { class: "fact fact-link", href: app.weakHref(weak), title: `${ELEMENT_KO[weak]} 약점 시즌들을 그래프와 표로 나란히` },
      "이 약점 시즌 비교 ›"));
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
