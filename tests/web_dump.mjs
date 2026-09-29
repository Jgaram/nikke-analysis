// Runs the page's tier computation (web/js/model.js) under Node and prints what
// it makes of a built site's data, for tests/test_web.py to hold against the
// Python pipeline:
//
//   node tests/web_dump.mjs <site dir> ['{"topN": 10, ...}']
//
// The optional JSON overrides the defaults the site was built with.

import { readFileSync } from "node:fs";
import * as M from "../web/js/model.js";

const [, , siteDir, overrides] = process.argv;
const read = (name) => JSON.parse(readFileSync(`${siteDir}/data/${name}`, "utf-8"));
const model = read("model.json");
const decks = read("decks.json");

let params = M.defaultParams(model);
if (overrides) params = M.normalizeParams({ ...params, ...JSON.parse(overrides) });

const population = M.computeTables(model, decks, params);
const history = M.tierHistory(model, population, params);

const rows = [];
for (const s of population.summary) {
  for (const r of s.rows) {
    const h = history.get(s.season)?.get(r.u) ?? {};
    rows.push({
      season: r.season, unit_id: r.id, rankers: r.rankers, best_rank: r.bestRank, presence: r.presence,
      credit: r.credit, deck_share: r.deckShare, main_deck_rate: r.mainDeckRate,
      in_deck_1: r.inDeck[0], in_deck_2: r.inDeck[1], in_deck_3: r.inDeck[2], in_deck_4: r.inDeck[3],
      in_deck_5: r.inDeck[4], avg_deck: r.avgDeck, usage_rate: r.usageRate, usage_rank: r.usageRank,
      lift: r.lift, tier: M.assignTier(r.lift, params.cuts), treasure: r.treasure, element_match: r.elementMatch,
      overall: h.overall, overall_tier: h.overallTier, provisional: h.provisional,
      elements_observed: h.elementsObserved, element_lift: h.elementLift, element_tier: h.elementTier,
      element_seasons: h.elementSeasons, generality: h.generality,
    });
  }
}

const view = M.viewAt(model, population, model.asOf, params);
const overall = view.standing.overall.map((r) => {
  const g = view.generality.get(r.u);
  return {
    overall_rank: r.rank, unit_id: r.id, overall: r.overall, overall_tier: r.tier, provisional: r.provisional,
    elements_observed: r.elementsObserved, seasons_observed: r.seasonsObserved, last_season: r.lastSeason,
    treasure: r.treasure, generality: g.generality, generality_band: g.band,
  };
});
const elements = view.standing.elements.map((r) => ({
  element: r.element, element_rank: r.rank, unit_id: r.id, source: r.source, element_lift: r.lift,
  element_tier: r.tier, element_seasons: r.seasons, treasure: r.treasure,
}));
const lifeRows = (life) => [...life.values()].map((a) => ({
  unit_id: a.id, first_used: a.firstUsed, run_from: a.runFrom, last_used: a.lastUsed, seasons_used: a.seasonsUsed,
  seasons_out: a.seasonsOut, returns: a.returns, idle_days: a.idleDays, missed_own: a.missedOwn, retired: a.retired,
}));
const life = lifeRows(view.life);
// every unit's lifespan as each finished season ended, when most units have gaps behind them
const lives = population.summary.filter((s) => s.final)
  .flatMap((s) => lifeRows(M.lifespans(model, population, s.end, params)).map((r) => ({ season: s.season, ...r })));
const seasons = population.summary.map((s) => ({
  season: s.season, rankers: s.rankers, decks: s.decks, final: s.final, servers: s.servers.join(";"),
}));

process.stdout.write(JSON.stringify({
  params, rows, overall, elements, life, lives, seasons, final: view.final, live: view.live,
}));
