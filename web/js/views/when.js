// The time axis: the Solo Raid seasons left to right, the same on every view. A season
// chosen reads everything as it stood once that season was over; none chosen reads it now
// (the newest season's chip is lit). Each chip: number, weakness, boss, the day it ended;
// a flag over it for a half anniversary (the raid that counts for it) or a new year.

import { h, elementIcon, ELEMENT_KO, kst, noonKst, shortDay } from "../ui.js";

const DAY_MS = 86400000;
const RAID_AFTER_DAYS = 21; // an anniversary's raid opens within three weeks of the day, if not on it

// Every half anniversary of the launch - 0.5주년, 1주년, 1.5주년, ... - as {label, season}:
// the raid open on the anniversary, else the first to open in the three weeks after it.
// Up to the last season with a start; one with no such raid is left out.
export function anniversaries(launch, seasons) {
  const t = kst(launch);
  const [y, m, d] = [Number(t.y), Number(t.m), Number(t.d)];
  const dated = seasons.filter((s) => s.start != null).sort((a, b) => a.start - b.start);
  if (!dated.length) return [];
  const last = dated[dated.length - 1].start;
  const out = [];
  for (let half = 1; half <= 200; half++) {
    const months = m - 1 + 6 * half;
    const year = y + Math.floor(months / 12), month = (months % 12) + 1;
    const days = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const noon = noonKst(`${year}-${String(month).padStart(2, "0")}-${String(Math.min(d, days)).padStart(2, "0")}`);
    if (noon > last) break;
    // a season with no end yet is open for three weeks at most
    const raid = dated.find((s) => s.start <= noon && (s.end ?? s.start + RAID_AFTER_DAYS * DAY_MS) >= noon)
      || dated.find((s) => s.start > noon && s.start <= noon + RAID_AFTER_DAYS * DAY_MS);
    if (raid) out.push({ label: half % 2 ? `${(half - 1) / 2}.5주년` : `${half / 2}주년`, season: raid.season });
  }
  return out;
}

// The seasons ``weak`` (a weakness) picks out; the others stay on the axis, faded.
export function timeStrip(app, { weak = null, compact = false } = {}) {
  const { model, state } = app;
  const pop = app.population();
  const latest = app.latestSeason();
  const selected = state.season ?? latest;
  const marks = new Map(anniversaries(model.launch, model.seasons).map((a) => [a.season, a.label]));
  const href = (n) => app.link({ season: n === latest ? null : n });
  let year = null;
  const chips = model.seasons.map((s) => {
    const entry = pop.tables.get(s.season);
    const boss = s.bossKo || s.bossEn || "?";
    const end = s.end ?? s.start;
    const y = end != null ? kst(end).y : null;
    const flags = [];
    if (y != null && y !== year) { flags.push(h("span", { class: "flag year" }, y)); year = y; }
    if (marks.has(s.season)) flags.push(h("span", { class: "flag ann" }, marks.get(s.season)));
    const on = s.season === selected;
    const live = entry && !entry.final;
    const title = [`시즌 ${s.season} · ${boss} · 약점 ${ELEMENT_KO[s.weak] || "?"}`,
      s.start != null ? `${shortDay(s.start)} ~ ${s.end != null ? shortDay(s.end) : "?"}` : "일정 미정",
      marks.get(s.season), live ? "진행 중" : null, !entry ? "랭킹 없음" : null].filter(Boolean).join(" · ");
    const body = [
      flags.length ? h("span", { class: "flags" }, flags) : null,
      h("span", { class: "schip-top" }, h("span", { class: "schip-n" }, s.season), elementIcon(s.weak, 12, { title: "" })),
      s.bossImage ? h("img", { class: "schip-boss", src: `icons/bosses/${s.bossImage}.webp`, alt: "", width: 36, height: 36, loading: "lazy", decoding: "async" })
        : h("span", { class: "schip-boss none", "aria-hidden": "true" }),
      h("span", { class: "schip-d" }, end != null ? shortDay(end) : "–"),
    ];
    const cls = ["schip", on && "on", live && "live", weak && !on && s.weak !== weak && "faded", flags.some((f) => f.classList.contains("year")) && "new-year"];
    if (!entry) return h("span", { class: [...cls, "off"], title, "aria-disabled": "true" }, body);
    return h("a", { class: cls, href: href(s.season), title, "aria-current": on ? "true" : null, "aria-label": title }, body);
  });

  // The chosen season goes to the middle: the strip slides there from where the one on
  // screen was, or starts there when the view is just opened.
  const list = h("div", { class: "strip-list" }, chips);
  const before = document.querySelector(".strip-list")?.scrollLeft;
  requestAnimationFrame(() => {
    const on = list.querySelector(".schip.on");
    if (!on) return;
    const left = on.offsetLeft - (list.clientWidth - on.offsetWidth) / 2;
    if (before == null) { list.scrollLeft = left; return; }
    list.scrollLeft = before;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    list.scrollTo({ left, behavior: still ? "auto" : "smooth" });
  });

  // The steps go season by season, or with a weakness from one of its seasons to the next.
  const steps = model.seasons.filter((s) => pop.tables.has(s.season) && (!weak || s.weak === weak || s.season === selected));
  const index = steps.findIndex((s) => s.season === selected);
  const what = weak ? `${ELEMENT_KO[weak]} 약점 시즌` : "시즌";
  const step = (dir) => {
    const target = index < 0 ? null : steps[index + dir];
    const label = `${dir < 0 ? "이전" : "다음"} ${what}`;
    return target ? h("a", { class: "strip-step", href: href(target.season), "aria-label": label, title: label }, dir < 0 ? "‹" : "›")
      : h("span", { class: "strip-step off", "aria-hidden": "true" }, dir < 0 ? "‹" : "›");
  };
  return h("nav", { class: ["strip", compact && "compact"], "aria-label": "기준 시즌" }, step(-1), list, step(1));
}

// The moment the views stand at, in words: "지금", or the chosen season over (or collected so far).
export function whenLabel(app, moment) {
  const s = app.state.season != null ? app.model.bySeason.get(app.state.season) : null;
  if (!s) return "지금";
  const entry = app.population().tables.get(s.season);
  const t = kst(moment);
  const at = entry && !entry.final ? `${shortDay(entry.collectedOn)} 수집분까지` : `끝난 ${t.y}-${t.m}-${t.d}`;
  return `S${s.season} ${s.bossKo || s.bossEn || "?"} ${at}`;
}

// That, and the seasons that counted, in one line.
export function whenLine(app, view) {
  const live = view.live.length ? ` + 진행 중 ${view.live.join("·")}(잠정)` : "";
  const counted = view.final.length ? `시즌 ${view.final[0]}–${view.final[view.final.length - 1]}${live}` : `끝난 시즌 없음${live}`;
  return h("p", { class: "when" }, h("b", null, whenLabel(app, view.moment)), " 기준",
    h("span", { class: "sep" }), h("span", { class: "muted" }, counted));
}
