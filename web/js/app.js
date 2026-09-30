// The page: state in the URL, the computation cached per parameter set, two tabs -
// 티어표 (where every unit stands: over every season, one weakness's, or one season alone)
// and 변화 (how it moved: one unit, or units side by side - over every season, or one
// weakness's). Both read at one moment: the chosen season, once it was over, or now.

import * as M from "./model.js";
import { h, initTip, hideTip, day, noonKst, todayKst, unitName, ELEMENT_KO } from "./ui.js";
import { buildParams, encodeParams, decodeParams, changedParams, renderParamsFoot, renderHowto } from "./params.js";
import { seasonView } from "./views/season.js";
import { dateView } from "./views/date.js";
import { unitView } from "./views/unit.js";
import { pickView } from "./views/pick.js";
import { compareView, COMPARE_MAX } from "./views/trend.js";
import { metaView } from "./views/meta.js";

const TABS = ["tier", "trend", "meta"];
const TRENDS = ["unit", "compare"];
const VIEWS = {
  tier: (app) => (app.state.view === "raid" ? seasonView(app) : dateView(app)),
  trend: (app) => ({
    unit: () => (app.state.unit == null ? pickView(app) : unitView(app)),
    compare: () => compareView(app),
  })[app.state.trend](),
  meta: (app) => metaView(app),
};

const state = {
  tab: "tier",
  view: "overall", // 티어표: overall, an element (the boss's weakness), or raid
  season: null, // the season every view reads at, as it stood once over; null = now (the newest)
  weak: null, // the unit chart's weakness, or the comparison's
  mode: "tiers", // 티어표: tiers | table
  trend: "unit", // 변화: unit (the list, or one unit) | compare
  unit: null, // unit index; null on 변화 · unit = the list to pick one from
  compare: [], // the units compared, in the order they were added
  query: "", // the unit list's search
  params: null,
  filters: { elements: new Set(), bursts: new Set(), classes: new Set(), weapons: new Set(), makers: new Set() },
  showUnused: false,
  showNums: false, // 티어표 cards: their number (기여도)
  showBands: false, // 티어표 cards: their generality bar
  expanded: new Set(),
  sort: {},
};

const app = { state, model: null, decks: null, defaults: null };
const cache = { pop: null, popKey: null, hist: null, histKey: null, views: new Map(), meta: null, metaKey: null };

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

// The meta tab's numbers: they move with the population and the career parameters.
app.metaTrend = () => {
  const pop = app.population();
  const key = `${M.populationKey(state.params)}|${M.lifeKey(state.params)}`;
  if (cache.metaKey !== key) {
    cache.meta = { trend: M.metaTrend(app.model, pop, state.params), debuts: M.debuts(app.model, pop, state.params) };
    cache.metaKey = key;
  }
  return cache.meta.trend;
};
app.debuts = () => { app.metaTrend(); return cache.meta.debuts; };

app.profile = (u, moment) => M.unitProfile(app.model, app.population(), moment, state.params, u);

// The moment every view is read at: now, or the chosen season as the tier history has it -
// its end once its ranking is final, else the end of the day its ranking was collected.
app.moment = () => {
  const entry = state.season != null ? app.population().tables.get(state.season) : null;
  if (!entry) return Date.now();
  return entry.final ? entry.end : entry.collectedUntil;
};

// The chosen moment, when one is chosen (the charts mark it); null = now.
app.pinned = () => (state.season != null ? app.moment() : null);

// The season open at ``moment``, else the last one over by then - with a ranking; null when
// that is the newest (read now). What an old address's day (?d=2024-11-04) became.
function seasonAt(moment) {
  const pop = app.population();
  const around = M.seasonsAround(app.model, moment);
  const hit = [around.current, around.previous].find((s) => s && pop.tables.has(s.season));
  return hit && hit.season !== app.latestSeason() ? hit.season : null;
}

app.latestSeason = () => {
  const ranked = app.population().summary;
  return ranked.length ? ranked[ranked.length - 1].season : app.model.seasons[app.model.seasons.length - 1].season;
};

app.unitIndex = (id) => app.model.byId.get(id);

// The filters: element, burst, role, weapon and maker.
app.passes = (unit, more = true) => {
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
// the URL: #/tier?v=..&s=..  ·  #/trend[/<unit id> | /compare]?s=..  (and the old #/season/<n>,
// #/date, #/unit/<id>, #/trend/weak, v=season and d=<day>, read as the places they became)

app.query = (extra = {}) => {
  const q = new URLSearchParams(encodeParams(state.params, app.defaults));
  for (const [k, v] of Object.entries(extra)) if (v != null && v !== "") q.set(k, v);
  const text = q.toString().replace(/%2C/gi, ","); // lists read better with their commas
  return text ? `?${text}` : "";
};

// Which kind of place a state is: the within-place choices (the weakness) do not travel between kinds.
const placeOf = (st) => (st.tab === "trend" ? `trend-${st.trend}` : st.tab);

const compareText = (list) => list.map((u) => app.model.units[u].id).join(",");

function hashOf(st) {
  const extra = { s: st.season, c: compareText(st.compare) };
  let path;
  if (st.tab === "tier") {
    path = "#/tier";
    if (st.view !== "overall") extra.v = st.view;
    if (st.mode === "table") extra.m = "table";
  } else if (st.tab === "meta") {
    path = "#/meta";
  } else {
    const arg = st.trend === "unit" ? (st.unit != null ? app.model.units[st.unit].id : null) : st.trend;
    path = `#/trend${arg != null ? `/${arg}` : ""}`;
    if (!(st.trend === "unit" && st.unit == null)) extra.wk = st.weak;
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
app.seasonHref = (season) => app.link({ tab: "tier", view: "raid", season: season === app.latestSeason() ? null : season });
app.unitHref = (id) => app.link({ tab: "trend", trend: "unit", unit: app.unitIndex(id) });
app.weakHref = (weak) => app.link({ tab: "trend", trend: "compare", weak });
app.tierHref = (view) => app.link({ tab: "tier", view });

// The compare list (``base``) with ``u`` added at the end (as it was, when it is in or full),
// or taken out.
app.withCompared = (u, base = state.compare) => (base.includes(u) || base.length >= COMPARE_MAX ? [...base] : [...base, u]);
app.withoutCompared = (u, base = state.compare) => base.filter((x) => x !== u);

function currentHash() {
  return hashOf(state);
}

function readHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const [tab, arg] = path.split("/");
  const q = new URLSearchParams(query);
  state.params = decodeParams(q, app.defaults, app.model);
  state.weak = M.ELEMENTS.includes(q.get("wk")) ? q.get("wk") : null;
  state.mode = q.get("m") === "table" ? "table" : "tiers";
  const seasonOf = (n) => (n != null && app.model.seasons.some((s) => s.season === Number(n)) ? Number(n) : null);
  const day = q.get("d") || "";
  state.season = seasonOf(tab === "season" ? arg : q.get("s"))
    ?? (/^\d{4}-\d{2}-\d{2}$/.test(day) && day < todayKst() ? seasonAt(noonKst(day)) : null);
  state.compare = [...new Set((q.get("c") || "").split(",").map((id) => (id ? app.unitIndex(id) : null))
    .filter((u) => u != null))].slice(0, COMPARE_MAX);
  state.unit = null;
  if (tab === "trend" || tab === "unit") {
    state.tab = "trend";
    // 약점별 시즌 became the comparison with a weakness chosen
    state.trend = arg === "compare" || arg === "weak" ? "compare" : "unit";
    if (state.trend === "unit" && arg != null && arg !== "unit") state.unit = app.unitIndex(decodeURIComponent(arg)) ?? null;
  } else if (tab === "meta") {
    state.tab = "meta";
    state.weak = null;
  } else {
    state.tab = "tier";
    const v = q.get("v");
    state.view = tab === "season" || v === "season" || v === "raid" ? "raid" : M.ELEMENTS.includes(v) ? v : "overall";
    state.weak = null; // the old season tab's strip filter is gone: its weakness has its own tier
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
    a.href = a.dataset.tab === "tier" ? app.link({ tab: "tier" }) : a.dataset.tab === "meta" ? app.link({ tab: "meta" })
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
  const place = state.tab === "meta" ? "메타 변화" : state.tab === "tier"
    ? (state.view === "raid" ? "레이드별 티어" : state.view === "overall" ? "종합 티어" : `${ELEMENT_KO[state.view]} 약점 티어`)
    : state.trend === "compare" ? (state.weak ? `니케 비교 · ${ELEMENT_KO[state.weak]} 약점` : "니케 비교")
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
  renderHowto(state.params);
}

// ---------------------------------------------------------------------------
// theme

// The device's setting until the toggle is pressed; then the pick, remembered.
function initTheme() {
  const button = document.getElementById("theme");
  const meta = document.querySelector('meta[name="theme-color"]');
  const system = matchMedia("(prefers-color-scheme: light)");
  const stored = () => { try { return localStorage.getItem("theme"); } catch { return null; } };
  const apply = (theme) => {
    document.documentElement.dataset.theme = theme;
    button.setAttribute("aria-label", theme === "dark" ? "라이트 모드로" : "다크 모드로");
    button.title = button.getAttribute("aria-label");
    meta?.setAttribute("content", theme === "dark" ? "#080b12" : "#eef1f6");
  };
  apply(document.documentElement.dataset.theme || (system.matches ? "light" : "dark"));
  button.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    apply(next);
    try { localStorage.setItem("theme", next); } catch { /* private mode: the toggle just is not remembered */ }
    if (app.model) render();
  });
  system.addEventListener?.("change", () => {
    if (stored() === "light" || stored() === "dark") return;
    apply(system.matches ? "light" : "dark");
    if (app.model) render();
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
