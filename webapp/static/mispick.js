let lastCsv = null;
// Kept so nudge buttons (which re-run analyze() without the user touching
// the file input again) and a restored session both keep working — a
// plain <input type=file> can never be re-populated by JS after a page
// reload (browser security), so the actual file CONTENTS are cached here
// instead the first time they're read, and reused whenever the input
// itself is empty. See analyze()'s file-reading block below.
let lastStrateFiles = [];

// ---- Visual grids (added 2026/08/18: user asked to see the actual wafer
// MAP here too, not just a table — and to have force-delete positions
// shown as a red outline directly on each substrate's own BINGO MAP,
// updating live as the offset is nudged with direction buttons). Reuses
// the same .wafer-cell/.substrate-cell CSS the main 補資料 page uses. ----
// Bin color palette — same convention as app.js's BIN_COLORS/renderBinLegend
// (see that comment for why bin codes are always a single ASCII digit):
// 2026/08/19 ask "應該依據下載下來有什麼bin code就出現不能只有Bin 1 Bin 7".
const BIN_COLORS = {
  "0": "#94a3b8", "1": "#4fb84a", "2": "#f59e0b", "3": "#ef4444",
  "4": "#8b5cf6", "5": "#3b82f6", "6": "#14b8a6", "7": "#d867d8",
  "8": "#92400e", "9": "#ca8a04",
};
const BIN_COLOR_FALLBACK = "#64748b";

function binColor(bin) {
  return BIN_COLORS[bin] !== undefined ? BIN_COLORS[bin] : BIN_COLOR_FALLBACK;
}

function applyBinColor(cell, bin) {
  if (bin === undefined) return;
  cell.classList.add("bin-cell");
  cell.style.setProperty("--bin-color", binColor(bin));
}

function renderBinLegend(containerId, cells) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const bins = new Set(cells.values());
  const sorted = [...bins].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  el.innerHTML = sorted.map((b) => `<span><i style="background:${binColor(b)}"></i>Bin ${b}</span>`).join("");
}

function renderWaferGrid(wafer) {
  const panel = document.getElementById("mispick-wafer-panel");
  const container = document.getElementById("mp-wafer-grid");
  container.innerHTML = "";
  if (!wafer || !wafer.cells || !wafer.cells.length) {
    panel.style.display = "none";
    return;
  }
  panel.style.display = "";
  document.getElementById("mp-wafer-info").textContent =
    `LotNo=${wafer.lot_no} WaferID=${wafer.wafer_id}（${wafer.columns}x${wafer.rows}，共${wafer.cells.length}顆有資料）`;

  const cellMap = new Map(wafer.cells.map((c) => [`${c.x},${c.y}`, c.bin]));
  renderBinLegend("mp-wafer-bin-legend", cellMap);
  const xs = wafer.cells.map((c) => c.x);
  const ys = wafer.cells.map((c) => c.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);

  const headerRow = document.createElement("div");
  headerRow.className = "wafer-row";
  const corner = document.createElement("div");
  corner.className = "grid-axis-cell grid-axis-corner";
  headerRow.appendChild(corner);
  for (let x = maxX; x >= minX; x--) {
    const label = document.createElement("div");
    label.className = "grid-axis-cell";
    label.textContent = x;
    headerRow.appendChild(label);
  }
  container.appendChild(headerRow);

  for (let y = minY; y <= maxY; y++) {
    const row = document.createElement("div");
    row.className = "wafer-row";
    const rowLabel = document.createElement("div");
    rowLabel.className = "grid-axis-cell";
    rowLabel.textContent = y;
    row.appendChild(rowLabel);
    for (let x = maxX; x >= minX; x--) {
      const bin = cellMap.get(`${x},${y}`);
      const cell = document.createElement("div");
      cell.className = "wafer-cell";
      applyBinColor(cell, bin);
      cell.title = `${x}:${y}`;
      row.appendChild(cell);
    }
    container.appendChild(row);
  }
}

function renderSubstrateGrid(containerId, sub) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";
  if (!sub.substrate_column || !sub.substrate_row) return;

  const cellInfo = new Map(sub.grid_cells.map((c) => [`${c.tx},${c.ty}`, c]));

  const headerRow = document.createElement("div");
  headerRow.className = "wafer-row";
  const corner = document.createElement("div");
  corner.className = "grid-axis-cell grid-axis-corner";
  headerRow.appendChild(corner);
  for (let x = 0; x < sub.substrate_column; x++) {
    const label = document.createElement("div");
    label.className = "grid-axis-cell";
    label.textContent = x;
    headerRow.appendChild(label);
  }
  container.appendChild(headerRow);

  for (let y = 0; y < sub.substrate_row; y++) {
    const row = document.createElement("div");
    row.className = "wafer-row";
    const rowLabel = document.createElement("div");
    rowLabel.className = "grid-axis-cell";
    rowLabel.textContent = y;
    row.appendChild(rowLabel);
    for (let x = 0; x < sub.substrate_column; x++) {
      const cell = document.createElement("div");
      cell.className = "substrate-cell";
      const info = cellInfo.get(`${x},${y}`);
      if (info) {
        cell.classList.add("filled");
        if (info.decision === "FORCE_DELETE_ACTUAL_BIN_NG") cell.classList.add("mp-force");
        else if (info.decision === "REVIEW_ACTUAL_BIN_REVIEW") cell.classList.add("mp-review");
        cell.title = `${x}:${y} — ${decisionLabel(info.decision)}（第${info.layer === "other" ? "2" : "1"}層）`;
      } else {
        cell.title = `${x}:${y}`;
      }
      row.appendChild(cell);
    }
    container.appendChild(row);
  }
}

function decisionLabel(decision) {
  if (decision === "FORCE_DELETE_ACTUAL_BIN_NG") return "強制點除";
  if (decision === "REVIEW_ACTUAL_BIN_REVIEW") return "人工確認";
  return decision;
}

function decisionClass(decision) {
  if (decision === "FORCE_DELETE_ACTUAL_BIN_NG") return "bad";
  if (decision === "REVIEW_ACTUAL_BIN_REVIEW") return "warnRow";
  return "";
}

function renderResults(data) {
  renderWaferGrid(data.wafer);

  const container = document.getElementById("mp-results");
  container.innerHTML = "";

  data.substrates.forEach((sub, idx) => {
    const box = document.createElement("div");
    box.className = "notice";
    box.style.marginTop = "0.8rem";

    if (sub.error) {
      box.classList.add("error");
      box.innerHTML = `<b>${sub.name}</b>（Substrate ID: ${sub.substrate_id ?? "?"}）<br>錯誤：${sub.error}`;
      container.appendChild(box);
      return;
    }

    const s = sub.summary;
    const head = document.createElement("div");
    head.innerHTML =
      `<b>${sub.name}</b>（Substrate ID: ${sub.substrate_id}）｜` +
      `強制點除 ${s.force_delete}｜人工確認 ${s.review}｜異常 ${s.anomaly}｜正常 ${s.ok}｜其他 ${s.other}｜` +
      `排除(非目標Wafer) ${sub.excluded_count}`;
    container.appendChild(head);

    const gridId = `mp-substrate-grid-${idx}`;
    const gridWrap = document.createElement("div");
    gridWrap.className = "lyr-wafer-wrap";
    gridWrap.style.marginTop = "0.4rem";
    gridWrap.innerHTML = `<div id="${gridId}" class="lyr-substrate-grid"></div>`;
    container.appendChild(gridWrap);
    renderSubstrateGrid(gridId, sub);

    if (sub.action_rows.length) {
      const table = document.createElement("table");
      table.className = "tbl";
      table.style.marginTop = "0.5rem";
      table.innerHTML =
        "<thead><tr><th>No.</th><th>判定</th><th>Layer</th><th>Block</th><th>座標</th><th>TX:TY</th><th>實際BIN</th></tr></thead>";
      const tbody = document.createElement("tbody");
      for (const r of sub.action_rows) {
        const tr = document.createElement("tr");
        tr.className = decisionClass(r.decision);
        tr.innerHTML =
          `<td>${r.action_no}</td><td>${decisionLabel(r.decision)}</td><td>${r.layer}</td>` +
          `<td>${r.output_block ?? ""}</td><td>${r.output_coord}</td><td>${r.tx}:${r.ty}</td><td>${r.actual_bin}</td>`;
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      container.appendChild(table);
    } else {
      const none = document.createElement("p");
      none.className = "small";
      none.textContent = "沒有需要點除或人工確認的位置。";
      container.appendChild(none);
    }
  });
}

async function analyze() {
  const status = document.getElementById("mp-status");
  status.className = "";
  status.textContent = "分析中...";
  document.getElementById("mp-btn-download-csv").style.display = "none";
  lastCsv = null;

  const files = [...(document.getElementById("mp_strate_files").files || [])];
  let strateFiles;
  if (files.length) {
    strateFiles = [];
    for (const f of files) {
      strateFiles.push({ name: f.name, text: await f.text() });
    }
    lastStrateFiles = strateFiles;
  } else if (lastStrateFiles.length) {
    strateFiles = lastStrateFiles; // nudge button, or a restored session — see the comment at lastStrateFiles' declaration
  } else {
    status.className = "error";
    status.textContent = "請至少選擇一份STRATE檔案";
    return;
  }

  const payload = {
    wafer_ring: document.getElementById("mp_wafer_ring").value,
    machine_type: document.getElementById("mp_machine_type").value,
    offset_axis: document.getElementById("mp_offset_axis").value,
    offset_value: document.getElementById("mp_offset_value").value,
    good_bins: document.getElementById("mp_good_bins").value,
    ng_bins: document.getElementById("mp_ng_bins").value,
    review_bins: document.getElementById("mp_review_bins").value,
    frm: {
      lot_no: document.getElementById("mp_frm_lot_no").value,
      barcode_id: document.getElementById("mp_frm_barcode_id").value,
      frm_path: document.getElementById("mp_frm_path").value,
    },
    strate_files: strateFiles,
  };

  const res = await fetch("/api/mispick/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    status.className = "error";
    status.textContent = data.error;
    return;
  }

  renderResults(data);
  lastCsv = data.csv;
  document.getElementById("mp-btn-download-csv").style.display = "";
  updateOffsetDisplay();
  status.className = "ok";
  status.textContent = `分析完成，共 ${data.substrates.length} 份STRATE。`;
  saveState();
}

function downloadCsv() {
  if (!lastCsv) return;
  const blob = new Blob([lastCsv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "誤吸偏移點除清單.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function updateEsecWarning() {
  const isEsec = document.getElementById("mp_machine_type").value === "ESEC";
  document.getElementById("mp-esec-warning").style.display = isEsec ? "" : "none";
}

function updateOffsetDisplay() {
  const axis = document.getElementById("mp_offset_axis").value;
  const value = document.getElementById("mp_offset_value").value;
  document.getElementById("mp-offset-display").textContent = `目前偏移：${axis} ${value > 0 ? "+" : ""}${value}`;
}

// Direction buttons (2026/08/18 ask: "當我將WAFER T點移動往右或往左或
// 往上或往下，對應的strate bingo map就要知道對應位置那一顆吃到bin7"):
// each click nudges the offset by 1 in that direction and immediately
// re-runs analyze() against the already-selected STRATE files, so the
// red-outlined force-delete cells on the BINGO MAP grid update live
// instead of needing a manual "分析" click each time. Switching axis
// (e.g. was on Y, click ←/→) starts that axis fresh at ±1 rather than
// carrying over the old axis's magnitude, since a diagonal offset isn't
// a representable case (see mispick_analysis.py's make_offset() — always
// single-axis, matching how the real bonder's known-offset failure mode
// actually happens).
function nudgeOffset(axis, delta) {
  const axisSelect = document.getElementById("mp_offset_axis");
  const valueInput = document.getElementById("mp_offset_value");
  if (axisSelect.value !== axis) {
    axisSelect.value = axis;
    valueInput.value = delta;
  } else {
    const next = (parseInt(valueInput.value, 10) || 0) + delta;
    valueInput.value = next === 0 ? delta : next; // offset must never be 0
  }
  updateOffsetDisplay();
  analyze();
}

document.getElementById("mp-btn-analyze").addEventListener("click", analyze);
document.getElementById("mp-btn-download-csv").addEventListener("click", downloadCsv);
document.getElementById("mp_machine_type").addEventListener("change", updateEsecWarning);
document.getElementById("mp_offset_axis").addEventListener("change", updateOffsetDisplay);
document.getElementById("mp_offset_value").addEventListener("input", updateOffsetDisplay);
document.getElementById("mp-btn-nudge-up").addEventListener("click", () => nudgeOffset("Y", -1));
document.getElementById("mp-btn-nudge-down").addEventListener("click", () => nudgeOffset("Y", 1));
document.getElementById("mp-btn-nudge-left").addEventListener("click", () => nudgeOffset("X", -1));
document.getElementById("mp-btn-nudge-right").addEventListener("click", () => nudgeOffset("X", 1));
updateEsecWarning();
updateOffsetDisplay();

// ---- Persistence (2026/08/19 ask: "每個分頁在切換的時候資料不要不見" —
// only STRATE補檔/SECS格式化參數頁 had this so far; extending the same
// localStorage convention here). Saves the already-read STRATE file
// contents (lastStrateFiles) plus every form field; a restored session
// re-runs analyze() against them rather than re-deriving results
// client-side, same principle as the other pages' restoreState(). ----
const MP_STORAGE_KEY = "bingomap_mispick_state";
const MP_FIELD_IDS = [
  "mp_frm_lot_no", "mp_frm_barcode_id", "mp_frm_path", "mp_wafer_ring",
  "mp_machine_type", "mp_offset_axis", "mp_offset_value",
  "mp_good_bins", "mp_ng_bins", "mp_review_bins",
];

function saveState() {
  try {
    const fields = {};
    for (const id of MP_FIELD_IDS) fields[id] = document.getElementById(id).value;
    localStorage.setItem(MP_STORAGE_KEY, JSON.stringify({ strateFiles: lastStrateFiles, fields }));
  } catch (err) {
    // localStorage unavailable or quota exceeded — just don't persist
  }
}

function restoreState() {
  const raw = localStorage.getItem(MP_STORAGE_KEY);
  if (!raw) return;
  let saved;
  try {
    saved = JSON.parse(raw);
  } catch (err) {
    return;
  }

  // Field values are restored unconditionally, even with no STRATE files
  // loaded yet — see app.js's identical fix (2026/08/19: saveState() was
  // only ever reached through analyze(), so filling in wafer_ring/FRM
  // lot no/offset settings before ever selecting a STRATE file silently
  // lost those values when switching tabs). A direct 'input'/'change'
  // listener on every field (wired below) now saves immediately too.
  for (const id of MP_FIELD_IDS) {
    if (saved.fields && saved.fields[id] !== undefined) document.getElementById(id).value = saved.fields[id];
  }
  updateEsecWarning();
  updateOffsetDisplay();

  if (!saved.strateFiles || !saved.strateFiles.length) return;
  lastStrateFiles = saved.strateFiles;
  analyze();
}

for (const id of MP_FIELD_IDS) {
  const el = document.getElementById(id);
  el.addEventListener("input", saveState);
  el.addEventListener("change", saveState); // belt-and-suspenders for <select> (machine_type/offset_axis)
}

restoreState();
