// 니케 추이: one unit - where it stands now (or on the chosen day), and season by season.

import { assignTier, unitSeasons, ELEMENTS } from "../model.js";
import {
  h, num, pct, face, elementIcon, classIcon, burstIcon, weaponIcon, makerIcon, ELEMENT_KO, CLASS_KO, WEAPON_SHORT,
  WEAPON_KO, MAKER_KO, day, todayKst, tierBadge, deckSplit, sortableTable, unitName, kst, segmented,
} from "../ui.js";
import { provisionalReason, lifeText, lifeSub, lifeStrip, returnTag, fold } from "./common.js";
import { trajectoryChart } from "../chart.js";

export function unitView(app) {
  const { model, state } = app;
  const pop = app.population();
  const history = app.history();
  const moment = app.moment();
  const u = state.unit;
  const unit = model.units[u];
  const all = unitSeasons(pop, history, u).map(({ season, row, hist }) => ({ season, row, hist }));
  const prof = app.profile(u, moment);
  const own = prof.members.map((m) => m.element);

  const root = h("div", { class: "view view-unit" });
  root.append(picker(app, u));
  root.append(profile(app, u, prof, moment));
  if (!all.length) {
    root.append(h("div", { class: "panel empty" }, "아직 치른 시즌이 없습니다. 출시 뒤 첫 시즌이 열리면 여기에 나옵니다."));
    return root;
  }
  // A weakness chosen keeps the chart and the table to the seasons of that weakness.
  const weak = state.weak;
  const records = weak ? all.filter((r) => r.season.weak === weak) : all;
  const head = h("div", { class: "panel-head" },
    h("h3", null, "시즌별 기여도와 티어 변화"),
    weakSwitch(app, all, own),
    h("span", { class: "muted small" }, "막대에 마우스를 올리거나 눌러 보세요 · 선의 값은 그 시즌이 끝났을 때의 티어"));
  root.append(h("section", { class: "panel chart-panel" }, head,
    records.length ? trajectoryChart(app, u, records, { own, treasureAt: unit.treasure })
      : h("p", { class: "empty-note muted" }, `출시 뒤 ${ELEMENT_KO[weak]} 약점 시즌이 아직 없습니다.`)));
  if (records.length) root.append(seasonTable(app, u, records));
  return root;
}

// 전체, or one boss weakness: how many of the unit's seasons each has, its own element(s) marked.
function weakSwitch(app, records, own) {
  const count = (e) => records.filter((r) => r.season.weak === e).length;
  return segmented([
    { value: null, label: "전체", title: `전체 시즌 ${records.length}개` },
    ...ELEMENTS.filter((e) => count(e)).map((e) => ({
      value: e, icon: elementIcon(e, 16, { title: "" }), label: own.includes(e) ? "▶" : null,
      title: `${ELEMENT_KO[e]} 약점 시즌만 (${count(e)}개)${own.includes(e) ? " · 자기 속성" : ""}`,
    })),
  ], app.state.weak, (v) => app.go({ weak: v }, { replace: true }), { class: "weak-seg", label: "약점 속성으로 거르기" });
}

// ---------------------------------------------------------------------------

function picker(app, current) {
  const { model } = app;
  const pop = app.population();
  const ranked = new Set();
  for (const s of pop.summary) for (const r of s.rows) ranked.add(r.u);
  const now = app.viewAt(Date.now());
  const order = new Map(now.standing.overall.map((o, i) => [o.u, i]));
  const candidates = [...ranked].sort((a, b) => (order.get(a) ?? 1e9) - (order.get(b) ?? 1e9));

  const list = h("ul", { class: "picker-list", id: "unit-options", role: "listbox", hidden: true });
  const input = h("input", {
    type: "search", class: "picker-input", placeholder: `${unitName(model.units[current])} · 다른 니케 찾기 (한글·영문)`,
    "aria-label": "니케 찾기", autocomplete: "off", spellcheck: false, role: "combobox", "aria-expanded": "false",
    "aria-controls": "unit-options", "aria-autocomplete": "list",
  });
  let active = 0;
  let shown = [];
  const choose = (u) => { list.hidden = true; app.go({ unit: u }); };
  const paint = () => {
    list.replaceChildren(...shown.map((u, i) => {
      const unit = model.units[u];
      const o = now.standing.overallByUnit.get(u);
      return h("li", {
        role: "option", id: `unit-opt-${i}`, class: ["picker-opt", i === active && "on"], "aria-selected": String(i === active),
        onpointerdown: (e) => { e.preventDefault(); choose(u); },
      }, face(unit, 32), h("span", { class: "picker-name" }, unitName(unit), h("span", { class: "muted" }, unit.en)),
      elementIcon(unit.element, 15), o ? tierBadge(o.tier, null) : null);
    }));
    list.hidden = !shown.length;
    input.setAttribute("aria-expanded", String(!list.hidden));
    input.setAttribute("aria-activedescendant", shown.length ? `unit-opt-${active}` : "");
  };
  const search = () => {
    const q = fold(input.value.trim());
    active = 0;
    if (!q) { shown = candidates.slice(0, 10); paint(); return; }
    const scored = [];
    for (const u of candidates) {
      const unit = model.units[u];
      const ko = fold(unit.ko), en = fold(unit.en);
      const at = Math.min(...[ko.indexOf(q), en.indexOf(q)].map((i) => (i < 0 ? 1e9 : i)));
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
      choose(shown[active]);
    } else if (e.key === "Escape") {
      list.hidden = true;
    }
  });
  return h("div", { class: "unit-top" },
    h("a", { class: "btn ghost back", href: app.href("unit") },
      h("span", { class: "back-arrow", "aria-hidden": "true" }, "‹"), h("span", { class: "back-k" }, "니케 "), "목록"),
    h("div", { class: "picker" }, h("span", { class: "picker-icon", "aria-hidden": "true" }, "⌕"), input, list));
}

// ---------------------------------------------------------------------------

function tile(label, tier, value, sub, extra = {}) {
  return h("div", { class: ["tile", extra.class], dataset: { tier: tier || "none" } },
    h("div", { class: "tile-label" }, label),
    h("div", { class: "tile-value" },
      tier ? h("span", { class: "tile-tier" }, tier) : h("span", { class: "tile-tier none" }, "–"),
      value != null && !Number.isNaN(value) ? h("span", { class: "tile-num" }, num(value)) : null,
      extra.mark ? h("span", { class: "tile-mark" }, extra.mark) : null),
    h("div", { class: "tile-sub" }, sub));
}

function slotChart(app, slots, overallMode) {
  const cuts = app.state.params.cuts;
  const top = Math.max(cuts[0][1] + 0.2, ...slots.map((s) => s.lift));
  return h("div", { class: "tile slots-tile" },
    h("div", { class: "tile-label" }, "종합을 이루는 다섯 칸", h("span", { class: "muted" }, " · 보스 약점별")),
    h("div", { class: "mini-bars", role: "img", "aria-label": slots.map((s) => `${ELEMENT_KO[s.element]} ${num(s.lift)}${s.seasons ? "" : "(채운 값)"}`).join(", ") },
      slots.map((sl) => h("div", { class: ["mb", !sl.seasons && "filled", sl.own && "own"], title: sl.seasons
        ? `${ELEMENT_KO[sl.element]} 약점 시즌 ${sl.seasons}번의 기여도 가중 평균 ${num(sl.lift)}`
        : `${ELEMENT_KO[sl.element]} 약점 시즌을 아직 못 겪어 채운 값 ${num(sl.lift)}` },
      h("span", { class: "mb-val" }, sl.seasons ? num(sl.lift) : `(${num(sl.lift)})`),
      h("span", { class: "mb-track" }, h("span", { class: "mb-fill", dataset: { tier: assignTier(sl.lift, cuts) },
        style: { height: `${Math.max(2, (sl.lift / top) * 100)}%` } })),
      h("span", { class: "mb-el" }, elementIcon(sl.element, 15), sl.own ? h("b", { class: "own-mark" }, "▶") : null)))),
    h("div", { class: "tile-sub" }, overallMode === "mean" ? "종합 = 다섯 칸의 평균 · 괄호 = 못 겪어서 채운 값 · ▶ = 자기 속성"
      : overallMode === "frequency" ? "종합 = 최근 자주 나온 약점일수록 크게 친 평균 · ▶ = 자기 속성"
        : "종합 = 겪어 본 칸 중 가장 큰 값 · ▶ = 자기 속성"));
}

// Since when top rankers have used the unit, and whether they still do.
function lifeTile(app, u, view) {
  const t = lifeText(app, view, u);
  if (!t.a) return null;
  const used = t.a.lastUsed != null;
  return h("div", { class: "tile tile-life", dataset: { tier: "none", state: t.state } },
    h("div", { class: "tile-label" }, "수명", returnTag(app, t.a)),
    h("div", { class: "tile-value" }, h("span", { class: ["tile-state", t.state] }, t.label),
      used ? h("span", { class: "tile-life-main" }, t.main) : null),
    lifeStrip(app, view, u, { width: 230 }),
    h("div", { class: "tile-sub" }, used ? `${lifeSub(t)} · 출시 뒤 ${t.a.seasonsOut}시즌 중 ${t.a.seasonsUsed}번 쓰임` : t.sub));
}

function profile(app, u, prof, moment) {
  const { model, state } = app;
  const unit = model.units[u];
  const t = kst(moment);
  const now = !state.date || state.date === todayKst();
  const o = prof.overall;
  const elementTiles = prof.elements.map((r) => tile(
    h("span", null, "속성 티어 · ", elementIcon(r.element, 14), ELEMENT_KO[r.element], r.source === "skill" ? h("span", { class: "muted" }, " (스킬)") : null),
    r.seasons ? r.tier : null, r.seasons ? r.lift : null,
    r.seasons ? `${ELEMENT_KO[r.element]} 니케 ${r.units}명 중 ${r.rank}위 · 약점 시즌 ${r.seasons}번`
      : `미관측 — ${prof.treasured ? "애장품" : "출시"} 뒤 ${ELEMENT_KO[r.element]} 약점 시즌이 아직 없음`,
    { class: "tile-element" }));
  const tiles = o ? [
    tile("종합 티어", o.tier, o.overall, `${prof.units}명 중 ${o.rank}위${o.provisional ? ` · ${provisionalReason(o, prof.slots, state.params)}` : ""}`,
      { mark: o.provisional ? "*" : null, class: "tile-overall" }),
    ...elementTiles,
    lifeTile(app, u, prof.view),
    prof.slots ? slotChart(app, prof.slots, state.params.overall) : null,
  ] : [h("div", { class: "tile tile-none" }, prof.treasured
    ? "애장품을 낀 시즌 기록이 아직 없어 티어가 없습니다 (애장품 전 기록은 아래 차트·표)."
    : "이 날짜까지 치른 시즌이 없어 티어가 없습니다."), lifeTile(app, u, prof.view)];
  const added = unit.extra.map((e) => ELEMENT_KO[e]);
  const byTreasure = unit.treasureElements.map((e) => ELEMENT_KO[e]);
  return h("section", { class: "profile" },
    h("div", { class: "pf-face" }, face(unit, 104, { loading: "eager" }), elementIcon(unit.element, 26, { class: "pf-el" })),
    h("div", { class: "pf-main" },
      h("div", { class: "pf-when muted small" }, `${t.y}-${t.m}-${t.d}${now ? " 지금" : " 정오"} 기준`,
        prof.treasured ? " · 애장품을 낀 시즌만으로" : "",
        prof.view.live.length ? ` · 진행 중 시즌 ${prof.view.live.join("·")} 잠정 반영` : "",
        !now ? h("a", { class: "link", href: app.href("unit", unit.id, { d: "" }), onclick: (e) => { e.preventDefault(); app.go({ date: null }, { replace: true }); } }, " 오늘로") : null),
      h("h2", { class: "pf-name" }, unitName(unit), unit.en && unit.ko ? h("span", { class: "pf-en" }, unit.en) : null),
      h("div", { class: "pf-attrs" },
        h("span", { class: "attr" }, elementIcon(unit.element, 16), ELEMENT_KO[unit.element] || "?",
          added.length ? h("span", { class: "muted" }, ` + 스킬 ${added.join("·")}`) : null,
          byTreasure.length ? h("span", { class: "muted" }, ` + 애장품 뒤 ${byTreasure.join("·")}`) : null),
        h("span", { class: "attr" }, classIcon(unit.class, 15), CLASS_KO[unit.class] || unit.class),
        h("span", { class: "attr" }, burstIcon(unit.burst), `버스트 ${unit.burst}`),
        unit.weapon ? h("span", { class: "attr", title: WEAPON_KO[unit.weapon] || unit.weapon }, weaponIcon(unit.weapon, 15),
          WEAPON_SHORT[unit.weapon] || unit.weapon) : null,
        unit.manufacturer ? h("span", { class: "attr" }, makerIcon(unit.manufacturer, 15), MAKER_KO[unit.manufacturer] || unit.manufacturer) : null,
        h("span", { class: "attr" }, h("span", { class: "fact-k" }, "출시"), unit.releaseDate || "?"),
        unit.treasure != null ? h("span", { class: "attr heart-attr" }, h("span", { class: "fact-k" }, "애장품"), `♥ ${day(unit.treasure)}`) : null),
      h("div", { class: "tiles" }, tiles)));
}

// ---------------------------------------------------------------------------

function seasonTable(app, u, records) {
  const { state, model } = app;
  const unit = model.units[u];
  const cuts = state.params.cuts;
  const sort = state.sort.unit || { key: "season", dir: "desc" };
  const firstTreasure = records.find((r) => r.row.treasure)?.season.season;
  const columns = [
    { key: "season", label: "시즌", num: true, head: true, sort: (r) => r.season.season, cell: (r) => h("a", { href: app.href("season", r.season.season), class: "link" }, `S${r.season.season}`) },
    { key: "start", label: "시작", sort: (r) => r.season.start, cell: (r) => h("span", { class: "muted" }, day(r.season.start)) },
    { key: "boss", label: "보스 · 약점", sort: (r) => r.season.weak, cell: (r) => h("span", { class: "boss-cell" },
      h("span", { class: "boss-name" }, r.season.info.bossKo || r.season.info.bossEn || "?"),
      elementIcon(r.season.weak, 15), r.row.elementMatch ? h("b", { class: "own-mark", title: "자기 속성 약점 시즌" }, "▶") : null,
      !r.season.final ? h("span", { class: "pill live" }, "진행 중") : null,
      r.season.season === firstTreasure ? h("span", { class: "pill heart", title: `애장품 ${day(unit.treasure)}` }, "♥ 애장품부터") : null) },
    { key: "usage", label: "사용", num: true, sort: (r) => r.row.usageRate, cell: (r) => (r.row.rankers ? pct(r.row.usageRate) : h("span", { class: "muted" }, "0%")) },
    { key: "split", label: "덱 분포", sort: (r) => (r.row.rankers ? -r.row.avgDeck : null), cell: (r) => deckSplit(r.row.inDeck, r.row.rankers, 96) },
    { key: "lift", label: "기여도", sort: (r) => r.row.lift, cell: (r) => tierBadge(assignTier(r.row.lift, cuts), r.row.lift) },
    { key: "element", label: "속성 티어", title: "그 시즌이 끝났을 때 (자기 속성 약점 시즌만)", sort: (r) => (r.hist?.counted ? r.hist.elementLift : null),
      cell: (r) => (r.hist?.counted && !Number.isNaN(r.hist.elementLift) ? tierBadge(r.hist.elementTier, r.hist.elementLift) : h("span", { class: "muted" }, "–")) },
    { key: "overall", label: "종합 티어", title: "그 시즌이 끝났을 때", sort: (r) => r.hist?.overall,
      cell: (r) => (r.hist && !Number.isNaN(r.hist.overall) ? h("span", null, tierBadge(r.hist.overallTier, r.hist.overall), r.hist.provisional ? h("sup", { class: "muted" }, "*") : null) : "–") },
  ];
  return h("section", { class: "panel table-panel" },
    h("div", { class: "panel-head" }, h("h3", null, "시즌별 기록"), h("span", { class: "muted small" }, `${records.length}시즌`)),
    sortableTable(columns, records, {
      sortKey: sort.key, sortDir: sort.dir, caption: `${unitName(unit)} 시즌별 기록`,
      onSort: (key, dir) => { state.sort.unit = { key, dir }; app.rerender(); },
      rowAttrs: (r) => ({ class: [r.row.elementMatch && "own-row", !r.season.final && "live-row"].filter(Boolean).join(" ") || null }),
    }),
    h("p", { class: "note" }, "▶ = 보스 약점이 이 니케의 속성인 시즌 · 사용 = 그 니케를 쓴 랭커 비율 · 덱 분포 = 쓴 사람 중 몇 번째로 센 덱에 넣었나 · "
      + "속성·종합 티어 = 그 시즌이 끝났을 때 (애장품 전과 뒤는 따로 매김) · * = 잠정"));
}

