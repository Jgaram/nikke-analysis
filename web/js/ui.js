// Small DOM helpers, labels and formatting shared by the views.
//
// Every string from the data goes into the page as text (h() makes text
// nodes), never as markup.

export const ELEMENT_KO = { Fire: "작열", Water: "수냉", Wind: "풍압", Iron: "철갑", Electric: "전격" };
export const CLASS_KO = { Attacker: "화력형", Supporter: "지원형", Defender: "방어형" };
export const BURSTS = ["I", "II", "III"];
export const TIERS = ["SS", "S", "A", "B", "C", "D"];

const SVG_NS = "http://www.w3.org/2000/svg";

function append(node, child) {
  if (child == null || child === false) return;
  if (Array.isArray(child)) { for (const c of child) append(node, c); return; }
  node.append(child instanceof Node ? child : document.createTextNode(String(child)));
}

function set(node, attrs, isSvg) {
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key === "class") node.setAttribute("class", Array.isArray(value) ? value.filter(Boolean).join(" ") : value);
    else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "text") node.textContent = value;
    else if (!isSvg && key in node && typeof value !== "string") node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
}

export function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  set(node, attrs, false);
  append(node, children);
  return node;
}

export function s(tag, attrs, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  set(node, attrs, true);
  append(node, children);
  return node;
}

// ---------------------------------------------------------------------------
// numbers and dates

export const num = (v, d = 2) => (v == null || Number.isNaN(v) ? "–" : v.toFixed(d));
export const pct = (v, d = 0) => (v == null || Number.isNaN(v) ? "–" : `${(v * 100).toFixed(d)}%`);
export const int = (v) => (v == null || Number.isNaN(v) ? "–" : Math.round(v).toLocaleString("ko-KR"));

const KST = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  hourCycle: "h23",
});

export function kst(ms) {
  const parts = Object.fromEntries(KST.formatToParts(new Date(ms)).map((p) => [p.type, p.value]));
  return { y: parts.year, m: parts.month, d: parts.day, hh: parts.hour, mm: parts.minute };
}

export const day = (ms) => { if (ms == null) return "–"; const t = kst(ms); return `${t.y}-${t.m}-${t.d}`; };
export const shortDay = (ms) => { if (ms == null) return "–"; const t = kst(ms); return `${t.m}/${t.d}`; };
export const stamp = (ms) => { if (ms == null) return "–"; const t = kst(ms); return `${t.y}-${t.m}-${t.d} ${t.hh}:${t.mm}`; };

// A day as the moment the CLI means by it: noon KST.
export function noonKst(dateText) {
  const [y, m, d] = dateText.split("-").map(Number);
  return Date.UTC(y, m - 1, d, 3, 0, 0);
}

export function todayKst() {
  return day(Date.now());
}

// ---------------------------------------------------------------------------
// units and attributes

export const unitName = (unit) => unit.ko || unit.en || unit.id;

// "라피 : 레드 후드" -> ["라피", "레드 후드"]: two lines under a face.
export function nameLines(unit) {
  const name = unitName(unit);
  const cut = name.indexOf(" : ");
  return cut < 0 ? [name] : [name.slice(0, cut), name.slice(cut + 3)];
}

const slug = (v) => v.trim().toLowerCase().replaceAll(" ", "-");

export function elementIcon(element, size = 18, extra = {}) {
  if (!element) return null;
  return h("img", {
    class: ["ico-el", extra.class], src: `icons/elements/${slug(element)}.png`, alt: ELEMENT_KO[element] || element,
    title: extra.title ?? (ELEMENT_KO[element] || element), width: size, height: Math.round(size * 73 / 63),
    decoding: "async",
  });
}

// A one-colour glyph (class, burst) drawn in the text colour, so it reads on either theme.
function glyph(kind, value, width, height, title) {
  const url = `url("${new URL(`icons/${kind}/${slug(value)}.png`, document.baseURI).href}")`;
  return h("span", {
    class: "glyph", role: "img", "aria-label": title, title,
    style: { width: `${width}px`, height: `${height}px`, maskImage: url, webkitMaskImage: url },
  });
}

const BURST_SIZE = { I: [6, 13], II: [11, 13], III: [14, 13], "I-II-III": [14, 13] };

export function burstIcon(burst) {
  if (!burst) return null;
  const [w, hgt] = BURST_SIZE[burst] || [12, 13];
  return glyph("bursts", burst, w, hgt, `버스트 ${burst}`);
}

export function classIcon(unitClass, size = 16) {
  if (!unitClass) return null;
  return glyph("classes", unitClass, size, size, CLASS_KO[unitClass] || unitClass);
}

export function face(unit, size = 64, attrs = {}) {
  return h("img", {
    class: "face-img", src: `icons/units/${unit.id}.webp`, alt: unitName(unit), width: size, height: size,
    loading: "lazy", decoding: "async", ...attrs,
    onerror: (e) => { e.target.replaceWith(h("span", { class: "face-missing" }, unitName(unit).slice(0, 2))); },
  });
}

export function elementLabel(element) {
  return h("span", { class: "el-label" }, elementIcon(element, 16), ELEMENT_KO[element] || element || "?");
}

export function tierBadge(tier, value, attrs = {}) {
  const t = tier || "-";
  return h("span", { class: ["tb", attrs.class], dataset: { tier: t }, title: attrs.title },
    h("b", null, t), value != null && !Number.isNaN(value) ? h("span", null, num(value)) : null);
}

// ---------------------------------------------------------------------------
// tooltip: one for the page, for hover and focus alike

let tip = null;
let tipOwner = null;

export function initTip(node) {
  tip = node;
  document.addEventListener("scroll", () => hideTip(), { passive: true, capture: true });
  window.addEventListener("resize", () => hideTip());
}

function place(x, y, anchor) {
  const pad = 12;
  const box = tip.getBoundingClientRect();
  const vw = document.documentElement.clientWidth, vh = window.innerHeight;
  let left, top;
  if (anchor) {
    left = anchor.left + anchor.width / 2 - box.width / 2;
    top = anchor.top - box.height - 10;
    if (top < pad) top = anchor.bottom + 10;
  } else {
    left = x + 16;
    top = y + 16;
    if (left + box.width > vw - pad) left = x - box.width - 16;
    if (top + box.height > vh - pad) top = y - box.height - 16;
  }
  tip.style.left = `${Math.max(pad, Math.min(left, vw - box.width - pad))}px`;
  tip.style.top = `${Math.max(pad, Math.min(top, vh - box.height - pad))}px`;
}

export function showTip(owner, content, at = null) {
  if (!tip) return;
  tip.replaceChildren(content);
  tipOwner = owner;
  tip.hidden = false;
  if (at) place(at.x, at.y, null);
  else place(0, 0, owner.getBoundingClientRect());
}

export function moveTip(owner, at) {
  if (tip && tipOwner === owner && !tip.hidden) place(at.x, at.y, null);
}

export function hideTip(owner = null) {
  if (!tip || (owner && owner !== tipOwner)) return;
  tip.hidden = true;
  tipOwner = null;
}

// Hover and keyboard focus show the same details; the details are built lazily.
export function withTip(node, build) {
  const show = (e) => showTip(node, build(), e.type === "pointermove" && e.pointerType === "mouse" ? { x: e.clientX, y: e.clientY } : null);
  node.addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") show(e); });
  node.addEventListener("pointerleave", () => hideTip(node));
  node.addEventListener("focus", show);
  node.addEventListener("blur", () => hideTip(node));
  return node;
}

// ---------------------------------------------------------------------------
// controls

export function segmented(options, value, onChange, attrs = {}) {
  return h("div", { class: ["seg", attrs.class], role: "radiogroup", "aria-label": attrs.label },
    options.map((o) => h("button", {
      type: "button", class: "seg-btn", role: "radio", "aria-checked": String(o.value === value),
      title: o.title, onclick: () => { if (o.value !== value) onChange(o.value); },
    }, o.icon || null, o.label != null ? h("span", null, o.label) : null)));
}

export function toggle(label, checked, onChange, attrs = {}) {
  return h("label", { class: ["switch", attrs.class] },
    h("input", { type: "checkbox", checked, onchange: (e) => onChange(e.target.checked) }),
    h("span", { class: "switch-track", "aria-hidden": "true" }), h("span", null, label));
}

// A sortable table: columns [{key, label, title, num, sort(row), cell(row)}].
export function sortableTable(columns, rows, { sortKey, sortDir = "desc", onSort, rowAttrs, caption } = {}) {
  const column = columns.find((c) => c.key === sortKey) || null;
  const sorted = column?.sort ? [...rows].sort((a, b) => {
    const x = column.sort(a), y = column.sort(b);
    const nx = x == null || Number.isNaN(x), ny = y == null || Number.isNaN(y);
    if (nx || ny) return nx === ny ? 0 : nx ? 1 : -1;
    const d = typeof x === "string" ? x.localeCompare(y, "ko") : x - y;
    return sortDir === "asc" ? d : -d;
  }) : rows;
  const head = h("tr", null, columns.map((c) => {
    const active = c.key === sortKey;
    return h("th", {
      scope: "col", class: [c.num && "n", c.class, active && "sorted"], title: c.title,
      "aria-sort": active ? (sortDir === "asc" ? "ascending" : "descending") : null,
    }, c.sort ? h("button", {
      type: "button", class: "th-btn",
      onclick: () => onSort?.(c.key, active ? (sortDir === "asc" ? "desc" : "asc") : (c.firstDir || "desc")),
    }, c.label, h("span", { class: "sort-mark", "aria-hidden": "true" }, active ? (sortDir === "asc" ? "▲" : "▼") : "")) : c.label);
  }));
  const body = sorted.map((r) => h("tr", rowAttrs ? rowAttrs(r) : null,
    columns.map((c) => h(c.head ? "th" : "td", { class: [c.num && "n", c.class], scope: c.head ? "row" : null },
      c.cell(r)))));
  return h("div", { class: "table-wrap" },
    h("table", { class: "grid" }, caption ? h("caption", { class: "sr-only" }, caption) : null,
      h("thead", null, head), h("tbody", null, body)));
}

// Five segments, the players who fielded a unit by the deck rank they put it in (1덱 = strongest).
export function deckSplit(inDeck, total, width = 112) {
  if (!total) return h("span", { class: "muted" }, "–");
  const bar = h("span", { class: "split", style: { width: `${width}px` }, role: "img",
    "aria-label": inDeck.map((n, k) => `${k + 1}덱 ${Math.round((n / total) * 100)}%`).join(", ") });
  inDeck.forEach((n, k) => {
    if (!n) return;
    bar.append(h("span", { class: "split-seg", style: { flexGrow: n, background: `var(--deck-${k + 1})` } }));
  });
  return bar;
}
