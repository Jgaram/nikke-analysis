// The parameter drawer, and the parameters in the URL (only what differs from config/tiers.yaml).

import { OVERALL_MODES, GENERALITY_MAX } from "./model.js";
import { h, segmented, toggle, num } from "./ui.js";
import { retiredText } from "./views/common.js";

const OVERALL_KO = { mean: "평균", frequency: "최근 빈도 가중", max: "가장 잘한 칸" };
const OVERALL_HINT = {
  mean: "보스 약점 다섯 칸의 평균. 최근 어떤 약점이 몰렸는지에 흔들리지 않는다.",
  frequency: "최근 보스 약점으로 자주 나온 칸일수록 크게 친 평균.",
  max: "다섯 칸 중 겪어 본 칸의 가장 큰 값.",
};
// The cuts one can move: every tier but the bottom one (F), whose floor is 0.
const cutLabels = (d) => d.cuts.slice(0, -1).map(([label]) => label);
// The choices offered for the own-element seasons a unit may sit out before it counts as
// retired, and for the other-element seasons that mean it left them - more when the defaults
// or the address ask for more.
const RETIRE_OWN_MAX = 3;
const upTo = (max, ...values) => Math.max(max, ...values.map((v) => Math.round(v)));

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const range1 = (n) => Array.from({ length: n }, (_, i) => i + 1);
const sortedServers = (p) => [...p.servers].sort();

export function encodeParams(p, d) {
  const q = {};
  if (!same(sortedServers(p), sortedServers(d))) q.srv = p.servers.join(",");
  if (p.topN !== d.topN) q.top = String(p.topN);
  if (p.rankWeighting !== d.rankWeighting) q.w = p.rankWeighting;
  if (!same(p.cuts, d.cuts)) q.cuts = p.cuts.slice(0, cutLabels(d).length).map(([, v]) => v).join(",");
  if (!same(p.overallCuts, d.overallCuts)) q.ocuts = p.overallCuts.slice(0, cutLabels(d).length).map(([, v]) => v).join(",");
  if (p.halfLifeDays !== d.halfLifeDays) q.hl = String(p.halfLifeDays);
  if (p.priorStrength !== d.priorStrength) q.k = String(p.priorStrength);
  if (p.overall !== d.overall) q.ov = p.overall;
  if (p.minElementsObserved !== d.minElementsObserved) q.min = String(p.minElementsObserved);
  if (p.includeLive !== d.includeLive) q.live = p.includeLive ? "1" : "0";
  if (p.minTier !== d.minTier) q.use = p.minTier;
  if (p.retireAfterDays !== d.retireAfterDays) q.ret = String(p.retireAfterDays);
  if (p.retireAfterOwnSeasons !== d.retireAfterOwnSeasons) q.rown = String(p.retireAfterOwnSeasons);
  if (!same(p.generalityBands, d.generalityBands)) q.band = p.generalityBands.join(",");
  return q;
}

const number = (text, lo, hi) => {
  const v = Number(text);
  return text != null && text !== "" && Number.isFinite(v) && v >= lo && v <= hi ? v : null;
};

export function decodeParams(q, d, model) {
  const p = { ...d, cuts: d.cuts.map((c) => [...c]), overallCuts: d.overallCuts.map((c) => [...c]), servers: [...d.servers] };
  if (q.has("srv")) {
    const kept = q.get("srv").split(",").map((s) => s.trim().toUpperCase()).filter((s) => model.servers.includes(s));
    if (kept.length) p.servers = model.servers.filter((s) => kept.includes(s));
  }
  p.topN = Math.round(number(q.get("top"), 1, 50) ?? d.topN);
  if (["dcg", "uniform"].includes(q.get("w"))) p.rankWeighting = q.get("w");
  for (const [key, name] of [["cuts", "cuts"], ["ocuts", "overallCuts"]]) {
    if (!q.has(key)) continue;
    const labels = cutLabels(d);
    const values = q.get(key).split(",").map((v) => number(v, 0, 10));
    if (values.length === labels.length && values.every((v) => v != null) && descending(values)) {
      p[name] = [...labels.map((l, i) => [l, values[i]]), ...d[name].slice(labels.length)];
    }
  }
  p.halfLifeDays = number(q.get("hl"), 0, 3650) ?? d.halfLifeDays;
  p.priorStrength = number(q.get("k"), 0, 50) ?? d.priorStrength;
  if (OVERALL_MODES.includes(q.get("ov"))) p.overall = q.get("ov");
  p.minElementsObserved = Math.round(number(q.get("min"), 1, 5) ?? d.minElementsObserved);
  if (q.has("live")) p.includeLive = q.get("live") === "1";
  if (tierChoices(d).includes(q.get("use"))) p.minTier = q.get("use");
  const ret = number(q.get("ret"), 0, 3650);
  if (ret != null) p.retireAfterDays = Math.round(ret);
  const own = number(q.get("rown"), 0, 50);
  if (own != null) p.retireAfterOwnSeasons = Math.round(own);
  if (q.has("band")) {
    const bands = q.get("band").split(",").map((v) => number(v, 0, GENERALITY_MAX));
    if (bands.length === 2 && bands.every((v) => v != null) && bands[0] <= bands[1]) p.generalityBands = bands;
  }
  return p;
}

// The season tiers that can count as fielded: every one above the bottom (F) - or the one
// the defaults name, should that be the bottom.
function tierChoices(d) {
  const labels = cutLabels(d);
  return labels.includes(d.minTier) ? labels : [...labels, d.minTier];
}

function descending(values) {
  return values.every((v, i) => i === 0 || v < values[i - 1]) && values[values.length - 1] >= 0;
}

export function changedParams(p, d) {
  const out = [];
  if (!same(sortedServers(p), sortedServers(d))) out.push("서버");
  if (p.topN !== d.topN) out.push("상위 N위");
  if (p.rankWeighting !== d.rankWeighting) out.push("순위 가중");
  if (!same(p.cuts, d.cuts)) out.push("티어 컷");
  if (!same(p.overallCuts, d.overallCuts)) out.push("종합 티어 컷");
  if (p.halfLifeDays !== d.halfLifeDays) out.push("반감기");
  if (p.priorStrength !== d.priorStrength) out.push("축소");
  if (p.overall !== d.overall) out.push("종합 방식");
  if (p.minElementsObserved !== d.minElementsObserved) out.push("잠정 기준");
  if (p.includeLive !== d.includeLive) out.push("진행 중 시즌");
  if (p.minTier !== d.minTier) out.push("쓰인 기준");
  if (p.retireAfterDays !== d.retireAfterDays || p.retireAfterOwnSeasons !== d.retireAfterOwnSeasons) out.push("은퇴 기준");
  if (!same(p.generalityBands, d.generalityBands)) out.push("범용도 띠");
  return out;
}

// The page's "숫자 읽는 법", where it quotes the parameters in force.
export function renderHowto(p) {
  const put = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
  put("howto-weight", p.rankWeighting === "uniform" ? "순위와 상관없이 똑같이 쳐서" : "순위가 높을수록 조금 크게 쳐서");
  put("howto-recent", p.halfLifeDays > 0 ? `최근일수록 크게 친(${p.halfLifeDays}일 지난 시즌은 절반)` : "시즌마다 똑같이 친");
  put("howto-used", `${p.minTier} 이상`);
  put("howto-retired", retiredText(p));
}

// ---------------------------------------------------------------------------

function field(label, control, hint, attrs = {}) {
  return h("div", { class: ["field", attrs.class] },
    h("div", { class: "field-label" }, label),
    control,
    hint ? h("p", { class: "hint" }, hint) : null);
}

function range({ min, max, step, value, format, onInput, onCommit, label }) {
  const out = h("output", { class: "range-out" }, format(value));
  const input = h("input", {
    type: "range", min, max, step, value, "aria-label": label,
    oninput: (e) => { out.textContent = format(Number(e.target.value)); onInput?.(Number(e.target.value)); },
    onchange: (e) => onCommit(Number(e.target.value)),
  });
  return h("div", { class: "range" }, input, out);
}

let populationTimer = 0;

export function buildParams(app, body) {
  const p = app.state.params;
  const d = app.defaults;
  const model = app.model;
  const later = (patch) => {
    clearTimeout(populationTimer);
    populationTimer = setTimeout(() => app.setParams(patch), 250);
  };

  const servers = h("div", { class: "chips" }, model.servers.map((s) => {
    const on = p.servers.includes(s);
    return h("button", {
      type: "button", class: "chip", "aria-pressed": String(on), title: model.serverNames[s],
      onclick: () => {
        const next = on ? p.servers.filter((x) => x !== s) : model.servers.filter((x) => x === s || p.servers.includes(x));
        if (!next.length) return;
        app.setParams({ servers: next });
        buildParams(app, body);
      },
    }, h("b", null, s), h("span", null, model.serverNames[s]));
  }));

  const cutError = h("p", { class: "hint error", hidden: true }, "위 티어일수록 커야 하고 0 이상이어야 합니다.");
  const bandError = h("p", { class: "hint error", hidden: true },
    `0 이상 ${GENERALITY_MAX} 이하, 왼쪽이 오른쪽보다 크지 않게.`);
  // The two generality bands: 특화 below the first, 범용 from the second.
  const bandRow = () => {
    const row = h("div", { class: "cuts" });
    const read = () => [...row.querySelectorAll("input")].map((i) => Number(i.value));
    [["속성 우선", 0], ["범용", 1]].forEach(([label, i]) => {
      row.append(h("label", { class: "cut" },
        h("span", { class: "band-label" }, label), h("span", { class: "cut-ge", "aria-hidden": "true" }, "≥"),
        h("input", {
          type: "number", min: 0, max: GENERALITY_MAX, step: 0.05, value: p.generalityBands[i], inputMode: "decimal",
          "aria-label": `${label} 띠의 최소 범용도`,
          onchange: () => {
            const values = read();
            const ok = values.every((v) => Number.isFinite(v) && v >= 0 && v <= GENERALITY_MAX) && values[0] <= values[1];
            bandError.hidden = ok;
            if (ok) app.setParams({ generalityBands: values });
          },
        })));
    });
    return row;
  };
  const labels = cutLabels(d);
  const floor = d.cuts[d.cuts.length - 1][0];
  // One row of cut inputs for ``name`` (the season/element cuts, or the overall's).
  const cutRow = (name, what) => {
    const row = h("div", { class: "cuts" });
    const read = () => [...row.querySelectorAll("input")].map((i) => Number(i.value));
    labels.forEach((label, i) => {
      row.append(h("label", { class: "cut", dataset: { tier: label } },
        h("span", { class: "tb", dataset: { tier: label } }, h("b", null, label)),
        h("span", { class: "cut-ge", "aria-hidden": "true" }, "≥"),
        h("input", {
          type: "number", min: 0, max: 10, step: 0.005, value: p[name][i][1], inputMode: "decimal",
          "aria-label": `${label} 티어 최소 ${what}`,
          onchange: () => {
            const values = read();
            const ok = values.every((v) => Number.isFinite(v)) && descending(values);
            cutError.hidden = ok;
            if (ok) app.setParams({ [name]: [...labels.map((l, k) => [l, values[k]]), ...p[name].slice(labels.length)] });
          },
        })));
    });
    return row;
  };

  body.replaceChildren(
    h("section", { class: "psec" },
      h("h3", null, "표본", h("small", null, "기여도를 셀 랭커")),
      field("서버", servers, "서버들은 보스·패치가 같아 기본은 전부 합칩니다. 랭킹이 없는 서버가 있는 시즌도 있습니다."),
      field("서버마다 상위", range({
        min: 1, max: 50, step: 1, value: p.topN, label: "서버마다 상위 몇 위까지", format: (v) => `${v}위`,
        onInput: (v) => later({ topN: v }), onCommit: (v) => { clearTimeout(populationTimer); app.setParams({ topN: v }); },
      }), "enikk 가 주는 순위까지 고를 수 있습니다."),
      field("순위 가중", segmented([
        { value: "dcg", label: "상위일수록 크게" }, { value: "uniform", label: "모두 같게" },
      ], p.rankWeighting, (v) => { app.setParams({ rankWeighting: v }); buildParams(app, body); }, { label: "순위 가중" }),
      "상위일수록 크게 = 1 / log₂(순위 + 1). 모두 같게 = 순위와 상관없이 1.")),
    h("section", { class: "psec" },
      h("h3", null, "티어 컷", h("small", null, "기여도 기준")),
      field("시즌·속성 티어", cutRow("cuts", "기여도")),
      field("종합 티어", cutRow("overallCuts", "종합 값"),
        "종합은 다섯 칸을 합친 값이라 한 속성만 맡는 니케는 속성 기여도보다 훨씬 낮습니다. 그래서 컷이 따로이고 낮습니다. "
        + "순위는 그대로이고 티어 이름만 바뀝니다."),
      cutError,
      h("p", { class: "hint" }, "기여도 1.0 = 한 사람이 쓰는 25명(5덱 × 5명)이 대미지를 똑같이 나눴을 때의 몫. "
        + `0 = 아무도 안 씀. 그 아래는 ${floor}(티어표에서 접어 둠).`)),
    h("section", { class: "psec" },
      h("h3", null, "속성·종합 티어", h("small", null, "여러 시즌을 하나로")),
      field("최근성 반감기", range({
        min: 0, max: upTo(720, d.halfLifeDays, p.halfLifeDays), step: 30, value: p.halfLifeDays, label: "반감기 (일)",
        format: (v) => (v > 0 ? `${v}일` : "끔"),
        onInput: (v) => later({ halfLifeDays: v }), onCommit: (v) => { clearTimeout(populationTimer); app.setParams({ halfLifeDays: v }); },
      }), "이만큼 지난 시즌은 절반만 칩니다. 끔(0) = 모든 시즌을 똑같이."),
      field("종합 티어 방식", segmented(OVERALL_MODES.map((m) => ({ value: m, label: OVERALL_KO[m] })), p.overall,
        (v) => { app.setParams({ overall: v }); buildParams(app, body); }, { label: "종합 티어 방식" }),
      OVERALL_HINT[p.overall]),
      field("축소 세기", range({
        min: 0, max: upTo(10, d.priorStrength, p.priorStrength), step: 0.5, value: p.priorStrength, label: "축소 세기",
        format: (v) => (v > 0 ? num(v, 1) : "끔"),
        onInput: (v) => later({ priorStrength: v }), onCommit: (v) => { clearTimeout(populationTimer); app.setParams({ priorStrength: v }); },
      }), "겪은 시즌이 적은 칸을 그 니케의 전체 평균 쪽으로 당기는 가상 시즌 수. 끔 = 겪은 시즌을 그대로 믿음."),
      field("잠정 기준", segmented([1, 2, 3, 4, 5].map((n) => ({ value: n, label: `${n}가지` })), p.minElementsObserved,
        (v) => { app.setParams({ minElementsObserved: v }); buildParams(app, body); }, { label: "잠정 기준" }),
      "겪은 보스 약점이 이보다 적거나 자기 속성 시즌을 아직 못 겪었으면 종합 티어가 잠정(*)."),
      field("진행 중 시즌", toggle("지금까지 수집분으로 포함", p.includeLive, (v) => app.setParams({ includeLive: v })),
        "진행 중인 시즌의 순위도 속성·종합 티어와 수명에 잠정으로 넣습니다. 끄면 끝난 시즌만.")),
    h("section", { class: "psec" },
      h("h3", null, "수명", h("small", null, "언제부터 쓰였고 아직 쓰이나 · 시즌 티어로")),
      field("쓰인 시즌", segmented(tierChoices(d).map((label) => ({ value: label, label: `${label} 이상` })), p.minTier,
        (v) => { app.setParams({ minTier: v }); buildParams(app, body); }, { label: "쓰인 시즌으로 칠 시즌 티어" }),
      "그 시즌의 시즌 티어가 이 티어 이상이면 그 니케가 쓰인 시즌입니다(컷은 위 시즌·속성 티어). 속성·종합 티어는 "
        + "지난 시즌을 기억해서 은퇴를 늦게 알아채므로 시즌 티어로 봅니다."),
      field("은퇴 공백", range({
        min: 0, max: upTo(730, d.retireAfterDays, p.retireAfterDays), step: 5, value: p.retireAfterDays,
        label: "은퇴로 볼 공백 (일)",
        format: (v) => `${v}일 공백`,
        onCommit: (v) => app.setParams({ retireAfterDays: v }),
      }), "마지막으로 쓰인 시즌이 끝나고 이만큼 안 쓰였고 아래 자기 속성 시즌도 놓쳤으면 은퇴, 그 뒤 다시 쓰이면 복귀."),
      field("놓친 자기 속성 시즌", segmented([0, ...range1(upTo(RETIRE_OWN_MAX, d.retireAfterOwnSeasons, p.retireAfterOwnSeasons))]
        .map((n) => ({ value: n, label: n ? `${n}번` : "안 봄" })),
        p.retireAfterOwnSeasons, (v) => { app.setParams({ retireAfterOwnSeasons: v }); buildParams(app, body); },
        { label: "은퇴로 볼 놓친 자기 속성 시즌 수" }),
      "그 공백 동안 자기 속성이 약점인 시즌이 이만큼 지나가도록 안 쓰여야 은퇴. 같은 약점이 오래 걸려 돌아오기도 해서, "
        + "자기 속성 시즌이 아직 안 온 속성 특화 니케는 공백이 길어도 현역으로 둡니다. 안 봄 = 공백만으로.")),
    h("section", { class: "psec" },
      h("h3", null, "범용도", h("small", null, "약점을 얼마나 타나 · 티어와 별개")),
      field("범용도 띠", bandRow(), "범용도 = 2 × 다른 속성 칸 평균 ÷ (자기 속성 칸 + 다른 속성 칸 평균). 0 = 약점이 자기 "
        + `속성일 때만 쓰임, 1 = 약점과 무관, ${GENERALITY_MAX} = 약점이 다른 속성일 때만 쓰임. `
        + "이 두 값으로 특화 · 속성 우선 · 범용을 나눕니다."),
      bandError),
  );

  renderParamsFoot(app, () => buildParams(app, body));
}

// The drawer's footer: what differs from the defaults, a reset and a link to this view.
export function renderParamsFoot(app, rebuild = null) {
  const changed = changedParams(app.state.params, app.defaults);
  const footer = document.getElementById("params-foot");
  footer.replaceChildren(
    h("span", { class: "muted small" }, changed.length ? `바뀐 인자: ${changed.join(" · ")}` : "config/tiers.yaml 기본값"),
    h("div", { class: "foot-actions" },
      h("button", { type: "button", class: "btn ghost", disabled: !changed.length,
        onclick: () => { app.resetParams(); rebuild?.(); } }, "기본값으로"),
      h("button", { type: "button", class: "btn", onclick: async (e) => {
        const button = e.currentTarget;
        try {
          await navigator.clipboard.writeText(location.href);
          button.textContent = "복사됨";
        } catch {
          button.textContent = "주소창을 복사하세요";
        }
        setTimeout(() => { button.textContent = "링크 복사"; }, 1600);
      } }, "링크 복사")),
  );
}
