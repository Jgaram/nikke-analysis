// Every unit to pick from, the best overall tier first, filling the grid from the top left:
// 티어 변화 · 니케 한 명 before a unit is chosen (a card goes to the unit), and the
// comparison's picker (a card puts the unit in or out of the list).

import { h, hideTip } from "../ui.js";
import { unitCard, filterGroups, standingTip, fold, trendTabs } from "./common.js";
import { timeStrip, whenLabel } from "./when.js";

export function pickView(app) {
  const view = app.viewAt(app.moment());
  return h("div", { class: "view view-pick" },
    trendTabs(app),
    timeStrip(app, { compact: true }),
    unitPicker(app, {
      heading: "니케 고르기",
      sub: `종합 티어 순 · ${whenLabel(app, view.moment)} 기준`,
      enter: (u) => app.go({ unit: u }),
      note: "얼굴을 누르면 그 니케의 티어 변화로.",
    }));
}

// The search, the filters and the grid of every unit out by the chosen day. ``pick(u)``
// (optional) makes each card a toggle: {on, href, onclick}; ``enter(u)`` is what Enter in
// the search does with the first unit shown.
export function unitPicker(app, { heading, sub, enter, pick = null, note = "", fold: foldKey = "pick:bottom" }) {
  const { model, state } = app;
  const cuts = state.params.overallCuts;
  const bottom = cuts.length > 1 ? cuts[cuts.length - 1][0] : null;
  const view = app.viewAt(app.moment());
  // Every unit out by the moment: the standing's order, best first, then the ones with no
  // tier yet (no season played since their release, or since their treasure), newest first.
  const out = new Set();
  model.units.forEach((unit, u) => { if (unit.release != null && unit.release <= view.moment) out.add(u); });
  for (const s of app.population().summary) if (s.start != null && s.start <= view.moment) for (const r of s.rows) out.add(r.u);
  const items = view.standing.overall.map((o) => ({ u: o.u, tier: o.tier, o }));
  const untiered = [...out].filter((u) => !view.standing.overallByUnit.has(u))
    .sort((a, b) => (model.units[b].release ?? 0) - (model.units[a].release ?? 0));
  for (const u of untiered) items.push({ u, tier: null, o: null });

  const card = (it) => unitCard(app, it.u, {
    value: it.o?.overall, tier: it.tier, provisional: it.o?.provisional, heart: it.o?.treasure,
    retired: view.life.get(it.u)?.retired, tip: () => standingTip(app, it.u, view), pick: pick ? pick(it.u) : null,
  });
  const mark = (tier, n) => h("span", { class: "pick-tier", dataset: { tier: tier || "-" }, title: `${tier ? `${tier} 티어` : "티어 없음"} ${n}명` },
    h("b", null, tier || "–"), h("small", null, n));
  const setOpen = (on) => { if (on) state.expanded.add(foldKey); else state.expanded.delete(foldKey); paint(); };

  // The grid alone is redrawn as the search changes, so the search box keeps its focus.
  const grid = h("div", { class: "cards pick-grid" });
  const count = h("span", { class: "pick-count" });
  let first = null;
  function paint() {
    hideTip();
    const q = fold(state.query);
    const shown = items.filter((it) => {
      const unit = model.units[it.u];
      return app.passes(unit, true) && (!q || fold(unit.ko).includes(q) || fold(unit.en).includes(q));
    });
    first = shown.length ? shown[0].u : null;
    // The bottom tier (next to no use) starts folded, as on the tier boards; a search shows it all.
    const open = !!q || state.expanded.has(foldKey);
    const nodes = [];
    for (let i = 0; i < shown.length;) {
      const tier = shown[i].tier;
      let j = i;
      while (j < shown.length && shown[j].tier === tier) j++;
      const group = shown.slice(i, j);
      i = j;
      // a tier's mark wraps to a new line together with its first card
      if (tier === bottom && !open) {
        nodes.push(h("span", { class: "pick-lead" }, mark(tier, group.length), h("button", {
          type: "button", class: "fold", "aria-expanded": "false", onclick: () => setOpen(true),
        }, h("b", null, `${group.length}명`), " 펼치기 · 거의 안 쓰인 니케")));
        continue;
      }
      nodes.push(h("span", { class: "pick-lead" }, mark(tier, group.length), card(group[0])), group.slice(1).map(card));
      if (tier === bottom && !q) {
        nodes.push(h("button", { type: "button", class: "fold open", "aria-expanded": "true", onclick: () => setOpen(false) }, "접기"));
      }
    }
    grid.replaceChildren(...(nodes.length ? nodes.flat() : [h("span", { class: "row-empty" }, "조건에 맞는 니케가 없습니다")]));
    count.textContent = shown.length === items.length ? `${items.length}명` : `${items.length}명 중 ${shown.length}명`;
  }

  const input = h("input", {
    type: "search", class: "picker-input", placeholder: "니케 찾기 (한글·영문)", "aria-label": "니케 찾기",
    autocomplete: "off", spellcheck: false, value: state.query,
    oninput: (e) => { state.query = e.target.value; paint(); },
    onkeydown: (e) => { if (e.key === "Enter" && first != null) { e.preventDefault(); enter(first); } },
  });
  paint();

  // the search and the filters the tier boards have on one line, the unit list's own below
  const { groups, clear } = filterGroups(app, { more: true });
  const filters = (...children) => h("div", { class: "filters", role: "group", "aria-label": "필터" }, children);
  return [
    h("div", { class: "pick-bar" },
      h("div", { class: "picker" }, h("span", { class: "picker-icon", "aria-hidden": "true" }, "⌕"), input),
      filters(groups.slice(0, 2))),
    filters(groups.slice(2), clear),
    h("section", { class: "panel pick-panel", "aria-label": heading || "니케 고르기" },
      h("div", { class: "panel-head" }, heading ? h("h3", null, heading) : null, h("span", { class: "muted small" }, sub, " · ", count)),
      grid,
      h("p", { class: "note" },
        "종합 티어가 높은 니케부터 왼쪽 위에서 채운다. 숫자 = 종합 티어의 값 · ? = 잠정 · ",
        h("span", { class: "heart-text" }, "♥"), " = 애장품을 낀 시즌만으로 매김 · 흑백 얼굴 = 은퇴",
        untiered.length ? " · – = 출시(애장품) 뒤 치른 시즌이 아직 없어 티어가 없음" : "",
        `. ${note}`)),
  ];
}
