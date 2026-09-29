// The page: state in the URL, the computation cached per parameter set, two tabs -
// 티어표 (where every unit stands: on a day, or in one season) and 변화 (how it moved:
// one unit, units side by side, the seasons of one weakness).

import * as M from "./model.js";
import { h, initTip, hideTip, day, noonKst, todayKst, unitName, ELEMENT_KO } from "./ui.js";
import { buildParams, encodeParams, decodeParams, changedParams, renderParamsFoot } from "./params.js";
import { seasonView } from "./views/season.js";
import { dateView } from "./views/date.js";
import { unitView } from "./views/unit.js";
import { pickView } from "./views/pick.js";
import { compareView, weakView, COMPARE_MAX } from "./views/trend.js";

const TABS = ["tier", "trend"];
const TRENDS = ["unit", "compare", "weak"];
const VIEWS = {
  tier: (app) => (app.state.view === "season" ? seasonView(app) : dateView(app)),
  trend: (app) => ({
    unit: () => (app.state.unit == null ? pickView(app) : unitView(app)),
    compare: () => compareView(app),
    weak: () => weakView(app),
  })[app.state.trend](),
};

const state = {
  tab: "tier",
  view: "overall", // 티어표: overall, an element, or season
  season: null, // 티어표 · season: the season; null = the one of the chosen day
  weak: null, // the season strip's weakness, the unit chart's, or the weakness compared
  date: null, // "YYYY-MM-DD"; null = now - one day for every view
  mode: "tiers", // 티어표: tiers | table
  trend: "unit", // 변화: unit (the list, or one unit) | compare | weak
  unit: null, // unit index; null on 변화 · unit = the list to pick one from
  compare: [], // the units compared, by colour slot (a removed one leaves its slot empty)
  query: "", // the unit list's search
  params: null,
  filters: { elements: new Set(), bursts: new Set(), classes: new Set(), weapons: new Set(), makers: new Set() },
  showUnused: false,
  expanded: new Set(),
  sort: {},
};

const app = { state, model: null, decks: null, defaults: null };
const cache = { pop: null, popKey: null, hist: null, histKey: null, views: new Map() };

// ---------------------------------------------------------------------------
// the computation, cached

app.population = () => {
  const key = M.populationKey(state.params);
  if (cache.popKey !== key) {
    cache.pop = M.computeTables(app.model, app.decks, state.params);
    cache.popKey = key;
    cache.hist = null;
    cache.histKey = null;
    cache.views.clear();
  }
  return cache.pop;
};

app.history = () => {
  const pop = app.population();
  const key = M.tierKey(state.params);
  if (cache.histKey !== key) {
    cache.hist = M.tierHistory(app.model, pop, state.params);
    cache.histKey = key;
  }
  return cache.hist;
};

app.viewAt = (moment) => {
  const pop = app.population();
  const key = `${M.tierKey(state.params)}|${M.lifeKey(state.params)}|${moment}`;
  let view = cache.views.get(key);
  if (!view) {
    view = M.viewAt(app.model, pop, moment, state.params);
    if (cache.views.size > 24) cache.views.clear();
    cache.views.set(key, view);
  }
  return view;
};

app.profile = (u, moment) => M.unitProfile(app.model, app.population(), moment, state.params, u);

// The moment the date tab (and a unit's standing) is read at: now, or noon KST of the chosen day.
app.moment = () => (state.date && state.date !== todayKst() ? noonKst(state.date) : Date.now());

app.latestSeason = () => {
  const ranked = app.population().summary;
  return ranked.length ? ranked[ranked.length - 1].season : app.model.seasons[app.model.seasons.length - 1].season;
};

app.unitIndex = (id) => app.model.byId.get(id);

// The filters a view shows: element and burst everywhere, role, weapon and maker on the unit list (``more``).
app.passes = (unit, more = false) => {
  const f = state.filters;
  if (f.elements.size && !M.unitElements(unit, true).some((m) => f.elements.has(m.element))) return false;
  if (f.bursts.size && !(f.bursts.has(unit.burst) || unit.burst === "I-II-III")) return false;
  if (!more) return true;
  if (f.classes.size && !f.classes.has(unit.class)) return false;
  if (f.weapons.size && !f.weapons.has(unit.weapon)) return false;
  if (f.makers.size && !f.makers.has(unit.manufacturer)) return false;
  return true;
};

// ---------------------------------------------------------------------------
// the URL: #/tier?v=..&s=..  ·  #/trend[/<unit id> | /compare | /weak]  (and the old
// #/season/<n>, #/date, #/unit/<id>, read as the places they became)

app.query = (extra = {}) => {
  const q = new URLSearchParams(encodeParams(state.params, app.defaults));
  for (const [k, v] of Object.entries(extra)) if (v != null && v !== "") q.set(k, v);
  const text = q.toString().replace(/%2C/gi, ","); // lists read better with their commas
  return text ? `?${text}` : "";
};

// Which kind of place a state is: the within-place choices (the weakness) do not travel between kinds.
const placeOf = (st) => (st.tab === "tier" ? (st.view === "season" ? "tier-season" : "tier") : `trend-${st.trend}`);

const compareText = (list) => {
  const ids = list.map((u) => (u == null ? "" : app.model.units[u].id));
  while (ids.length && !ids[ids.length - 1]) ids.pop();
  return ids.join(",");
};

function hashOf(st) {
  const extra = { d: st.date, c: compareText(st.compare) };
  let path;
  if (st.tab === "tier") {
    path = "#/tier";
    if (st.view !== "overall") extra.v = st.view;
    if (st.view === "season") { extra.s = st.season; extra.wk = st.weak; }
    if (st.mode === "table") extra.m = "table";
  } else {
    const arg = st.trend === "unit" ? (st.unit != null ? app.model.units[st.unit].id : null) : st.trend;
    path = `#/trend${arg != null ? `/${arg}` : ""}`;
    if (st.trend !== "compare" && !(st.trend === "unit" && st.unit == null)) extra.wk = st.weak;
  }
  return `${path}${app.query(extra)}`;
}

// A link to the state ``patch`` makes. Moving to another kind of place drops the weakness
// unless the patch names one.
app.link = (patch = {}) => {
  const next = { ...state, ...patch };
  if (!("weak" in patch) && placeOf(next) !== placeOf(state)) next.weak = null;
  return hashOf(next);
};
app.seasonHref = (season) => app.link({ tab: "tier", view: "season", season });
app.unitHref = (id) => app.link({ tab: "trend", trend: "unit", unit: app.unitIndex(id) });
app.weakHref = (weak) => app.link({ tab: "trend", trend: "weak", weak });
app.tierHref = (view) => app.link({ tab: "tier", view });

// The compare list (``base``) with ``u`` added in the first free slot (or as it was, when it
// is in or full), or taken out leaving its slot empty.
app.withCompared = (u, base = state.compare) => {
  const list = [...base];
  if (list.includes(u)) return list;
  const free = list.findIndex((x) => x == null);
  if (free >= 0) list[free] = u;
  else if (list.length < COMPARE_MAX) list.push(u);
  return list;
};
app.withoutCompared = (u, base = state.compare) => {
  const list = base.map((x) => (x === u ? null : x));
  while (list.length && list[list.length - 1] == null) list.pop();
  return list;
};

function currentHash() {
  return hashOf(state);
}

function readHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const [tab, arg] = path.split("/");
  const q = new URLSearchParams(query);
  state.params = decodeParams(q, app.defaults, app.model);
  state.date = /^\d{4}-\d{2}-\d{2}$/.test(q.get("d") || "") ? q.get("d") : null;
  state.weak = M.ELEMENTS.includes(q.get("wk")) ? q.get("wk") : null;
  state.mode = q.get("m") === "table" ? "table" : "tiers";
  const seasonOf = (n) => (app.model.seasons.some((s) => s.season === Number(n)) ? Number(n) : null);
  state.compare = (q.get("c") || "").split(",").slice(0, COMPARE_MAX)
    .map((id) => (id ? app.unitIndex(id) ?? null : null))
    .map((u, i, all) => (u != null && all.indexOf(u) !== i ? null : u));
  while (state.compare.length && state.compare[state.compare.length - 1] == null) state.compare.pop();
  state.unit = null;
  if (tab === "trend" || tab === "unit") {
    state.tab = "trend";
    state.trend = TRENDS.includes(arg) && arg !== "unit" ? arg : "unit";
    if (state.trend === "unit" && arg != null && arg !== "unit") state.unit = app.unitIndex(decodeURIComponent(arg)) ?? null;
  } else {
    state.tab = "tier";
    const v = q.get("v");
    state.view = tab === "season" ? "season" : v === "season" || M.ELEMENTS.includes(v) ? v : "overall";
    state.season = seasonOf(tab === "season" ? arg : q.get("s"));
    // the old date tab's weakness filter did not exist; the old season tab's did
    if (state.view !== "season") state.weak = null;
  }
  if (!TABS.includes(state.tab)) state.tab = "tier";
}

// Navigation and view changes: a history entry per place, a replaced one per tweak.
//
// A place just reached opens at its top; back and forward leave the scroll to the
// browser, which puts it back where it was. The entries the page has shown carry a
// state, so one without is a place a followed link or an edited address just made.
const SHOWN = { shown: true };
let shownHash = null;

app.go = (patch, { replace = false } = {}) => {
  Object.assign(state, patch);
  const hash = currentHash();
  const moved = !replace && location.hash !== hash;
  if (replace) history.replaceState(SHOWN, "", hash);
  else if (moved) history.pushState(SHOWN, "", hash);
  shownHash = location.hash;
  render();
  if (moved) window.scrollTo(0, 0);
};

app.setParams = (patch) => {
  state.params = M.normalizeParams({ ...state.params, ...patch });
  history.replaceState(SHOWN, "", currentHash());
  shownHash = location.hash;
  renderSoon();
};

// Back, forward, a followed link or an edited address: read the state back from the URL.
function onNavigate() {
  if (location.hash === shownHash) return;
  shownHash = location.hash;
  const fresh = history.state == null;
  if (fresh) history.replaceState(SHOWN, "");
  readHash();
  canonical();
  buildParams(app, document.getElementById("params-body"));
  render();
  if (fresh) window.scrollTo(0, 0);
}

// An old address (#/season/40, #/date, #/unit/330) or a bare one becomes the place's own.
function canonical() {
  const hash = currentHash();
  if (location.hash !== hash) history.replaceState(history.state ?? SHOWN, "", hash);
  shownHash = location.hash;
}

app.resetParams = () => app.setParams(app.defaults);

app.rerender = () => render();

// ---------------------------------------------------------------------------
// rendering

const main = document.getElementById("view");
let pending = 0;

function renderSoon() {
  main.classList.add("busy");
  clearTimeout(pending);
  pending = setTimeout(() => render(), 30);
}

function render() {
  clearTimeout(pending);
  hideTip();
  for (const a of document.querySelectorAll("[data-tab]")) {
    const on = a.dataset.tab === state.tab;
    a.setAttribute("aria-current", on ? "page" : "false");
    // the unit tab opens on its list, to pick a unit from
    // a tab goes back to where it was left; pressed while on it, to its start (the unit list)
    a.href = a.dataset.tab === "tier" ? app.link({ tab: "tier" })
      : app.link({ tab: "trend", unit: on && state.trend === "unit" ? null : state.unit });
  }
  renderParamsBadge();
  const started = performance.now();
  let content;
  try {
    content = VIEWS[state.tab](app);
  } catch (err) {
    console.error(err);
    content = h("div", { class: "panel empty" }, "계산 중 문제가 생겼습니다: ", String(err.message || err));
  }
  main.replaceChildren(content);
  main.classList.remove("busy");
  main.dataset.ms = String(Math.round(performance.now() - started));
  const place = state.tab === "tier"
    ? (state.view === "season" ? "시즌 티어" : state.view === "overall" ? "종합 티어" : `${ELEMENT_KO[state.view]} 속성 티어`)
    : state.trend === "compare" ? "니케 비교" : state.trend === "weak" ? "약점별 시즌"
      : state.unit != null ? `${unitName(app.model.units[state.unit])} · 티어 변화` : "티어 변화";
  document.title = `${place} · 니케 솔로 레이드 티어`;
}

function renderParamsBadge() {
  const changed = changedParams(state.params, app.defaults);
  const badge = document.getElementById("params-count");
  badge.textContent = changed.length ? String(changed.length) : "";
  badge.hidden = !changed.length;
  const sample = document.getElementById("sample");
  const dropped = app.model.servers.filter((s) => !state.params.servers.includes(s));
  const where = !dropped.length ? "전 서버" : dropped.length <= 2 ? `${dropped.join("·")} 제외` : state.params.servers.join("·");
  sample.textContent = `${where} · 상위 ${state.params.topN}위`;
  renderParamsFoot(app, () => buildParams(app, document.getElementById("params-body")));
}

// ---------------------------------------------------------------------------
// theme

function initTheme() {
  const button = document.getElementById("theme");
  const apply = (theme) => {
    document.documentElement.dataset.theme = theme;
    button.setAttribute("aria-label", theme === "dark" ? "라이트 모드로" : "다크 모드로");
    button.title = button.getAttribute("aria-label");
  };
  apply(document.documentElement.dataset.theme || "dark");
  button.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    apply(next);
    try { localStorage.setItem("theme", next); } catch { /* private mode: the toggle just is not remembered */ }
    render();
  });
}

// ---------------------------------------------------------------------------

async function boot() {
  initTheme();
  initTip(document.getElementById("tip"));
  main.replaceChildren(h("div", { class: "loading" }, h("span", { class: "spinner" }), "랭킹 데이터를 불러오는 중…"));
  try {
    const model = await (await fetch("data/model.json", { cache: "no-cache" })).json();
    const decks = await (await fetch(`data/decks.json?v=${model.dataVersion}`)).json();
    model.byId = new Map(model.units.map((u, i) => [u.id, i]));
    model.bySeason = new Map(model.seasons.map((s) => [s.season, s]));
    app.model = model;
    app.decks = decks;
    app.defaults = M.defaultParams(model);
  } catch (err) {
    console.error(err);
    main.replaceChildren(h("div", { class: "panel empty" }, "데이터를 불러오지 못했습니다. 새로고침해 보세요."));
    return;
  }
  const collected = Math.max(...app.model.seasons.map((s) => s.collected ?? -Infinity));
  document.getElementById("asof").textContent = `랭킹 ${day(collected)} 수집분까지`;
  readHash();
  if (history.state == null) history.replaceState(SHOWN, "");
  canonical();
  buildParams(app, document.getElementById("params-body"));
  window.addEventListener("popstate", onNavigate);
  window.addEventListener("hashchange", onNavigate);
  render();
}

// the parameter drawer
const drawer = document.getElementById("params");
const scrim = document.getElementById("scrim");
function openDrawer(open) {
  if (!open && drawer.contains(document.activeElement)) document.getElementById("params-open").focus({ preventScroll: true });
  drawer.classList.toggle("open", open);
  drawer.setAttribute("aria-hidden", String(!open));
  drawer.inert = !open;
  scrim.classList.toggle("on", open);
  document.getElementById("params-open").setAttribute("aria-expanded", String(open));
  if (open) drawer.querySelector("button, input")?.focus({ preventScroll: true });
}
document.getElementById("params-open").addEventListener("click", () => openDrawer(!drawer.classList.contains("open")));
document.getElementById("params-close").addEventListener("click", () => openDrawer(false));
scrim.addEventListener("click", () => openDrawer(false));
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && drawer.classList.contains("open")) openDrawer(false); });
drawer.inert = true;

boot();
