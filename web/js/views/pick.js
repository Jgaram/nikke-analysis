// 티어 변화 · 니케 한 명, before a unit is chosen: every unit to pick one from, the best overall
// tier first, filling the grid from the top left.

import { h, hideTip, kst, todayKst } from "../ui.js";
import { unitCard, filterGroups, standingTip, fold, trendTabs } from "./common.js";
import { dateBar } from "./date.js";

const FOLD = "pick:bottom";

export function pickView(app) {
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
    retired: view.life.get(it.u)?.retired, tip: () => standingTip(app, it.u, view),
  });
  const mark = (tier, n) => h("span", { class: "pick-tier", dataset: { tier: tier || "-" }, title: `${tier ? `${tier} 티어` : "티어 없음"} ${n}명` },
    h("b", null, tier || "–"), h("small", null, n));
  const setOpen = (on) => { if (on) state.expanded.add(FOLD); else state.expanded.delete(FOLD); paint(); };

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
    const open = !!q || state.expanded.has(FOLD);
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
    onkeydown: (e) => { if (e.key === "Enter" && first != null) { e.preventDefault(); app.go({ unit: first }); } },
  });
  paint();

  // the search and the filters the tier boards have on one line, the unit list's own below
  const { groups, clear } = filterGroups(app, { more: true });
  const filters = (...children) => h("div", { class: "filters", role: "group", "aria-label": "필터" }, children);
  const t = kst(view.moment);
  const now = !state.date || state.date === todayKst();
  return h("div", { class: "view view-pick" },
    trendTabs(app),
    dateBar(app),
    h("div", { class: "pick-bar" },
      h("div", { class: "picker" }, h("span", { class: "picker-icon", "aria-hidden": "true" }, "⌕"), input),
      filters(groups.slice(0, 2))),
    filters(groups.slice(2), clear),
    h("section", { class: "panel pick-panel", "aria-label": "니케 목록" },
      h("div", { class: "panel-head" }, h("h3", null, "니케 고르기"),
        h("span", { class: "muted small" }, `종합 티어 순 · ${t.y}-${t.m}-${t.d}${now ? " 지금" : " 정오"} 기준 · `, count)),
      grid,
      h("p", { class: "note" },
        "종합 티어가 높은 니케부터 왼쪽 위에서 채운다. 숫자 = 종합 티어의 값 · * = 잠정 · ",
        h("span", { class: "heart-text" }, "♥"), " = 애장품을 낀 시즌만으로 매김 · 흑백 얼굴 = 은퇴",
        untiered.length ? " · – = 출시(애장품) 뒤 치른 시즌이 아직 없어 티어가 없음" : "",
        ". 얼굴을 누르면 그 니케의 티어 변화로.")));
}
