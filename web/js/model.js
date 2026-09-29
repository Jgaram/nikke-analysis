// The tier computation, in the browser.
//
// This follows analyze/metrics.py and analyze/tiers.py step for step, so that
// with the defaults of config/tiers.yaml the page shows what the committed
// tables say (tests/test_web.py checks it). Two levels, cached separately:
//
//   population  servers, ranks 1..topN, rank weighting
//               -> per season and unit: usage, deck split, lift (기여도)
//   tiers       cuts, recency, prior, how the overall is formed, the live season
//               -> element and overall tiers at any moment, a unit's history
//   lifespans   what counts as used, how long idle - and through how many seasons of
//               its own element - means retired
//               -> since when each unit was in use, and whether it still is
//
// No DOM here: the same module runs under Node for the tests.

export const ELEMENTS = ["Fire", "Water", "Wind", "Iron", "Electric"];
export const OVERALL_MODES = ["mean", "frequency", "max"];
export const DAY_MS = 86_400_000;

// ---------------------------------------------------------------------------
// parameters

export function defaultParams(model) {
  const d = model.defaults;
  const include = d.servers.length ? new Set(d.servers) : null;
  const exclude = new Set(d.excludeServers);
  return normalizeParams({
    servers: model.servers.filter((s) => (!include || include.has(s)) && !exclude.has(s)),
    topN: d.topN,
    rankWeighting: d.rankWeighting,
    cuts: d.cuts.map(([label, value]) => [label, value]),
    halfLifeDays: d.halfLifeDays,
    priorStrength: d.priorStrength,
    overall: d.overall,
    minElementsObserved: d.minElementsObserved,
    includeLive: d.includeLive,
    minUsage: d.minUsage,
    retireAfterDays: d.retireAfterDays,
    retireAfterOwnSeasons: d.retireAfterOwnSeasons,
  });
}

export function normalizeParams(p) {
  const cuts = p.cuts.map(([label, value]) => [String(label), Number(value)]);
  cuts.sort((a, b) => b[1] - a[1]);
  if (!OVERALL_MODES.includes(p.overall)) throw new Error(`overall must be one of ${OVERALL_MODES}`);
  return { ...p, cuts, servers: [...p.servers] };
}

export function populationKey(p) {
  return JSON.stringify([[...p.servers].sort(), p.topN, p.rankWeighting]);
}

export function tierKey(p) {
  return JSON.stringify([p.cuts, p.halfLifeDays, p.priorStrength, p.overall, p.minElementsObserved, p.includeLive]);
}

export function lifeKey(p) {
  return JSON.stringify([p.minUsage, p.retireAfterDays, p.retireAfterOwnSeasons]);
}

// ---------------------------------------------------------------------------
// helpers

export function assignTier(value, cuts) {
  if (value == null || Number.isNaN(value)) return "";
  for (const [label, minimum] of cuts) if (value >= minimum) return label;
  return cuts[cuts.length - 1][0];
}

export function tierIndex(label, cuts) {
  const i = cuts.findIndex(([l]) => l === label);
  return i < 0 ? cuts.length : i;
}

export function rankWeight(rank, scheme) {
  const r = rank < 1 ? 1 : rank;
  if (scheme === "uniform") return 1;
  if (scheme !== "dcg") throw new Error(`unknown rank weighting ${scheme}`);
  return 1 / Math.log2(r + 1);
}

// Compensated summation into slot ``i`` of ``sum``/``comp``, as pandas' group sums do.
function kahan(sum, comp, i, value) {
  const y = value - comp[i];
  const t = sum[i] + y;
  comp[i] = t - sum[i] - y;
  sum[i] = t;
}

function median(values) {
  if (!values.length) return NaN;
  const v = [...values].sort((a, b) => a - b);
  const mid = v.length >> 1;
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
}

// Ranks, best first, ties sharing the lowest (pandas rank(method="min", ascending=False)); NaN -> null.
function minRanks(values) {
  const order = values.map((v, i) => i).filter((i) => !Number.isNaN(values[i]));
  order.sort((a, b) => values[b] - values[a]);
  const ranks = new Array(values.length).fill(null);
  for (let k = 0; k < order.length; k++) {
    const i = order[k];
    ranks[i] = k > 0 && values[order[k - 1]] === values[i] ? ranks[order[k - 1]] : k + 1;
  }
  return ranks;
}

function decay(ageDays, halfLifeDays) {
  if (halfLifeDays <= 0) return 1;
  return Math.pow(0.5, Math.max(ageDays, 0) / halfLifeDays);
}

function nanMean(values) {
  let sum = 0, n = 0;
  for (const v of values) if (!Number.isNaN(v)) { sum += v; n++; }
  return n ? sum / n : NaN;
}

const cmpId = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

// ---------------------------------------------------------------------------
// population: per season and unit (analyze/metrics.py unit_season, season_summary)

export function computeTables(model, decks, params) {
  const U = model.units.length;
  const keep = model.servers.map((s) => params.servers.includes(s));
  const tables = new Map();
  const summary = [];
  for (const info of model.seasons) {
    const list = decks.seasons[String(info.season)];
    if (!list) continue;
    const credit = new Float64Array(U), creditC = new Float64Array(U);
    const wUsed = new Float64Array(U), wUsedC = new Float64Array(U);
    const wShare = new Float64Array(U), wShareC = new Float64Array(U);
    const wMain = new Float64Array(U), wMainC = new Float64Array(U);
    const users = new Int32Array(U);
    const best = new Float64Array(U).fill(Infinity);
    const inDeck = Array.from({ length: 5 }, () => new Int32Array(U));
    const seenBy = new Int32Array(U);
    const seasonW = new Float64Array(1), seasonWC = new Float64Array(1);
    const slotCounts = [];
    const servers = new Set();
    let rankers = 0, fielded = 0;
    for (let i = 0; i < list.length; i++) {
      const ranker = list[i];
      const server = ranker[0], rank = ranker[1];
      if (!keep[server] || rank < 1 || rank > params.topN) continue;
      const nd = ranker.length - 2;
      let total = 0;
      for (let d = 0; d < nd; d++) total += ranker[2 + d][0];
      const order = Array.from({ length: nd }, (_, d) => d).sort((a, b) => ranker[2 + b][0] - ranker[2 + a][0]);
      const deckRank = new Array(nd);
      order.forEach((d, position) => { deckRank[d] = position + 1; });
      const w = rankWeight(rank, params.rankWeighting);
      kahan(seasonW, seasonWC, 0, w);
      rankers++;
      fielded += nd;
      servers.add(model.servers[server]);
      let slots = 0;
      const stamp = i + 1;
      for (let d = 0; d < nd; d++) {
        const deck = ranker[2 + d];
        const size = deck.length - 1;
        slots += size;
        const share = total > 0 ? deck[0] / total : 0;
        const part = (w * share) / size;
        const main = deckRank[d] === 1 ? w : 0;
        for (let j = 1; j < deck.length; j++) {
          const u = deck[j];
          kahan(credit, creditC, u, part);
          if (seenBy[u] !== stamp) {
            seenBy[u] = stamp;
            users[u]++;
            kahan(wUsed, wUsedC, u, w);
            kahan(wShare, wShareC, u, w * share);
            kahan(wMain, wMainC, u, main);
            if (rank < best[u]) best[u] = rank;
            inDeck[deckRank[d] - 1][u]++;
          }
        }
      }
      slotCounts.push(slots);
    }
    if (!rankers) continue;
    const slots = median(slotCounts);
    const W = seasonW[0];
    const rows = [];
    for (let u = 0; u < U; u++) {
      const unit = model.units[u];
      const used = users[u] > 0;
      if (!used && !(info.start != null && unit.release != null && unit.release <= info.start)) continue;
      const c = used ? credit[u] / W : 0;
      const split = inDeck.map((a) => a[u]);
      const treasure = unit.treasure != null && info.start != null && unit.treasure <= info.start;
      const weak = info.weak || "?";
      const elementMatch = (unit.element || "") === weak || unit.extra.includes(info.weak)
        || (treasure && unit.treasureElements.includes(info.weak));
      rows.push({
        u,
        id: unit.id,
        season: info.season,
        rankers: users[u],
        bestRank: used ? best[u] : NaN,
        presence: used ? wUsed[u] / W : 0,
        credit: c,
        deckShare: used ? wShare[u] / wUsed[u] : NaN,
        mainDeckRate: used ? wMain[u] / wUsed[u] : NaN,
        inDeck: split,
        avgDeck: used ? split.reduce((s, n, k) => s + n * (k + 1), 0) / users[u] : NaN,
        usageRate: users[u] / rankers,
        usageRank: 0,
        lift: c * slots,
        treasure,
        elementMatch,
      });
    }
    const ranks = minRanks(rows.map((r) => r.rankers));
    rows.forEach((r, k) => { r.usageRank = ranks[k]; });
    rows.sort((a, b) => b.lift - a.lift || cmpId(a.id, b.id));
    const collectedOn = info.collected;
    const collectedUntil = collectedOn != null ? collectedOn + DAY_MS - 1000 : null;
    const entry = {
      season: info.season,
      info,
      start: info.start,
      end: info.end,
      weak: info.weak,
      collectedOn,
      collectedUntil,
      final: info.end != null && collectedUntil != null && collectedUntil >= info.end,
      rankers,
      decks: fielded,
      slots,
      servers: model.servers.filter((s) => servers.has(s)),
      rows,
      byUnit: new Map(rows.map((r) => [r.u, r])),
    };
    tables.set(info.season, entry);
    summary.push(entry);
  }
  return { tables, summary };
}

// ---------------------------------------------------------------------------
// tiers at a moment (analyze/tiers.py standings)

// The seasons a view at ``moment`` stands on: every season over by then and, with
// includeLive, the season in progress once a snapshot of it was taken by then.
export function countedSeasons(summary, moment, params) {
  const out = [];
  for (const s of summary) {
    const over = s.final && s.end != null && s.end <= moment;
    const live = params.includeLive && !s.final && s.collectedOn != null && s.collectedOn <= moment;
    if (over || live) out.push({ season: s.season, start: s.start, end: s.end, weak: s.weak, live: !over });
  }
  return out;
}

// Every element a unit counts as: its own, the ones its skill adds, and - for a
// unit with its treasure - the ones the treasure's skill adds.
export function unitElements(unit, treasured) {
  const list = [];
  const add = (e, source) => {
    if (ELEMENTS.includes(e) && !list.some((m) => m.element === e)) list.push({ element: e, source });
  };
  add(unit.element, "own");
  for (const e of unit.extra) add(e, "skill");
  if (treasured) for (const e of unit.treasureElements) add(e, "skill");
  return list;
}

const EMPTY_STANDINGS = (counted) => ({
  counted, overall: [], overallByUnit: new Map(), elements: [], slots: new Map(), treasured: new Set(),
});

export function standings(model, population, moment, params, treasured = null) {
  const counted = countedSeasons(population.summary, moment, params);
  const picked = [];
  for (const c of counted) {
    if (!ELEMENTS.includes(c.weak)) continue;
    const at = c.end != null && c.end <= moment ? c.end : moment;
    const w = decay((moment - at) / DAY_MS, params.halfLifeDays);
    for (const r of population.tables.get(c.season).rows) picked.push({ r, e: ELEMENTS.indexOf(c.weak), w });
  }
  if (treasured == null) treasured = new Set(picked.filter((x) => x.r.treasure).map((x) => x.r.u));
  const rows = picked.filter((x) => x.r.treasure === treasured.has(x.r.u));
  if (!rows.length) return EMPTY_STANDINGS(counted);

  // per unit: all its seasons, and per boss weakness (slot)
  const per = new Map();
  for (const { r, e, w } of rows) {
    let a = per.get(r.u);
    if (!a) {
      a = {
        W: [0], WC: [0], WL: [0], WLC: [0], seasons: 0, last: -Infinity,
        sW: new Float64Array(5), sWC: new Float64Array(5), sWL: new Float64Array(5), sWLC: new Float64Array(5),
        n: new Int32Array(5),
      };
      per.set(r.u, a);
    }
    kahan(a.W, a.WC, 0, w);
    kahan(a.WL, a.WLC, 0, w * r.lift);
    a.seasons++;
    if (r.season > a.last) a.last = r.season;
    kahan(a.sW, a.sWC, e, w);
    kahan(a.sWL, a.sWLC, e, w * r.lift);
    a.n[e]++;
  }
  const units = [...per.keys()].sort((x, y) => cmpId(model.units[x].id, model.units[y].id));
  const k = params.priorStrength;

  let freq = null;
  if (params.overall === "frequency") {
    freq = new Array(5).fill(0);
    for (const c of counted) {
      const at = c.end != null && c.end <= moment ? c.end : moment;
      const e = ELEMENTS.indexOf(c.weak);
      if (e >= 0) freq[e] += decay((moment - at) / DAY_MS, params.halfLifeDays);
    }
    const total = freq.reduce((s, v) => s + v, 0);
    freq = total > 0 ? freq.map((v) => v / total) : freq.map(() => 1 / 5);
  }

  const overall = [], elements = [], slots = new Map();
  for (const u of units) {
    const a = per.get(u);
    const unit = model.units[u];
    const prior = a.WL[0] / a.W[0];
    const observed = ELEMENTS.map((_, e) => a.n[e] > 0);
    const mean = ELEMENTS.map((_, e) => (observed[e] ? a.sWL[e] / a.sW[e] : NaN));
    const level = k <= 0 ? mean
      : ELEMENTS.map((_, e) => (observed[e] ? (a.n[e] * mean[e] + k * prior) / (a.n[e] + k) : NaN));
    const members = unitElements(unit, treasured.has(u));
    const own = ELEMENTS.map((e) => members.some((m) => m.element === e));
    // An unseen slot: the mean of the other elements seen for another element (0 with none
    // seen yet), 0 for an element of its own.
    let otherLevel = nanMean(level.filter((_, e) => !own[e]));
    if (Number.isNaN(otherLevel)) otherLevel = 0;
    const estimate = ELEMENTS.map((_, e) => (observed[e] ? level[e] : own[e] ? 0 : otherLevel));

    for (const m of members) {
      const e = ELEMENTS.indexOf(m.element);
      const seen = a.n[e];
      elements.push({ u, id: unit.id, element: m.element, source: m.source, lift: seen > 0 ? estimate[e] : NaN,
        seasons: seen, treasure: treasured.has(u) });
    }

    let value;
    if (params.overall === "mean") value = nanMean(estimate);
    else if (params.overall === "max") value = Math.max(...estimate.filter((_, e) => observed[e]));
    else value = estimate.reduce((s, v, e) => (Number.isNaN(v) ? s : s + v * freq[e]), 0);
    const nObs = observed.filter(Boolean).length;
    const ownUnseen = own.some(Boolean) && !own.some((o, e) => o && observed[e]);
    overall.push({
      u, id: unit.id, overall: value, provisional: nObs < params.minElementsObserved || ownUnseen,
      elementsObserved: nObs, seasonsObserved: a.seasons, lastSeason: a.last, treasure: treasured.has(u),
      ownUnseen,
    });
    slots.set(u, ELEMENTS.map((element, e) => ({ element, lift: estimate[e], seasons: a.n[e], own: own[e] })));
  }

  const ranks = minRanks(overall.map((r) => r.overall));
  overall.forEach((r, i) => { r.rank = ranks[i]; r.tier = assignTier(r.overall, params.cuts); });
  overall.sort((a, b) => b.overall - a.overall || cmpId(a.id, b.id));

  for (const element of ELEMENTS) {
    const group = elements.filter((r) => r.element === element);
    const er = minRanks(group.map((r) => r.lift));
    group.forEach((r, i) => { r.rank = er[i]; });
  }
  for (const r of elements) r.tier = assignTier(r.lift, params.cuts);
  elements.sort((a, b) => ELEMENTS.indexOf(a.element) - ELEMENTS.indexOf(b.element)
    || (Number.isNaN(a.lift) ? 1 : 0) - (Number.isNaN(b.lift) ? 1 : 0)
    || (Number.isNaN(a.lift) ? 0 : b.lift - a.lift) || cmpId(a.id, b.id));

  return { counted, overall, overallByUnit: new Map(overall.map((r) => [r.u, r])), elements, slots, treasured };
}

// ---------------------------------------------------------------------------
// lifespans: when each unit was in use (analyze/tiers.py lifespans)

// Per unit out by ``moment``: the seasons that used it (usage >= minUsage), the first
// and last, and whether it is retired: idle for retireAfterDays since the end of the
// last one, through at least retireAfterOwnSeasons seasons weak to its own element
// (``missedOwn``). Such a gap between two seasons that used it is a return, and the run
// in use since the latest starts at ``runFrom``. The live season counts as ending at ``moment``.
export function lifespans(model, population, moment, params) {
  const window = params.retireAfterDays * DAY_MS;
  const need = params.retireAfterOwnSeasons;
  const out = new Map();
  for (const c of countedSeasons(population.summary, moment, params)) {
    const at = c.end != null && c.end <= moment ? c.end : moment;
    for (const r of population.tables.get(c.season).rows) {
      let a = out.get(r.u);
      if (!a) {
        a = { u: r.u, id: r.id, firstUsed: null, runFrom: null, lastUsed: null, seasonsUsed: 0, seasonsOut: 0,
          returns: 0, idleDays: NaN, missedOwn: 0, retired: false, runStart: null, lastEnd: null };
        out.set(r.u, a);
      }
      a.seasonsOut++;
      if (!(r.usageRate >= params.minUsage)) {
        if (a.lastUsed != null && r.elementMatch) a.missedOwn++;
        continue;
      }
      if (a.lastUsed == null) {
        a.firstUsed = c.season;
        a.runFrom = c.season;
        a.runStart = c.start;
      } else if (c.start != null && c.start - a.lastEnd >= window && a.missedOwn >= need) {
        a.returns++;
        a.runFrom = c.season;
        a.runStart = c.start;
      }
      a.lastUsed = c.season;
      a.lastEnd = at;
      a.seasonsUsed++;
      a.missedOwn = 0;
    }
  }
  for (const a of out.values()) {
    if (a.lastUsed == null) continue;
    a.idleDays = (moment - a.lastEnd) / DAY_MS;
    a.retired = a.idleDays >= params.retireAfterDays && a.missedOwn >= need;
  }
  return out;
}

// ---------------------------------------------------------------------------
// where every unit stood once each season was over (analyze/tiers.py tier_history)

export function tierHistory(model, population, params) {
  const history = new Map(); // season -> Map(unit -> {overall..., element...})
  for (const s of population.summary) {
    const moment = s.final ? s.end : s.collectedUntil;
    if (moment == null) continue;
    const treasured = new Set(s.rows.filter((r) => r.treasure).map((r) => r.u));
    const standing = standings(model, population, moment, params, treasured);
    const here = new Map();
    const elementOf = new Map(standing.elements.filter((r) => r.element === s.weak).map((r) => [r.u, r]));
    for (const r of s.rows) {
      const o = standing.overallByUnit.get(r.u);
      const e = elementOf.get(r.u);
      here.set(r.u, {
        overall: o ? o.overall : NaN,
        overallTier: o ? o.tier : "",
        provisional: o ? o.provisional : false,
        elementsObserved: o ? o.elementsObserved : null,
        elementLift: e ? e.lift : NaN,
        elementTier: e ? e.tier : "",
        elementSeasons: e ? e.seasons : null,
        counted: !!e,
      });
    }
    history.set(s.season, here);
  }
  return history;
}

// ---------------------------------------------------------------------------
// the views the page shows

export function treasuredAt(model, moment) {
  const set = new Set();
  model.units.forEach((unit, u) => { if (unit.treasure != null && unit.treasure <= moment) set.add(u); });
  return set;
}

// Solo Raid seasons around ``moment``: the one open (or suspended) then, the last
// closed and the next a notice has scheduled (timeline.py Timeline.at, less the
// season only enikk knows about - the site's data leaves those out).
export function seasonsAround(model, moment) {
  const status = (s) => {
    if (moment < s.periods[0][0]) return "upcoming";
    if (s.periods.some(([a, b]) => a <= moment && (b == null || moment <= b))) return "open";
    const end = s.periods[s.periods.length - 1][1];
    if (end != null && moment > end) return "closed";
    return "suspended";
  };
  const scheduled = model.seasons.filter((s) => s.periods.length);
  const current = scheduled.find((s) => ["open", "suspended"].includes(status(s))) || null;
  const closed = scheduled.filter((s) => status(s) === "closed");
  const upcoming = scheduled.filter((s) => status(s) === "upcoming");
  return {
    current: current ? { ...current, status: status(current) } : null,
    previous: closed.length ? closed[closed.length - 1] : null,
    next: upcoming.length ? upcoming[0] : null,
  };
}

export function viewAt(model, population, moment, params) {
  const standing = standings(model, population, moment, params, treasuredAt(model, moment));
  const final = standing.counted.filter((c) => !c.live).map((c) => c.season);
  const live = standing.counted.filter((c) => c.live).map((c) => c.season);
  const life = lifespans(model, population, moment, params);
  return { moment, standing, final, live, life, around: seasonsAround(model, moment) };
}

// One unit at ``moment``: its tier in each element it counts as and its overall
// tier (the slots it is made of), on the side of its treasure it was on then.
export function unitProfile(model, population, moment, params, u) {
  const view = viewAt(model, population, moment, params);
  const o = view.standing.overallByUnit.get(u);
  const counts = new Map();
  for (const r of view.standing.elements) counts.set(r.element, (counts.get(r.element) || 0) + 1);
  const unit = model.units[u];
  const treasured = unit.treasure != null && unit.treasure <= moment;
  return {
    view,
    treasured,
    overall: o || null,
    units: view.standing.overall.length,
    elements: view.standing.elements.filter((r) => r.u === u)
      .sort((a, b) => (a.source === "own" ? 0 : 1) - (b.source === "own" ? 0 : 1))
      .map((r) => ({ ...r, units: counts.get(r.element) || 0 })),
    slots: view.standing.slots.get(u) || null,
    members: unitElements(unit, treasured),
  };
}

// The seasons a unit has rows in, with its history there.
export function unitSeasons(population, history, u) {
  const out = [];
  for (const s of population.summary) {
    const r = s.byUnit.get(u);
    if (!r) continue;
    out.push({ season: s, row: r, hist: history.get(s.season)?.get(u) || null });
  }
  return out;
}
