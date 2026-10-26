"use strict";
// Data comes from web/data.js (python -m feh build); user edits live in state.json via /api/state.
const D = window.FEH_DATA;
const TIERS = [9.9, 9.5, 9.0, 8.5, 8.0, 7.5, 7.0];
const KEEP_RATING = 9.0;
// a match is trusted when its distance is low and clearly better than the runner-up
const CONF_DIST = 20, CONF_MARGIN = 4;
const SLOTS = [["weapon", "Weapon"], ["assist", "Assist"], ["special", "Special"], ["A", "A"], ["B", "B"],
  ["C", "C"], ["S", "Seal"], ["X", "Attuned"], ["emblem", "Emblem"]];
const COLORS = ["Red", "Blue", "Green", "Colorless"];

let S = { tiles: {} };
let view = "ranking";
let openIdx = null;

// ---------- helpers ----------
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Game8 and the wiki spell some names differently: "Pulse Up：Blades" / "Pulse Up: Blades",
// "Dark Spikes T" / "Dark Spikes Τ" (Greek), "Distant Counter (D)" / "Distant Counter"
const norm = (s) => String(s ?? "").replace(/ð/g, "d").replace(/þ/g, "th").replace(/Τ/g, "T")
  .normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/\s*[:：]\s*/g, ": ")
  .replace(/\s*\([^)]*\)$/, "").toLowerCase().trim();
const tileImg = (t) => `../build/tiles/${t.img}`;
const faceImg = (w) => (D.units[w]?.face ? `../${D.units[w].face}` : "");
const unitLabel = (w) => { const u = D.units[w]; return u ? (u.shortname || `${u.name}: ${u.title}`) : (w ?? ""); };
const skillName = (w) => D.skills[w]?.name ?? w;
const stars = (r) => `<span class="r${r}">${"★".repeat(r)}</span>`;
const colorOf = (u) => (u?.weapon || "").split(" ")[0];
const ov = (idx) => (S.tiles[idx] ??= {});

// ---------- state persistence ----------
let saveTimer = null;
function save() {
  clearTimeout(saveTimer);
  $("#save-status").textContent = "saving…";
  saveTimer = setTimeout(async () => {
    try {
      const r = await fetch("/api/state", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(S) });
      if (!r.ok) throw new Error(r.status);
      $("#save-status").textContent = "saved to state.json";
    } catch {
      localStorage.setItem("feh-state", JSON.stringify(S));
      $("#save-status").textContent = "saved in browser only (run: python -m feh serve)";
    }
  }, 300);
}
async function loadState() {
  try {
    const r = await fetch("/api/state");
    if (r.ok) S = await r.json();
  } catch {
    S = JSON.parse(localStorage.getItem("feh-state") || "{}");
  }
  S.tiles ??= {};
}

// ---------- model ----------
function computeInstances() {
  const list = D.tiles.map((t) => {
    const o = S.tiles[t.idx] || {};
    const [best, second] = t.candidates;
    const confident = best && best.dist <= CONF_DIST && (!second || second.dist - best.dist >= CONF_MARGIN);
    const unit = o.unit || (confident ? best.unit : null);
    return {
      idx: t.idx, tile: t, unit, u: D.units[unit], confirmed: !!o.unit, uncertain: !unit,
      rarity: o.rarity ?? t.rarity, invested: o.invested ?? t.level_digits === 2,
      tracked: o.skills || {}, keep: o.keep,
    };
  });
  // duplicates: the best copy (invested, then rarity, then barracks order) is the main one
  const groups = {};
  for (const i of list) if (i.unit) (groups[i.unit] ??= []).push(i);
  for (const copies of Object.values(groups)) {
    copies.sort((a, b) => (b.invested - a.invested) || (b.rarity - a.rarity) || (a.idx - b.idx));
    copies.forEach((c, n) => { c.dup = n > 0; c.copies = copies.length; });
  }
  for (const i of list) i.deleteReason = deleteReason(i);
  for (const i of list) i.deletable = !!i.deleteReason;
  // skills a keeper's builds need and it doesn't have yet: norm(skill) -> [{keeper, build, slot}]
  const needed = {};
  for (const k of list) {
    if (!k.unit || k.deletable) continue;
    for (const b of k.u.builds || []) for (const [slot, sk] of Object.entries(b.slots)) {
      if (slot === "emblem" || hasSkill(k, sk)) continue;
      (needed[norm(sk)] ??= []).push({ keeper: k, build: b.title, slot });
    }
  }
  const providers = {};  // norm(skill) -> number of deletable units that can pass it on
  for (const i of list) {
    i.fodderFor = [];
    if (!i.deletable) continue;
    const seen = new Set();
    for (const w of inheritable(i)) for (const n of needed[norm(skillName(w))] || []) {
      const key = `${n.keeper.idx}|${norm(skillName(w))}`;  // one chip per keeper and skill, whatever the build
      if (n.keeper === i || seen.has(key)) continue;
      seen.add(key);
      i.fodderFor.push({ ...n, skill: skillName(w) });
    }
    for (const sk of new Set(i.fodderFor.map((f) => norm(f.skill)))) providers[sk] = (providers[sk] || 0) + 1;
  }
  for (const i of list) {
    for (const f of i.fodderFor) f.only = providers[norm(f.skill)] === 1;
    i.fodderFor.sort((a, b) => (b.only - a.only) || a.skill.localeCompare(b.skill));
    i.uniqueSkills = new Set(i.fodderFor.filter((f) => f.only).map((f) => f.skill)).size;
  }
  return list;
}

function deleteReason(i) {
  if (i.keep === true) return null;
  if (i.keep === false) return "marked for deletion";
  if (!i.unit || i.invested) return null;
  if (i.dup) return "duplicate";
  if (i.u.rating == null) return null;  // unrated on Game8: don't guess
  if (i.u.rating < KEEP_RATING) return `rated ${i.u.rating.toFixed(1)}`;
  return null;
}

// skills the unit knows at its rarity (wiki unlock rarity); `default` = learned without spending SP
function nativeSkills(i) {
  return (i.u?.skills || []).filter((s) => s.unlock && s.unlock <= i.rarity);
}
function inheritable(i) {
  return nativeSkills(i).map((s) => s.skill).filter((w) => !D.skills[w]?.exclusive);
}
function hasSkill(i, displayName) {
  const n = norm(displayName);
  return nativeSkills(i).some((s) => norm(skillName(s.skill)) === n)
    || Object.values(i.tracked).some((v) => norm(v) === n);
}

// ---------- views ----------
function card(i) {
  const name = i.unit ? unitLabel(i.unit) : "Unknown";
  const cls = ["card", i.deletable ? "deletable" : "", i.uncertain ? "uncertain" : ""].join(" ");
  const badge = $("#hide-dupes").checked && i.copies > 1 ? `<span class="badge">×${i.copies}</span>` : "";
  return `<div class="${cls}" data-idx="${i.idx}" title="${esc(i.unit || "unidentified")}">
    ${badge}<img src="${tileImg(i.tile)}" loading="lazy">
    <div class="name">${esc(name)}</div>
    <div class="meta">${stars(i.rarity)}<span>${i.invested ? "Lv.10+" : "Lv.1"}</span></div></div>`;
}

function filtered(list) {
  const q = norm($("#search").value);
  return list.filter((i) => !q || norm(i.unit ? `${i.unit} ${unitLabel(i.unit)}` : "unknown").includes(q))
    .filter((i) => !$("#hide-dupes").checked || !i.dup);
}

function renderRanking(list) {
  const groups = new Map(TIERS.map((t) => [t, []]));
  groups.set("unrated", []); groups.set("unknown", []);
  for (const i of filtered(list)) {
    const key = !i.unit ? "unknown" : (i.u.rating == null ? "unrated" : i.u.rating);
    (groups.get(key) ?? groups.get("unrated")).push(i);
  }
  const titles = { unrated: "Not rated on Game8", unknown: "Uncategorized (not identified yet: see To review)" };
  let html = "";
  for (const [key, items] of groups) {
    if (!items.length) continue;
    items.sort((a, b) => (COLORS.indexOf(colorOf(a.u)) - COLORS.indexOf(colorOf(b.u)))
      || unitLabel(a.unit).localeCompare(unitLabel(b.unit)) || a.idx - b.idx);
    const head = typeof key === "number" ? `<b>${key.toFixed(1)}</b>${key >= KEEP_RATING ? "Game8 tier list" : ""}` : `<b>${titles[key]}</b>`;
    html += `<section class="tier"><h2>${head} · ${items.length}</h2><div class="grid">${items.map(card).join("")}</div></section>`;
  }
  return html || `<p class="muted">Nothing to show.</p>`;
}

function candChips(i) {
  return i.tile.candidates.map((c) => `<div class="cand" data-pick="${esc(c.unit)}" data-for="${i.idx}">
    <img src="${faceImg(c.unit)}" loading="lazy"><span>${esc(unitLabel(c.unit))}</span><span class="muted">${c.dist}</span></div>`).join("");
}

function renderReview(list) {
  const showAll = S.reviewAll;
  const items = list.filter((i) => showAll ? !i.confirmed : i.uncertain);
  let html = `<div class="form-row"><label><input type="checkbox" id="review-all" ${showAll ? "checked" : ""}>
    Also show confident matches that aren't confirmed yet</label></div>
    <p class="muted">Click the right face to confirm it, or type a unit name. ${items.length} to review.</p><div class="list">`;
  for (const i of items) {
    html += `<div class="row"><img src="${tileImg(i.tile)}" data-idx="${i.idx}">
      <div class="grow"><div class="cands">${candChips(i)}</div>
      <div class="form-row"><input type="text" list="unit-names" placeholder="Other unit…" data-other="${i.idx}">
      <span class="muted">#${i.idx} · ${esc(i.tile.source)} · ${stars(i.rarity)}</span></div></div></div>`;
  }
  return html + "</div>";
}

// "Skill → keeper, keeper, keeper +N", one line per skill
function fodderSummary(i, max = 3) {
  const bySkill = new Map();
  for (const f of i.fodderFor) {
    if (!bySkill.has(f.skill)) bySkill.set(f.skill, { only: f.only, keepers: [] });
    bySkill.get(f.skill).keepers.push(f.keeper);
  }
  return [...bySkill].map(([skill, { only, keepers }]) => `<div>
    <span class="chip ${only ? "only" : ""}" title="${only ? "only deletable source of this skill" : ""}">${esc(skill)}</span> →
    ${keepers.slice(0, max).map((k) => `<a href="#" data-idx="${k.idx}">${esc(unitLabel(k.unit))}</a>`).join(", ")}
    ${keepers.length > max ? `<span class="muted">+${keepers.length - max}</span>` : ""}</div>`).join("");
}

function renderDelete(list) {
  const del = filtered(list).filter((i) => i.deletable);
  const fodder = del.filter((i) => i.fodderFor.length), home = del.filter((i) => !i.fodderFor.length);
  // most valuable fodder first: units that are the only source of a needed skill
  fodder.sort((a, b) => (b.uniqueSkills - a.uniqueSkills) || (b.fodderFor.length - a.fodderFor.length));
  const row = (i) => `<div class="row"><img src="${tileImg(i.tile)}" data-idx="${i.idx}">
    <div class="grow"><b>${esc(unitLabel(i.unit))}</b> ${stars(i.rarity)} <span class="muted">· ${esc(i.deleteReason)}</span>
    <div class="src">${fodderSummary(i)}</div></div></div>`;
  return `<h2>Fodder: has a skill one of your keepers' builds needs · ${fodder.length}</h2>
    <p class="muted">Highlighted skills have no other deletable source: inherit those before sending the unit home.</p>
    <div class="list">${fodder.map(row).join("") || '<p class="muted">None</p>'}</div>
    <h2>Send home: nothing useful to inherit · ${home.length}</h2>
    <div class="list">${home.map(row).join("") || '<p class="muted">None</p>'}</div>`;
}

// ---------- detail drawer ----------
function skillSources(list, me, sk) {
  const n = norm(sk);
  const holders = list.filter((i) => i !== me && i.unit && inheritable(i).some((w) => norm(skillName(w)) === n));
  holders.sort((a, b) => b.deletable - a.deletable);
  return holders.map((h) => `<span class="chip ${h.deletable ? "" : "muted"}" data-idx="${h.idx}" title="${h.deletable ? "deletable" : "keeper: would be consumed"}">
    <img src="${tileImg(h.tile)}">${esc(unitLabel(h.unit))}${h.deletable ? "" : " (keeper)"}</span>`).join("");
}

function renderDrawer(list) {
  const i = list.find((x) => x.idx === openIdx);
  if (!i) { $("#drawer").hidden = true; return; }
  const u = i.u;
  let html = `<button class="btn close" data-close>✕</button><div class="head">
    <img src="${tileImg(i.tile)}">${i.unit ? `<img src="${faceImg(i.unit)}">` : ""}
    <div><h2>${esc(u ? `${u.name}: ${u.title}` : "Unidentified")}</h2>
    <div class="muted">${esc(u?.shortname || "")} · ${esc(u?.weapon || "")} · ${esc(u?.move || "")}</div>
    <div>${u?.rating != null ? `Game8 <b>${u.rating.toFixed(1)}</b>/10` : "Not rated"}
      ${u?.game8_url ? ` · <a href="${esc(u.game8_url)}" target="_blank">Game8 page</a>` : ""}</div>
    <div>${i.deletable ? `<span class="bad">Deletable: ${esc(i.deleteReason)}</span>` : `<span class="ok">Keep</span>`}
      ${i.copies > 1 ? ` · ${i.copies} copies${i.dup ? " (this one is a duplicate)" : ""}` : ""}</div></div></div>

    <div class="form-row">Rarity <select data-rarity>${[5, 4, 3, 2, 1].map((r) => `<option ${r === i.rarity ? "selected" : ""}>${r}</option>`).join("")}</select>
      <label><input type="checkbox" data-invested ${i.invested ? "checked" : ""}> Invested</label>
      Decision <select data-keep>
        <option value="" ${i.keep == null ? "selected" : ""}>Auto</option>
        <option value="keep" ${i.keep === true ? "selected" : ""}>Keep</option>
        <option value="delete" ${i.keep === false ? "selected" : ""}>Delete</option></select></div>

    <h3>Identification ${i.confirmed ? '<span class="ok">confirmed</span>' : '<span class="warn">auto-detected</span>'}</h3>
    <div class="cands">${candChips(i)}</div>
    <div class="form-row"><input type="text" list="unit-names" placeholder="Other unit…" data-other="${i.idx}"></div>`;

  if (u) {
    for (const b of u.builds || []) {
      html += `<h3>${esc(b.title)}</h3><table class="build">`;
      for (const [slot, label] of SLOTS) {
        const sk = b.slots[slot];
        if (!sk) continue;
        let status;
        if (slot === "emblem") status = `<span class="muted">Emblem ring</span>`;
        else if (hasSkill(i, sk)) status = `<span class="ok">✓ has it</span>`;
        else {
          const src = skillSources(list, i, sk);
          status = src ? `<span class="warn">from:</span> ${src}` : `<span class="bad">not in barracks</span>${slot === "S" ? ' <span class="muted">(Sacred Seal Forge?)</span>' : ""}`;
        }
        const link = b.links?.[slot];
        const name = link ? `<a href="${esc(link)}" target="_blank" title="Game8 page: how to obtain">${esc(sk)} ↗</a>` : esc(sk);
        html += `<tr><td>${label}</td><td><b>${name}</b><div class="src">${status}</div></td></tr>`;
      }
      html += "</table>";
    }
    if (!u.builds?.length) html += `<h3>Builds</h3><p class="muted">${u.game8_url ? "No Game8 build (re-run the build after confirming units)" : "Not on Game8"}</p>`;

    html += `<h3>Current skills (tracked)</h3><p class="muted">Leave empty to assume the default kit.</p>`;
    for (const [slot, label] of SLOTS.filter(([s]) => s !== "emblem")) {
      html += `<div class="form-row"><span style="width:64px">${label}</span>
        <input type="text" list="skill-names" data-skill="${slot}" value="${esc(i.tracked[slot] || "")}" style="flex:1"></div>`;
    }
    html += `<h3>Kit at ${i.rarity}★</h3><div>${nativeSkills(i).map((s) => `<span class="chip" title="${esc(D.skills[s.skill]?.description || "")}">
      ${esc(skillName(s.skill))}${D.skills[s.skill]?.exclusive ? " 🔒" : ""}${s.default && s.default <= i.rarity ? "" : " (SP)"}</span>`).join("")}</div>`;
    if (i.fodderFor.length) {
      html += `<h3>Fodder for</h3><div class="src">${fodderSummary(i, Infinity)}</div>`;
    }
  }
  $("#drawer").innerHTML = html;
  $("#drawer").hidden = false;
}

// ---------- wiring ----------
function render() {
  const list = computeInstances();
  $("#count-review").textContent = `(${list.filter((i) => i.uncertain).length})`;
  $("#count-delete").textContent = `(${list.filter((i) => i.deletable).length})`;
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $("#view").innerHTML = view === "ranking" ? renderRanking(list) : view === "review" ? renderReview(list) : renderDelete(list);
  renderDrawer(list);
}

function setUnit(idx, wikiName) {
  if (!D.units[wikiName]) { alert(`Unknown unit: ${wikiName}`); return; }
  ov(idx).unit = wikiName;
  save(); render();
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-pick],[data-idx],[data-close],nav button");
  if (!t) return;
  if (t.tagName === "A") e.preventDefault();
  if (t.dataset.pick) setUnit(+t.dataset.for, t.dataset.pick);
  else if (t.dataset.idx) { openIdx = +t.dataset.idx; render(); }
  else if (t.hasAttribute("data-close")) { openIdx = null; render(); }
  else if (t.dataset.view) { view = t.dataset.view; render(); }
});

document.addEventListener("change", (e) => {
  const t = e.target;
  if (t.dataset.other) { if (t.value) setUnit(+t.dataset.other, t.value); return; }
  if (t.id === "review-all") { S.reviewAll = t.checked; save(); render(); return; }
  if (t.id === "hide-dupes") { render(); return; }
  if (openIdx == null) return;
  const o = ov(openIdx);
  if (t.hasAttribute("data-rarity")) o.rarity = +t.value;
  else if (t.hasAttribute("data-invested")) o.invested = t.checked;
  else if (t.hasAttribute("data-keep")) { if (t.value) o.keep = t.value === "keep"; else delete o.keep; }
  else if (t.dataset.skill) { o.skills ??= {}; if (t.value) o.skills[t.dataset.skill] = t.value; else delete o.skills[t.dataset.skill]; }
  else return;
  save(); render();
});

document.addEventListener("keydown", (e) => { if (e.key === "Escape" && openIdx != null) { openIdx = null; render(); } });
$("#search").addEventListener("input", render);

(async function init() {
  await loadState();
  const names = [...new Set(Object.values(D.skills).map((s) => s.name))].sort();
  $("#skill-names").innerHTML = names.map((n) => `<option value="${esc(n)}">`).join("");
  $("#unit-names").innerHTML = Object.entries(D.units).map(([w, u]) => `<option value="${esc(w)}">${esc(u.shortname || "")}</option>`).join("");
  render();
})();
