// Pieces the views share: a unit's card, the tier board, the filter row, the switches that
// lead between views, a unit search, tooltips.

import { ELEMENTS, DAY_MS, assignTier, unitElements, fielded } from "../model.js";
import {
  h, num, pct, int, face, elementIcon, classIcon, burstIcon, weaponIcon, makerIcon, nameLines, unitName, withTip, tierBadge,
  deckSplit, segmented, ELEMENT_KO, CLASS_KO, BURSTS, WEAPON_SHORT, WEAPON_KO, MAKER_KO, shortDay,
} from "../ui.js";

// ---------------------------------------------------------------------------
// a unit

// A name as the unit searches compare it: "라피 : 레드 후드" -> "라피레드후드".
export const fold = (text) => (text || "").toLowerCase().replace(/[\s:·\-_.()]/g, "");

export function unitCard(app, u, { value, tier, provisional, heart, dim, retired, tip, extra } = {}) {
  const unit = app.model.units[u];
  const [first, second] = nameLines(unit);
  const card = h("a", {
    class: ["card", dim && "dim", retired && "retired"], href: app.unitHref(unit.id), dataset: { tier: tier || "D" },
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
  return h("a", { class: "unit-inline", href: app.unitHref(unit.id) },
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
// ``cuts`` are the ones the items were tiered by: the season/element cuts unless given.
export function tierBoard(app, items, { key, card, collapseAt = 36, empty = "없음", note = null, cuts = null }) {
  cuts = cuts || app.state.params.cuts;
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

// The values of ``key`` the roster has, those ``order`` knows first in its order.
function present(units, key, order) {
  const have = new Set(units.map((u) => u[key]).filter(Boolean));
  return [...order.filter((v) => have.delete(v)), ...[...have].sort()];
}

// The tier boards filter by element and burst; the unit list (``more``) also by role,
// weapon and maker. Each group keeps its choice while the tabs change. The groups come
// in that order, with a button that clears them all while any is on.
export function filterGroups(app, { more = false } = {}) {
  const f = app.state.filters;
  const units = app.model.units;
  const chip = (set, value, content, title) => h("button", {
    type: "button", class: "fchip", "aria-pressed": String(set.has(value)), title,
    onclick: () => { if (set.has(value)) set.delete(value); else set.add(value); app.rerender(); },
  }, content);
  const groups = [
    ["elements", "속성", ELEMENTS.map((e) => [e, elementIcon(e, 17, { title: "" }), ELEMENT_KO[e]])],
    ["bursts", "버스트", BURSTS.map((b) => [b, burstIcon(b), `버스트 ${b}`])],
  ];
  if (more) {
    groups.push(
      ["classes", "역할군", present(units, "class", Object.keys(CLASS_KO))
        .map((c) => [c, [classIcon(c, 15), h("span", { class: "fl" }, CLASS_KO[c] || c)], CLASS_KO[c] || c])],
      ["weapons", "무기군", present(units, "weapon", Object.keys(WEAPON_SHORT))
        .map((w) => [w, [weaponIcon(w, 15), h("span", null, WEAPON_SHORT[w] || w)], WEAPON_KO[w] || w])],
      ["makers", "기업", present(units, "manufacturer", Object.keys(MAKER_KO))
        .map((m) => [m, [makerIcon(m, 15), h("span", { class: "fl" }, MAKER_KO[m] || m)], MAKER_KO[m] || m])],
    );
  }
  return {
    groups: groups.map(([key, label, chips]) => h("div", { class: "fgroup", role: "group", "aria-label": label },
      chips.map(([value, content, title]) => chip(f[key], value, content, title)))),
    clear: groups.some(([key]) => f[key].size) ? h("button", {
      type: "button", class: "fclear",
      onclick: () => { for (const [key] of groups) f[key].clear(); app.rerender(); },
    }, "필터 해제") : null,
  };
}

export function filterRow(app) {
  const { groups, clear } = filterGroups(app);
  return h("div", { class: "filters", role: "group", "aria-label": "필터" }, groups, clear);
}

// Tiers or table.
export function modeSwitch(app) {
  return segmented([
    { value: "tiers", label: "티어표" }, { value: "table", label: "표" },
  ], app.state.mode, (v) => app.go({ mode: v }, { replace: true }), { class: "mode", label: "보기" });
}

// 티어표's kinds: the overall tier and each element's on a day, or one season's own.
export function kindTabs(app) {
  return h("nav", { class: "kindbar", "aria-label": "티어 종류" }, segmented([
    { value: "overall", label: "종합 티어", title: "고른 날 기준 종합 티어" },
    ...ELEMENTS.map((e) => ({ value: e, label: ELEMENT_KO[e], icon: elementIcon(e, 16, { title: "" }), title: `고른 날 기준 ${ELEMENT_KO[e]} 속성 티어` })),
    { value: "season", label: "시즌 티어", title: "한 시즌의 기여도로 매긴 티어" },
  ], app.state.view, (v) => app.go({ view: v, weak: null }, { replace: true }), { class: "viewtabs", label: "티어 종류" }));
}

// 티어 변화's views: one unit, units side by side, the seasons of one weakness.
export function trendTabs(app) {
  const n = app.state.compare.filter((u) => u != null).length;
  return h("nav", { class: "kindbar", "aria-label": "변화 보기" }, segmented([
    { value: "unit", label: "니케 한 명", title: "한 니케의 시즌별 기여도·티어·범용도" },
    { value: "compare", label: n ? `니케 비교 ${n}` : "니케 비교", title: "여러 니케의 종합 티어를 한 그래프에" },
    { value: "weak", label: "약점별 시즌", title: "한 보스 약점의 시즌들을 나란히" },
  ], app.state.trend, (v) => app.go({ trend: v, weak: v === "weak" ? app.state.weak : null }), { class: "viewtabs", label: "변화 보기" }));
}

// A search box over the units that have played: typing lists the best matches (Korean or
// English), the arrows move, Enter or a press picks - ``choose(u)``. Empty, it lists
// ``order``'s first ten. ``skip`` leaves units out of the list.
export function unitSearch(app, { placeholder, choose, skip = new Set(), order = null }) {
  const { model } = app;
  const pop = app.population();
  const now = app.viewAt(Date.now());
  const ranked = new Set();
  for (const s of pop.summary) for (const r of s.rows) ranked.add(r.u);
  const rank = new Map(now.standing.overall.map((o, i) => [o.u, i]));
  const candidates = (order || [...ranked].sort((a, b) => (rank.get(a) ?? 1e9) - (rank.get(b) ?? 1e9)))
    .filter((u) => !skip.has(u));
  const id = `unit-options-${Math.random().toString(36).slice(2, 8)}`;
  const list = h("ul", { class: "picker-list", id, role: "listbox", hidden: true });
  const input = h("input", {
    type: "search", class: "picker-input", placeholder, "aria-label": "니케 찾기", autocomplete: "off", spellcheck: false,
    role: "combobox", "aria-expanded": "false", "aria-controls": id, "aria-autocomplete": "list",
  });
  let active = 0;
  let shown = [];
  const pick = (u) => { list.hidden = true; choose(u); };
  const paint = () => {
    list.replaceChildren(...shown.map((u, i) => {
      const unit = model.units[u];
      const o = now.standing.overallByUnit.get(u);
      return h("li", {
        role: "option", id: `${id}-${i}`, class: ["picker-opt", i === active && "on"], "aria-selected": String(i === active),
        onpointerdown: (e) => { e.preventDefault(); pick(u); },
      }, face(unit, 32), h("span", { class: "picker-name" }, unitName(unit), h("span", { class: "muted" }, unit.en)),
      elementIcon(unit.element, 15), o ? tierBadge(o.tier, null) : null);
    }));
    list.hidden = !shown.length;
    input.setAttribute("aria-expanded", String(!list.hidden));
    input.setAttribute("aria-activedescendant", shown.length ? `${id}-${active}` : "");
  };
  const search = () => {
    const q = fold(input.value.trim());
    active = 0;
    if (!q) { shown = candidates.slice(0, 10); paint(); return; }
    const scored = [];
    for (const u of candidates) {
      const unit = model.units[u];
      const at = Math.min(...[fold(unit.ko).indexOf(q), fold(unit.en).indexOf(q)].map((i) => (i < 0 ? 1e9 : i)));
      if (at < 1e9) scored.push([at, u]);
    }
    scored.sort((a, b) => a[0] - b[0]);
    shown = scored.slice(0, 12).map(([, u]) => u);
    paint();
  };
  input.addEventListener("input", search);
  input.addEventListener("focus", search);
  input.addEventListener("blur", () => { setTimeout(() => { list.hidden = true; input.setAttribute("aria-expanded", "false"); }, 120); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!shown.length) return;
      active = (active + (e.key === "ArrowDown" ? 1 : shown.length - 1)) % shown.length;
      paint();
    } else if (e.key === "Enter" && shown.length) {
      e.preventDefault();
      pick(shown[active]);
    } else if (e.key === "Escape") {
      list.hidden = true;
    }
  });
  return h("div", { class: "picker" }, h("span", { class: "picker-icon", "aria-hidden": "true" }, "⌕"), input, list);
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

// What retired means, with the parameters in force.
export function retiredText(params) {
  const { minTier, retireAfterDays: days, retireAfterOwnSeasons: own } = params;
  const since = days > 0 ? `마지막으로 쓰인 시즌이 끝나고 ${duration(days)} 넘게` : "마지막으로 쓰인 뒤";
  const unused = `시즌 티어 ${minTier} 이상인 시즌이 없음`;
  if (!own) return `${since} ${unused}`;
  const seasons = `자기 속성 약점 시즌${own > 1 ? ` ${own}번` : ""}`;
  return `${since}${days > 0 ? ", 그 사이" : ""} 온 ${seasons}까지 ${unused} — 자기 속성 시즌이 아직 안 왔으면 현역`;
}

// What the view says of unit ``u``'s lifespan, in words: its state, two lines, and ``why``
// - the seasons of its own element behind a retirement, or a long idle unit still in use.
export function lifeText(app, view, u) {
  const a = view.life.get(u);
  const { minTier, retireAfterDays, retireAfterOwnSeasons } = app.state.params;
  if (!a || a.lastUsed == null) {
    return { a, state: "never", label: "안 쓰임", main: "쓰인 시즌 없음", sub: `시즌 티어 ${minTier} 이상인 시즌이 없음`,
      length: null };
  }
  const counted = view.standing.counted;
  const latest = counted.length ? counted[counted.length - 1].season : null;
  // its elements as the seasons it sat out were weighed: 작열, or 작열·철갑
  const unit = app.model.units[u];
  const own = unitElements(unit, unit.treasure != null && unit.treasure <= view.moment)
    .map((m) => ELEMENT_KO[m.element]).join("·");
  if (a.retired) {
    const length = a.lastEnd - a.runStart;
    return {
      a, state: "retired", label: "은퇴", length,
      main: a.runFrom === a.lastUsed ? `S${a.lastUsed} 한 시즌` : `S${a.runFrom}–S${a.lastUsed} · ${duration(length / DAY_MS)}`,
      sub: `S${a.lastUsed} 뒤 ${duration(a.idleDays)}째 안 쓰임`,
      why: a.missedOwn ? `${own} 약점 시즌 ${a.missedOwn}번 놓침` : null,
    };
  }
  const length = view.moment - a.runStart;
  const recent = a.lastUsed === latest;
  // past the days, in use only because its element has not come round (often enough) since
  const waiting = !recent && retireAfterOwnSeasons > 0 && a.idleDays >= retireAfterDays;
  return {
    a, state: "active", label: "현역", length, recent,
    main: `S${a.runFrom}부터 · ${duration(length / DAY_MS)}째`,
    sub: recent ? "최근 시즌까지 쓰임" : `마지막 S${a.lastUsed} · ${duration(a.idleDays)} 전`,
    why: !waiting ? null : a.missedOwn ? `${own} 약점 시즌 ${a.missedOwn}번 놓침(은퇴는 ${retireAfterOwnSeasons}번부터)`
      : `그 뒤 ${own} 약점 시즌 아직 없음`,
  };
}

// The two lines under the state as one.
export const lifeSub = (t) => [t.sub, t.why].filter(Boolean).join(" · ");

// ---------------------------------------------------------------------------
// a unit's career: how general it is, and which way it is going

export const GENERALITY_KO = { specialist: "특화", element_first: "속성 우선", generalist: "범용" };
export const PATH_KO = {
  generalist: "범용", element_only: "속성 전용", left_others: "다른 속성에서 빠짐", specialist: "특화",
  retired_generalist: "범용 → 은퇴", retired_element_only: "범용 → 속성 전용 → 은퇴", retired_specialist: "특화 → 은퇴",
  unused: "안 쓰임",
};

// What the view says of unit ``u``'s path, in words (tierlist.py _career_lines says the same).
export function careerText(app, view, u) {
  const c = view.careers.get(u);
  if (!c) return null;
  const { generalistSeasons: gen, leftAfter: left } = app.state.params;
  const last = c.lastOther != null ? `S${c.lastOther}` : null;
  const detail = {
    generalist: `다른 속성 시즌 ${c.otherUsed}번 쓰임 · 마지막 ${last}`,
    element_only: `다른 속성은 ${last} 뒤 ${c.otherSince}시즌 내리 안 쓰임, 자기 속성 시즌엔 ${c.ownAfter}번 쓰임`,
    left_others: `다른 속성은 ${last} 뒤 ${c.otherSince}시즌 내리 안 쓰임, 그 뒤 자기 속성 시즌엔 아직 안 쓰임`,
    specialist: `다른 속성 시즌엔 ${c.otherUsed}번 쓰임 (범용은 ${gen}번부터)`,
    retired_generalist: `다른 속성 시즌 ${c.otherUsed}번 쓰이다 ${last} 뒤 자기 속성 시즌에서도 안 쓰이고 은퇴`,
    retired_element_only: `${last} 뒤 다른 속성에서 빠지고 자기 속성 시즌 ${c.ownAfter}번 더 쓰이다 은퇴`,
    retired_specialist: `다른 속성 시즌엔 ${c.otherUsed}번 쓰이고 은퇴`,
    unused: "쓰인 시즌 없음",
  }[c.path];
  return { c, label: PATH_KO[c.path], detail,
    rule: `범용 = 다른 속성 시즌 ${gen}번 이상 쓰임 · 빠짐 = 최근 다른 속성 시즌 ${left}번 내리 안 쓰임` };
}

export function lifePill(text) {
  return h("span", { class: ["life-pill", text.state] }, text.label);
}

export function returnTag(app, a) {
  if (!a || !a.returns) return null;
  return h("span", {
    class: "tag", title: `S${a.firstUsed}부터 쓰이다 은퇴한 적이 ${a.returns}번 · 이번에는 S${a.runFrom}부터 다시 쓰임`,
  }, a.returns > 1 ? `복귀 ${a.returns}번` : "복귀");
}

// One cell per season the view counts: blank before the unit was out, faint when out
// and unused (a season tier under the one that counts), filled when used - in the colour
// of its season tier there.
export function lifeStrip(app, view, u, { width = 150 } = {}) {
  const pop = app.population();
  const { params } = app.state;
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
    else if (!fielded(r, params)) strip.append(h("i", { class: "idle" }));
    else strip.append(h("i", { class: "used", dataset: { tier: assignTier(r.lift, params.cuts) } }));
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
  const { minTier } = app.state.params;
  return [
    { key: "strip", label: lifeHeader(view), class: "life-col", firstDir: "asc",
      title: `시즌 하나가 칸 하나. 칠한 칸 = 시즌 티어 ${minTier} 이상인 시즌(색 = 그 시즌 티어), `
        + "옅은 칸 = 나와 있었지만 거의 안 쓴 시즌. 정렬하면 처음 쓰인 시즌 순",
      sort: (row) => of(row).a?.firstUsed, cell: (row) => lifeStrip(app, view, row.u) },
    { key: "state", label: "상태", firstDir: "asc",
      title: `은퇴 = ${retiredText(app.state.params)}. 정렬하면 최근에 쓰인 순`,
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
          t.recent ? null : h("span", { class: "life-sub" }, t.sub),
          t.why ? h("span", { class: "life-sub" }, t.why) : null);
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
        h("span", { class: "muted" }, ` 1덱 ${pct(row.inDeck[0] / row.rankers)} · 평균 ${num(row.avgDeck)}덱`))] : null),
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
    life.a ? h("div", { class: "tip-life" }, h("div", { class: "muted small" }, lifeSub(life)), lifeStrip(app, view, u, { width: 240 })) : null,
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
