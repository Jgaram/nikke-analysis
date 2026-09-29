// Pieces the three views share: a unit's card, the tier board, the filter row, tooltips.

import { ELEMENTS, DAY_MS, assignTier } from "../model.js";
import {
  h, num, pct, int, face, elementIcon, classIcon, burstIcon, nameLines, unitName, withTip, tierBadge, deckSplit,
  segmented, ELEMENT_KO, CLASS_KO, BURSTS, shortDay,
} from "../ui.js";

// ---------------------------------------------------------------------------
// a unit

export function unitCard(app, u, { value, tier, provisional, heart, dim, retired, tip, extra } = {}) {
  const unit = app.model.units[u];
  const [first, second] = nameLines(unit);
  const card = h("a", {
    class: ["card", dim && "dim", retired && "retired"], href: app.href("unit", unit.id), dataset: { tier: tier || "D" },
    "aria-label": `${unitName(unit)}${value != null ? ` ${num(value)}` : ""}${tier ? ` ${tier} 티어` : ""}${retired ? " 은퇴" : ""}`,
  },
  h("span", { class: "face" },
    face(unit, 64),
    elementIcon(unit.element, 18, { class: "card-el", title: "" }),
    provisional ? h("span", { class: "mark prov", "aria-hidden": "true" }, "*") : null,
    heart ? h("span", { class: "mark heart", "aria-hidden": "true" }, "♥") : null,
    value != null && !Number.isNaN(value) ? h("span", { class: "val" }, num(value)) : null),
  h("span", { class: "name" }, h("span", null, first), second ? h("span", null, second) : null),
  extra || null);
  if (tip) withTip(card, tip);
  return card;
}

export function unitHead(app, u) {
  const unit = app.model.units[u];
  const added = [...unit.extra];
  return h("div", { class: "tip-head" },
    face(unit, 40),
    h("div", null,
      h("div", { class: "tip-name" }, unitName(unit), unit.en && unit.ko ? h("span", { class: "muted" }, unit.en) : null),
      h("div", { class: "tip-attrs" },
        elementIcon(unit.element, 14), ELEMENT_KO[unit.element] || "?",
        added.length ? h("span", { class: "muted" }, `+ ${added.map((e) => ELEMENT_KO[e]).join("·")}`) : null,
        h("span", { class: "sep" }), classIcon(unit.class, 13), CLASS_KO[unit.class] || unit.class,
        h("span", { class: "sep" }), burstIcon(unit.burst), `버스트 ${unit.burst}`)));
}

export function unitInline(app, u, { size = 28, sub = null } = {}) {
  const unit = app.model.units[u];
  return h("a", { class: "unit-inline", href: app.href("unit", unit.id) },
    face(unit, size),
    h("span", { class: "unit-inline-text" },
      h("span", { class: "unit-inline-name" }, unitName(unit)),
      sub ? h("span", { class: "unit-inline-sub" }, sub) : null),
    elementIcon(unit.element, 14, { class: "unit-inline-el" }));
}

// ---------------------------------------------------------------------------
// the tier board: one row per tier, best first

function cutText(cuts, i) {
  const [, lo] = cuts[i];
  if (i === cuts.length - 1) return i > 0 ? `< ${num(cuts[i - 1][1])}` : "";
  return `≥ ${num(lo)}`;
}

// The bottom tier (F: next to no use) starts folded; the others show up to ``collapseAt`` cards.
export function tierBoard(app, items, { key, card, collapseAt = 36, empty = "없음", note = null }) {
  const cuts = app.state.params.cuts;
  const board = h("div", { class: "board" });
  const toggle = (id, on) => { if (on) app.state.expanded.add(id); else app.state.expanded.delete(id); app.rerender(); };
  cuts.forEach(([label], i) => {
    const group = items.filter((it) => it.tier === label);
    const id = `${key}:${label}`;
    const open = app.state.expanded.has(id);
    const foldable = i === cuts.length - 1 && i > 0;
    const shown = open || (!foldable && group.length <= collapseAt + 4) ? group
      : foldable ? [] : group.slice(0, collapseAt);
    const cards = h("div", { class: "cards" }, shown.map(card));
    if (!group.length) cards.append(h("span", { class: "row-empty" }, empty));
    else if (foldable) {
      cards.append(h("button", {
        type: "button", class: ["fold", open && "open"], "aria-expanded": String(open), onclick: () => toggle(id, !open),
      }, open ? "접기" : [h("b", null, `${group.length}명`), " 펼치기 · 거의 안 쓰인 니케"]));
    } else if (shown.length < group.length) {
      cards.append(h("button", { type: "button", class: "more", onclick: () => toggle(id, true) },
        h("b", null, `+${group.length - shown.length}`), "명 더 보기"));
    }
    board.append(h("section", {
      class: ["tier-row", foldable && !open && group.length && "folded"], dataset: { tier: label },
      "aria-label": `${label} 티어 ${group.length}명`,
    },
      h("div", { class: "tier-label" },
        h("span", { class: "tier-letter" }, label),
        h("span", { class: "tier-cut" }, cutText(cuts, i)),
        h("span", { class: "tier-count" }, `${group.length}명`)),
      cards));
  });
  if (note) board.append(note);
  return board;
}

// ---------------------------------------------------------------------------
// filters and switches

export function filterRow(app) {
  const f = app.state.filters;
  const any = f.elements.size || f.classes.size || f.bursts.size;
  const chip = (set, value, content, title) => h("button", {
    type: "button", class: "fchip", "aria-pressed": String(set.has(value)), title,
    onclick: () => { if (set.has(value)) set.delete(value); else set.add(value); app.rerender(); },
  }, content);
  return h("div", { class: "filters", role: "group", "aria-label": "필터" },
    h("div", { class: "fgroup", role: "group", "aria-label": "속성" },
      ELEMENTS.map((e) => chip(f.elements, e, elementIcon(e, 17, { title: "" }), ELEMENT_KO[e]))),
    h("div", { class: "fgroup", role: "group", "aria-label": "클래스" },
      ["Attacker", "Supporter", "Defender"].map((c) => chip(f.classes, c, [classIcon(c, 15), h("span", { class: "fl" }, CLASS_KO[c])], CLASS_KO[c]))),
    h("div", { class: "fgroup", role: "group", "aria-label": "버스트" },
      BURSTS.map((b) => chip(f.bursts, b, burstIcon(b), `버스트 ${b}`))),
    any ? h("button", {
      type: "button", class: "fclear",
      onclick: () => { f.elements.clear(); f.classes.clear(); f.bursts.clear(); app.rerender(); },
    }, "필터 해제") : null);
}

export function modeSwitch(app) {
  return segmented([
    { value: "tiers", label: "티어표" }, { value: "table", label: "표" },
  ], app.state.mode, (v) => app.go({ mode: v }, { replace: true }), { class: "mode", label: "보기" });
}

// ---------------------------------------------------------------------------
// a unit's lifespan: since when top rankers used it, how often, and whether they still do

export function duration(days) {
  if (days == null || Number.isNaN(days)) return "–";
  const months = Math.round(days / 30.44);
  if (months < 1) return `${Math.max(1, Math.round(days / 7))}주`;
  if (months < 12) return `${months}개월`;
  const years = Math.floor(months / 12), rest = months % 12;
  return rest ? `${years}년 ${rest}개월` : `${years}년`;
}

// What the view says of unit ``u``'s lifespan, in words: its state and two lines.
export function lifeText(app, view, u) {
  const a = view.life.get(u);
  if (!a || a.lastUsed == null) {
    const min = Math.round(app.state.params.minUsage * 100);
    return { a, state: "never", label: "안 쓰임", main: "쓰인 시즌 없음", sub: `사용 ${min}%를 넘은 시즌이 없음`, length: null };
  }
  const counted = view.standing.counted;
  const latest = counted.length ? counted[counted.length - 1].season : null;
  if (a.retired) {
    const length = a.lastEnd - a.runStart;
    return {
      a, state: "retired", label: "은퇴", length,
      main: a.runFrom === a.lastUsed ? `S${a.lastUsed} 한 시즌` : `S${a.runFrom}–S${a.lastUsed} · ${duration(length / DAY_MS)}`,
      sub: `S${a.lastUsed} 뒤 ${duration(a.idleDays)}째 안 쓰임`,
    };
  }
  const length = view.moment - a.runStart;
  const recent = a.lastUsed === latest;
  return {
    a, state: "active", label: "현역", length, recent,
    main: `S${a.runFrom}부터 · ${duration(length / DAY_MS)}째`,
    sub: recent ? "최근 시즌까지 쓰임" : `마지막 S${a.lastUsed} · ${duration(a.idleDays)} 전`,
  };
}

export function lifePill(text) {
  return h("span", { class: ["life-pill", text.state] }, text.label);
}

export function returnTag(app, a) {
  if (!a || !a.returns) return null;
  const gap = duration(app.state.params.retireAfterDays);
  return h("span", {
    class: "tag", title: `S${a.firstUsed}부터 쓰이다 ${gap} 넘게 안 쓰인 적이 ${a.returns}번 · 이번에는 S${a.runFrom}부터 다시 쓰임`,
  }, a.returns > 1 ? `복귀 ${a.returns}번` : "복귀");
}

// One cell per season the view counts: blank before the unit was out, faint when out
// and unused, filled when used - the more rankers used it, the stronger.
export function lifeStrip(app, view, u, { width = 150 } = {}) {
  const pop = app.population();
  const min = app.state.params.minUsage;
  const counted = view.standing.counted;
  const a = view.life.get(u);
  const strip = h("span", {
    class: "life-strip", role: "img",
    style: { width: `${width}px`, gridTemplateColumns: `repeat(${Math.max(1, counted.length)}, 1fr)` },
    "aria-label": counted.length
      ? `시즌 ${counted[0].season}–${counted[counted.length - 1].season} 중 ${a?.seasonsUsed ?? 0}시즌 쓰임` : "시즌 없음",
  });
  for (const c of counted) {
    const r = pop.tables.get(c.season)?.byUnit.get(u);
    if (!r) strip.append(h("i", { class: "pre" }));
    else if (!(r.usageRate >= min)) strip.append(h("i", { class: "idle" }));
    else strip.append(h("i", { class: "used", style: { opacity: String(0.35 + 0.65 * Math.min(1, r.usageRate)) } }));
  }
  return strip;
}

export function lifeHeader(view, label = "시즌별 사용") {
  const counted = view.standing.counted;
  return h("span", { class: "life-th" }, label,
    counted.length ? h("span", { class: "life-axis", "aria-hidden": "true" },
      h("span", null, `S${counted[0].season}`), h("span", null, `S${counted[counted.length - 1].season}`)) : null);
}

// The lifespan columns of a date-view table; its rows carry the unit as ``.u``.
export function lifeColumns(app, view) {
  const texts = new Map();
  const of = (row) => {
    if (!texts.has(row.u)) texts.set(row.u, lifeText(app, view, row.u));
    return texts.get(row.u);
  };
  const { minUsage, retireAfterDays } = app.state.params;
  return [
    { key: "strip", label: lifeHeader(view), class: "life-col", firstDir: "asc",
      title: `시즌 하나가 칸 하나. 칠한 칸 = 상위 랭커 ${Math.round(minUsage * 100)}% 이상이 쓴 시즌(진할수록 많이), `
        + "옅은 칸 = 나와 있었지만 거의 안 쓴 시즌. 정렬하면 처음 쓰인 시즌 순",
      sort: (row) => of(row).a?.firstUsed, cell: (row) => lifeStrip(app, view, row.u) },
    { key: "state", label: "상태", firstDir: "asc",
      title: `마지막으로 쓰인 시즌이 끝나고 ${retireAfterDays}일 동안 안 쓰이면 은퇴. 정렬하면 최근에 쓰인 순`,
      sort: (row) => {
        const t = of(row);
        return t.state === "never" ? null : (t.state === "retired" ? 1e6 : 0) + t.a.idleDays;
      },
      cell: (row) => lifePill(of(row)) },
    { key: "life", label: "수명", title: "지금 흐름(복귀했으면 복귀한 뒤)이 언제부터 얼마나 이어졌나. 정렬하면 긴 순",
      sort: (row) => of(row).length,
      cell: (row) => {
        const t = of(row);
        return h("span", { class: "life-cell" },
          h("span", { class: "life-main" }, t.main, returnTag(app, t.a)),
          t.recent ? null : h("span", { class: "life-sub" }, t.sub));
      } },
    { key: "used", label: "쓰인 시즌", num: true, title: "쓰인 시즌 / 출시 뒤 치른 시즌",
      sort: (row) => of(row).a?.seasonsUsed,
      cell: (row) => {
        const a = of(row).a;
        return a ? h("span", null, h("b", null, a.seasonsUsed), h("span", { class: "muted" }, ` / ${a.seasonsOut}`)) : "–";
      } },
  ];
}

// ---------------------------------------------------------------------------
// tooltips

export function seasonTip(app, row, entry) {
  const cuts = app.state.params.cuts;
  const tier = assignTier(row.lift, cuts);
  return h("div", { class: "tip" },
    unitHead(app, row.u),
    h("div", { class: "tip-main" }, tierBadge(tier, row.lift), h("span", { class: "muted" }, `시즌 ${entry.season} 기여도`)),
    h("dl", { class: "tip-list" },
      h("dt", null, "사용"), h("dd", null, `${int(row.rankers)}명 · ${pct(row.usageRate)}`, h("span", { class: "muted" }, ` (사용 순위 ${row.usageRank}위)`)),
      row.rankers ? [h("dt", null, "덱 분포"), h("dd", null, deckSplit(row.inDeck, row.rankers, 120),
        h("span", { class: "muted" }, ` 1덱 ${pct(row.inDeck[0] / row.rankers)} · 평균 ${num(row.avgDeck)}덱`))] : null,
      row.rankers ? [h("dt", null, "최고 순위"), h("dd", null, `${row.bestRank}위`)] : null),
    h("div", { class: "tip-notes" },
      row.elementMatch ? h("span", { class: "pill" }, "▶ 자기 속성 약점 시즌") : null,
      row.treasure ? h("span", { class: "pill heart" }, "♥ 애장품을 낀 시즌") : null));
}

export function standingTip(app, u, view, { element = null } = {}) {
  const o = view.standing.overallByUnit.get(u);
  const mine = view.standing.elements.filter((r) => r.u === u);
  const slots = view.standing.slots.get(u);
  const counts = new Map();
  for (const r of view.standing.elements) counts.set(r.element, (counts.get(r.element) || 0) + 1);
  const unit = app.model.units[u];
  const life = lifeText(app, view, u);
  return h("div", { class: "tip" },
    unitHead(app, u),
    h("dl", { class: "tip-list" },
      o ? [h("dt", null, "종합"), h("dd", null, tierBadge(o.tier, o.overall), ` ${view.standing.overall.length}명 중 ${o.rank}위`,
        o.provisional ? h("span", { class: "muted" }, " · 잠정") : null)] : null,
      mine.map((r) => [h("dt", { class: element === r.element ? "hl" : null }, `${ELEMENT_KO[r.element]}${r.source === "skill" ? "(스킬)" : ""}`),
        h("dd", null, r.seasons ? [tierBadge(r.tier, r.lift), ` ${counts.get(r.element)}명 중 ${r.rank}위 · 시즌 ${r.seasons}번`]
          : h("span", { class: "muted" }, "미관측 — 이 약점 시즌을 아직 못 겪음"))]),
      h("dt", null, "수명"), h("dd", null, lifePill(life), life.main, returnTag(app, life.a)),
      life.a ? [h("dt", null, "쓰인 시즌"), h("dd", null, `출시 뒤 ${life.a.seasonsOut}시즌 중 ${life.a.seasonsUsed}번`,
        life.a.firstUsed != null ? h("span", { class: "muted" }, ` · 처음 S${life.a.firstUsed}`) : null)] : null),
    life.a ? h("div", { class: "tip-life" }, h("div", { class: "muted small" }, life.sub), lifeStrip(app, view, u, { width: 240 })) : null,
    h("div", { class: "tip-notes" },
      o?.treasure ? h("span", { class: "pill heart" }, `♥ 애장품(${shortDay(unit.treasure)}) 뒤 시즌만으로`) : null,
      o?.provisional ? h("span", { class: "pill" }, provisionalReason(o, slots, app.state.params)) : null));
}

export function provisionalReason(o, slots, params) {
  const reasons = [];
  const own = (slots || []).filter((s) => s.own);
  const other = (slots || []).filter((s) => !s.own);
  if (own.length && !own.some((s) => s.seasons)) reasons.push("자기 속성 시즌을 아직 못 겪음");
  else if (!other.some((s) => s.seasons)) reasons.push("다른 속성 기록 없음");
  if (o.elementsObserved < params.minElementsObserved) reasons.push(`겪은 보스 약점 ${o.elementsObserved}가지뿐`);
  return `잠정: ${reasons.join(" · ") || "표본이 적음"}`;
}
