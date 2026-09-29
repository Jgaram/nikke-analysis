// The page: state in the URL, the computation cached per parameter set, three views.

import * as M from "./model.js";
import { h, initTip, hideTip, day, noonKst, todayKst } from "./ui.js";
import { buildParams, encodeParams, decodeParams, changedParams, renderParamsFoot } from "./params.js";
import { seasonView } from "./views/season.js";
import { dateView } from "./views/date.js";
import { unitView } from "./views/unit.js";

const TABS = ["season", "date", "unit"];
const VIEWS = { season: seasonView, date: dateView, unit: unitView };

const state = {
  tab: "season",
  season: null,
  date: null, // "YYYY-MM-DD"; null = now
  view: "overall", // date tab: overall or an element
  mode: "tiers", // tiers | table
  unit: null, // unit index
  params: null,
  filters: { elements: new Set(), classes: new Set(), bursts: new Set() },
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

app.passes = (unit) => {
  const f = state.filters;
  if (f.elements.size && !M.unitElements(unit, true).some((m) => f.elements.has(m.element))) return false;
  if (f.classes.size && !f.classes.has(unit.class)) return false;
  if (f.bursts.size && !(f.bursts.has(unit.burst) || unit.burst === "I-II-III")) return false;
  return true;
};

// ---------------------------------------------------------------------------
// the URL: #/<tab>[/<arg>]?<query>

app.query = (extra = {}) => {
  const q = new URLSearchParams(encodeParams(state.params, app.defaults));
  for (const [k, v] of Object.entries(extra)) if (v != null && v !== "") q.set(k, v);
  const text = q.toString();
  return text ? `?${text}` : "";
};

app.href = (tab, arg = null, extra = {}) => {
  const keep = {};
  if (tab === "date" || tab === "unit") keep.d = state.date;
  if (tab === "date") keep.v = state.view !== "overall" ? state.view : null;
  if (tab !== "unit" && state.mode === "table") keep.m = "table";
  return `#/${tab}${arg != null ? `/${arg}` : ""}${app.query({ ...keep, ...extra })}`;
};

function currentHash() {
  const arg = state.tab === "season" ? state.season : state.tab === "unit" && state.unit != null
    ? app.model.units[state.unit].id : null;
  return app.href(state.tab, arg);
}

function readHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const [tab, arg] = path.split("/");
  const q = new URLSearchParams(query);
  state.tab = TABS.includes(tab) ? tab : "season";
  state.params = decodeParams(q, app.defaults, app.model);
  state.date = /^\d{4}-\d{2}-\d{2}$/.test(q.get("d") || "") ? q.get("d") : null;
  state.view = M.ELEMENTS.includes(q.get("v")) ? q.get("v") : "overall";
  state.mode = q.get("m") === "table" ? "table" : "tiers";
  if (state.tab === "season") {
    const n = Number(arg);
    state.season = app.model.seasons.some((s) => s.season === n) ? n : null;
  }
  if (state.tab === "unit") {
    const u = arg != null ? app.unitIndex(decodeURIComponent(arg)) : undefined;
    if (u != null) state.unit = u;
  }
}

// Navigation and view changes: a history entry per place, a replaced one per tweak.
let shownHash = null;

app.go = (patch, { replace = false } = {}) => {
  Object.assign(state, patch);
  const hash = currentHash();
  if (replace) history.replaceState(null, "", hash);
  else if (location.hash !== hash) history.pushState(null, "", hash);
  shownHash = location.hash;
  render();
};

app.setParams = (patch) => {
  state.params = M.normalizeParams({ ...state.params, ...patch });
  history.replaceState(null, "", currentHash());
  shownHash = location.hash;
  renderSoon();
};

// Back, forward, a followed link or an edited address: read the state back from the URL.
function onNavigate() {
  if (location.hash === shownHash) return;
  shownHash = location.hash;
  readHash();
  buildParams(app, document.getElementById("params-body"));
  render();
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
    const arg = a.dataset.tab === "season" ? state.season : a.dataset.tab === "unit" && state.unit != null
      ? app.model.units[state.unit].id : null;
    a.href = app.href(a.dataset.tab, arg);
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
  document.title = `${{ season: "시즌별 티어", date: "날짜별 티어", unit: "니케 추이" }[state.tab]} · 니케 솔로 레이드 티어`;
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
  shownHash = location.hash;
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
