// Pieces the three views share: a unit's card, the tier board, the filter row, tooltips.

import { ELEMENTS, assignTier } from "../model.js";
import {
  h, num, pct, int, face, elementIcon, classIcon, burstIcon, nameLines, unitName, withTip, tierBadge, deckSplit,
  segmented, ELEMENT_KO, CLASS_KO, BURSTS, shortDay,
} from "../ui.js";

// ---------------------------------------------------------------------------
// a unit

export function unitCard(app, u, { value, tier, provisional, heart, dim, tip, extra } = {}) {
  const unit = app.model.units[u];
  const [first, second] = nameLines(unit);
  const card = h("a", {
    class: ["card", dim && "dim"], href: app.href("unit", unit.id), dataset: { tier: tier || "D" },
    "aria-label": `${unitName(unit)}${value != null ? ` ${num(value)}` : ""}${tier ? ` ${tier} 티어` : ""}`,
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

export function tierBoard(app, items, { key, card, collapseAt = 36, empty = "없음", note = null }) {
  const cuts = app.state.params.cuts;
  const board = h("div", { class: "board" });
  cuts.forEach(([label], i) => {
    const group = items.filter((it) => it.tier === label);
    const id = `${key}:${label}`;
    const open = app.state.expanded.has(id);
    const shown = open || group.length <= collapseAt + 4 ? group : group.slice(0, collapseAt);
    const cards = h("div", { class: "cards" }, shown.map(card));
    if (!group.length) cards.append(h("span", { class: "row-empty" }, empty));
    if (shown.length < group.length) {
      cards.append(h("button", { type: "button", class: "more", onclick: () => { app.state.expanded.add(id); app.rerender(); } },
        h("b", null, `+${group.length - shown.length}`), "명 더 보기"));
    }
    board.append(h("section", { class: "tier-row", dataset: { tier: label }, "aria-label": `${label} 티어 ${group.length}명` },
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
// the five boss-weakness slots an overall tier is made of

export function slotStrip(slots, cuts, { labels = false } = {}) {
  return h("span", { class: ["slots", labels && "with-labels"] }, slots.map((sl) => {
    const filled = !sl.seasons;
    const tier = assignTier(sl.lift, cuts);
    return h("span", {
      class: ["slot", filled && "filled", sl.own && "own"], dataset: { tier },
      title: `${ELEMENT_KO[sl.element]} 약점 ${filled ? `못 겪어서 채운 값 ${num(sl.lift)}` : `${num(sl.lift)} · 시즌 ${sl.seasons}번`}${sl.own ? " · 자기 속성" : ""}`,
    },
    labels ? elementIcon(sl.element, 12, { title: "" }) : null,
    h("span", null, filled ? `(${num(sl.lift)})` : num(sl.lift)));
  }));
}

export function slotHeader() {
  return h("span", { class: "slots slots-head", "aria-hidden": "true" },
    ELEMENTS.map((e) => h("span", { class: "slot" }, elementIcon(e, 13, { title: ELEMENT_KO[e] }))));
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
  const cuts = app.state.params.cuts;
  const o = view.standing.overallByUnit.get(u);
  const mine = view.standing.elements.filter((r) => r.u === u);
  const slots = view.standing.slots.get(u);
  const counts = new Map();
  for (const r of view.standing.elements) counts.set(r.element, (counts.get(r.element) || 0) + 1);
  const unit = app.model.units[u];
  return h("div", { class: "tip" },
    unitHead(app, u),
    h("dl", { class: "tip-list" },
      o ? [h("dt", null, "종합"), h("dd", null, tierBadge(o.tier, o.overall), ` ${view.standing.overall.length}명 중 ${o.rank}위`,
        o.provisional ? h("span", { class: "muted" }, " · 잠정") : null)] : null,
      mine.map((r) => [h("dt", { class: element === r.element ? "hl" : null }, `${ELEMENT_KO[r.element]}${r.source === "skill" ? "(스킬)" : ""}`),
        h("dd", null, r.seasons ? [tierBadge(r.tier, r.lift), ` ${counts.get(r.element)}명 중 ${r.rank}위 · 시즌 ${r.seasons}번`]
          : h("span", { class: "muted" }, "미관측 — 이 약점 시즌을 아직 못 겪음"))])),
    slots ? h("div", { class: "tip-slots" }, h("div", { class: "muted small" }, "종합을 이루는 보스 약점별 다섯 칸"),
      slotHeader(), slotStrip(slots, cuts)) : null,
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
