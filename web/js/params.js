// The parameter drawer, and the parameters in the URL (only what differs from config/tiers.yaml).

import { OVERALL_MODES } from "./model.js";
import { h, segmented, toggle, num } from "./ui.js";

const OVERALL_KO = { mean: "평균", frequency: "최근 빈도 가중", max: "가장 잘한 칸" };
const OVERALL_HINT = {
  mean: "보스 약점 다섯 칸의 평균. 최근 어떤 약점이 몰렸는지에 흔들리지 않는다.",
  frequency: "최근 보스 약점으로 자주 나온 칸일수록 크게 친 평균.",
  max: "다섯 칸 중 겪어 본 칸의 가장 큰 값.",
};
// The cuts one can move: every tier but the bottom one (F), whose floor is 0.
const cutLabels = (d) => d.cuts.slice(0, -1).map(([label]) => label);
// The most own-element seasons a unit may sit out before it counts as retired.
const RETIRE_OWN_MAX = 3;

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const sortedServers = (p) => [...p.servers].sort();

export function encodeParams(p, d) {
  const q = {};
  if (!same(sortedServers(p), sortedServers(d))) q.srv = p.servers.join(",");
  if (p.topN !== d.topN) q.top = String(p.topN);
  if (p.rankWeighting !== d.rankWeighting) q.w = p.rankWeighting;
  if (!same(p.cuts, d.cuts)) q.cuts = p.cuts.slice(0, cutLabels(d).length).map(([, v]) => v).join(",");
  if (p.halfLifeDays !== d.halfLifeDays) q.hl = String(p.halfLifeDays);
  if (p.priorStrength !== d.priorStrength) q.k = String(p.priorStrength);
  if (p.overall !== d.overall) q.ov = p.overall;
  if (p.minElementsObserved !== d.minElementsObserved) q.min = String(p.minElementsObserved);
  if (p.includeLive !== d.includeLive) q.live = p.includeLive ? "1" : "0";
  if (p.minUsage !== d.minUsage) q.use = String(Math.round(p.minUsage * 100));
  if (p.retireAfterDays !== d.retireAfterDays) q.ret = String(p.retireAfterDays);
  if (p.retireAfterOwnSeasons !== d.retireAfterOwnSeasons) q.rown = String(p.retireAfterOwnSeasons);
  return q;
}

const number = (text, lo, hi) => {
  const v = Number(text);
  return text != null && text !== "" && Number.isFinite(v) && v >= lo && v <= hi ? v : null;
};

export function decodeParams(q, d, model) {
  const p = { ...d, cuts: d.cuts.map((c) => [...c]), servers: [...d.servers] };
  if (q.has("srv")) {
    const kept = q.get("srv").split(",").map((s) => s.trim().toUpperCase()).filter((s) => model.servers.includes(s));
    if (kept.length) p.servers = model.servers.filter((s) => kept.includes(s));
  }
  p.topN = Math.round(number(q.get("top"), 1, 50) ?? d.topN);
  if (["dcg", "uniform"].includes(q.get("w"))) p.rankWeighting = q.get("w");
  if (q.has("cuts")) {
    const labels = cutLabels(d);
    const values = q.get("cuts").split(",").map((v) => number(v, 0, 10));
    if (values.length === labels.length && values.every((v) => v != null) && descending(values)) {
      p.cuts = [...labels.map((l, i) => [l, values[i]]), ...d.cuts.slice(labels.length)];
    }
  }
  p.halfLifeDays = number(q.get("hl"), 0, 3650) ?? d.halfLifeDays;
  p.priorStrength = number(q.get("k"), 0, 50) ?? d.priorStrength;
  if (OVERALL_MODES.includes(q.get("ov"))) p.overall = q.get("ov");
  p.minElementsObserved = Math.round(number(q.get("min"), 1, 5) ?? d.minElementsObserved);
  if (q.has("live")) p.includeLive = q.get("live") === "1";
  const use = number(q.get("use"), 1, 100);
  if (use != null) p.minUsage = Math.round(use) / 100;
  const ret = number(q.get("ret"), 0, 3650);
  if (ret != null) p.retireAfterDays = Math.round(ret);
  const own = number(q.get("rown"), 0, RETIRE_OWN_MAX);
  if (own != null) p.retireAfterOwnSeasons = Math.round(own);
  return p;
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
  if (p.halfLifeDays !== d.halfLifeDays) out.push("반감기");
  if (p.priorStrength !== d.priorStrength) out.push("축소");
  if (p.overall !== d.overall) out.push("종합 방식");
  if (p.minElementsObserved !== d.minElementsObserved) out.push("잠정 기준");
  if (p.includeLive !== d.includeLive) out.push("진행 중 시즌");
  if (p.minUsage !== d.minUsage) out.push("쓰인 기준");
  if (p.retireAfterDays !== d.retireAfterDays || p.retireAfterOwnSeasons !== d.retireAfterOwnSeasons) out.push("은퇴 기준");
  return out;
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

  const cutInputs = h("div", { class: "cuts" });
  const cutError = h("p", { class: "hint error", hidden: true }, "위 티어일수록 커야 하고 0 이상이어야 합니다.");
  const readCuts = () => [...cutInputs.querySelectorAll("input")].map((i) => Number(i.value));
  const labels = cutLabels(d);
  const floor = d.cuts[d.cuts.length - 1][0];
  labels.forEach((label, i) => {
    cutInputs.append(h("label", { class: "cut", dataset: { tier: label } },
      h("span", { class: "tb", dataset: { tier: label } }, h("b", null, label)),
      h("span", { class: "cut-ge", "aria-hidden": "true" }, "≥"),
      h("input", {
        type: "number", min: 0, max: 10, step: 0.01, value: p.cuts[i][1], inputMode: "decimal",
        "aria-label": `${label} 티어 최소 기여도`,
        onchange: () => {
          const values = readCuts();
          const ok = values.every((v) => Number.isFinite(v)) && descending(values);
          cutError.hidden = ok;
          if (ok) app.setParams({ cuts: [...labels.map((l, k) => [l, values[k]]), ...p.cuts.slice(labels.length)] });
        },
      })));
  });

  body.replaceChildren(
    h("section", { class: "psec" },
      h("h3", null, "표본", h("small", null, "기여도를 셀 랭커")),
      field("서버", servers, "여섯 서버는 보스·패치가 같아 기본은 전부 합칩니다. 시즌 5·6은 GLOBAL·JP·NA·SEA 뿐입니다."),
      field("서버마다 상위", range({
        min: 1, max: 50, step: 1, value: p.topN, label: "서버마다 상위 몇 위까지", format: (v) => `${v}위`,
        onInput: (v) => later({ topN: v }), onCommit: (v) => { clearTimeout(populationTimer); app.setParams({ topN: v }); },
      }), "enikk 는 서버마다 50위까지 줍니다."),
      field("순위 가중", segmented([
        { value: "dcg", label: "상위일수록 크게" }, { value: "uniform", label: "모두 같게" },
      ], p.rankWeighting, (v) => { app.setParams({ rankWeighting: v }); buildParams(app, body); }, { label: "순위 가중" }),
      "상위일수록 크게 = 1 / log₂(순위 + 1): 1위 1.00 · 10위 0.29 · 50위 0.18")),
    h("section", { class: "psec" },
      h("h3", null, "티어 컷", h("small", null, "기여도 기준 · 시즌·속성·종합 공통")),
      cutInputs, cutError,
      h("p", { class: "hint" }, "기여도 1.0 = 한 사람이 쓰는 25명(5덱 × 5명)이 대미지를 똑같이 나눴을 때의 몫. "
        + `1.5 = 그 1.5배, 0 = 아무도 안 씀. 그 아래는 ${floor}(티어표에서 접어 둠).`)),
    h("section", { class: "psec" },
      h("h3", null, "속성·종합 티어", h("small", null, "여러 시즌을 하나로")),
      field("최근성 반감기", range({
        min: 0, max: 720, step: 30, value: p.halfLifeDays, label: "반감기 (일)",
        format: (v) => (v > 0 ? `${v}일` : "끔"),
        onInput: (v) => later({ halfLifeDays: v }), onCommit: (v) => { clearTimeout(populationTimer); app.setParams({ halfLifeDays: v }); },
      }), "이만큼 지난 시즌은 절반만 칩니다. 끔(0) = 모든 시즌을 똑같이."),
      field("종합 티어 방식", segmented(OVERALL_MODES.map((m) => ({ value: m, label: OVERALL_KO[m] })), p.overall,
        (v) => { app.setParams({ overall: v }); buildParams(app, body); }, { label: "종합 티어 방식" }),
      OVERALL_HINT[p.overall]),
      field("축소 세기", range({
        min: 0, max: 10, step: 0.5, value: p.priorStrength, label: "축소 세기", format: (v) => (v > 0 ? num(v, 1) : "끔"),
        onInput: (v) => later({ priorStrength: v }), onCommit: (v) => { clearTimeout(populationTimer); app.setParams({ priorStrength: v }); },
      }), "겪은 시즌이 적은 칸을 그 니케의 전체 평균 쪽으로 당기는 가상 시즌 수. 끔 = 겪은 시즌을 그대로 믿음."),
      field("잠정 기준", segmented([1, 2, 3, 4, 5].map((n) => ({ value: n, label: `${n}가지` })), p.minElementsObserved,
        (v) => { app.setParams({ minElementsObserved: v }); buildParams(app, body); }, { label: "잠정 기준" }),
      "겪은 보스 약점이 이보다 적거나 자기 속성 시즌을 아직 못 겪었으면 종합 티어가 잠정(*)."),
      field("진행 중 시즌", toggle("지금까지 수집분으로 포함", p.includeLive, (v) => app.setParams({ includeLive: v })),
        "진행 중인 시즌의 순위도 속성·종합 티어와 수명에 잠정으로 넣습니다. 끄면 끝난 시즌만.")),
    h("section", { class: "psec" },
      h("h3", null, "수명", h("small", null, "언제부터 쓰였고 아직 쓰이나 · 티어와 별개")),
      field("쓰인 시즌", range({
        min: 1, max: 50, step: 1, value: Math.round(p.minUsage * 100), label: "쓰인 시즌으로 칠 최소 사용률 (%)",
        format: (v) => `사용 ${v}% 이상`,
        onCommit: (v) => app.setParams({ minUsage: v / 100 }),
      }), "상위 랭커의 이만큼 이상이 쓴 시즌을 그 니케가 쓰인 시즌으로 칩니다."),
      field("은퇴 공백", range({
        min: 0, max: 730, step: 5, value: p.retireAfterDays, label: "은퇴로 볼 공백 (일)",
        format: (v) => `${v}일 공백`,
        onCommit: (v) => app.setParams({ retireAfterDays: v }),
      }), "마지막으로 쓰인 시즌이 끝나고 이만큼 안 쓰였고 아래 자기 속성 시즌도 놓쳤으면 은퇴, 그 뒤 다시 쓰이면 복귀."),
      field("놓친 자기 속성 시즌", segmented([0, 1, 2, 3].map((n) => ({ value: n, label: n ? `${n}번` : "안 봄" })),
        p.retireAfterOwnSeasons, (v) => { app.setParams({ retireAfterOwnSeasons: v }); buildParams(app, body); },
        { label: "은퇴로 볼 놓친 자기 속성 시즌 수" }),
      "그 공백 동안 자기 속성이 약점인 시즌이 이만큼 지나가도록 안 쓰여야 은퇴. 같은 약점이 1년 만에 돌아오기도 해서, "
        + "자기 속성 시즌이 아직 안 온 속성 특화 니케는 공백이 길어도 현역으로 둡니다. 안 봄 = 공백만으로.")),
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
