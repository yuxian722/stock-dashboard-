let lastCsv = null;
let lastWaferData = null; // last {columns, rows, lot_no, wafer_id, cells} passed to renderWaferGrid() — so the T點 fields can re-render live on every keystroke without re-fetching
// 2026/08/21：跟app.js同一次更正，見那邊waferFlipXByPanel的完整註解——不同
// layout的wafer需要的方向不一樣，改成手動切換而不是猜一個全部套用的公式。
let mpFlipX = true;
let mpFlipY = false;
// Kept so nudge buttons (which re-run analyze() without the user touching
// the file input again) and a restored session both keep working — a
// plain <input type=file> can never be re-populated by JS after a page
// reload (browser security), so the actual file CONTENTS are cached here
// instead the first time they're read, and reused whenever the input
// itself is empty. See analyze()'s file-reading block below.
let lastStrateFiles = [];

// 2026/08/25：使用者反映「誤吸偏移只能一個檔案load進去，換下一個檔案都
// 沒反應」——查證後這是<input type=file multiple>的原生行為：每次重新
// 打開選擇檔案視窗，只要沒有在同一次視窗裡用Ctrl/Shift多選，瀏覽器就會
// 用這次選到的檔案「整批換掉」上一次選的，不會累加，即使原本就有multiple
// 屬性也一樣——所以分好幾次選、每次只選一份的話，只有最後一次選的那份會
// 留著，前面選的會被使用者以為「消失了/沒反應」。修法：不要直接在analyze()
// 裡讀取input.files，改成每次change事件都把新選到的檔案累加進這個陣列
// (用檔名+大小去重複)，並在畫面上列出目前累加了哪些檔案，可以個別移除或
// 整批清除；input本身每次change後清空(value = "")，這樣同一個檔案再選一次
// 也能正常觸發change(瀏覽器對同一個檔案不會觸發change，清空value可以繞過)。
let pendingStrateFiles = []; // File[] — accumulated across multiple "選擇檔案" interactions

// ---- Visual grids (added 2026/08/18: user asked to see the actual wafer
// MAP here too, not just a table — and to have force-delete positions
// shown as a red outline directly on each substrate's own BINGO MAP,
// updating live as the offset is nudged with direction buttons). Reuses
// the same .wafer-cell/.substrate-cell CSS the main 補資料 page uses. ----
// Bin color palette — same convention as app.js's BIN_COLORS/renderBinLegend
// (see that comment for why bin codes are always a single ASCII digit):
// 2026/08/19 ask "應該依據下載下來有什麼bin code就出現不能只有Bin 1 Bin 7".
// 2026/08/20更正成真正的WaferCoordinate.exe自己用的顏色(反編譯
// clsWaferMap.cs的DrawBinRect()找到的，不是我們自己配的) — 詳細對照表跟
// 發現過程見app.js同一個常數的註解。
const BIN_COLORS = {
  "1": "#13ff13", "2": "#0000cd", "3": "#ff8c00", "4": "#c60060",
  "5": "#40e0d0", "6": "#838383", "7": "#ff59ff", "8": "#11ffff",
  "9": "#848400",
};
const BIN_COLOR_FALLBACK = "#e0ffff"; // covers bin "0" too — real tool's switch doesn't special-case it either

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

// 2026/08/19 ask "誤吸的分頁無法下載wafer mapping" — this page's wafer MAP
// used to only ever appear as a side effect of running the full mispick
// analysis (which needs a STRATE file AND the完整Wafer ID filled in first).
// Added a standalone "預覽/讀取wafer MAP" button (see previewWaferMap()
// below) that hits the same /api/frm endpoint the main page's own "自動
// 讀取FRM檔案" uses, so the wafer bin map can be checked/copied out on its
// own — plus the "顯示/複製座標文字" affordance STRATE補檔頁 already has,
// which is the more literal reading of "下載" (there's nothing to actually
// download as a file here, same as the main page's own wafer grid, but
// copy-to-clipboard text in the established x,y,bin format covers the
// same need — paste-able straight into the main page's manual textarea).
let lastWaferPasteText = "";

// Convenience auto-fill (2026/08/19): converts "目視檢查"'s own "Ref.
// Point" reading into T點 X/Y — see app.js's waferDimsByPanel comment for
// the formula/derivation (confirmed against a real example: Ref. Point
// (-10, 1) on a 46x24 wafer -> DB-rule (45, 14), matching
// WaferCoordinate.exe's own display exactly). Not a replacement for the
// manual T點 fields — just saves doing this arithmetic by hand; still
// only confirmed against one example.
function convertVisualRefPoint() {
  if (!lastWaferData) {
    document.getElementById("mp-preview-status").className = "error";
    document.getElementById("mp-preview-status").textContent = "請先預覽/讀取wafer MAP，才知道columns/rows可以換算";
    return;
  }
  const refX = parseInt(document.getElementById("mp-visual-ref-x").value, 10);
  const refY = parseInt(document.getElementById("mp-visual-ref-y").value, 10);
  if (!Number.isFinite(refX) || !Number.isFinite(refY)) {
    document.getElementById("mp-preview-status").className = "error";
    document.getElementById("mp-preview-status").textContent = "請先填目視檢查顯示的Ref. Point X跟Y";
    return;
  }
  document.getElementById("mp-t-point-x").value = lastWaferData.columns - refY;
  document.getElementById("mp-t-point-y").value = lastWaferData.rows + refX;
  saveState(); // setting .value in JS doesn't fire "input", so this won't auto-save otherwise
  renderWaferGrid(lastWaferData);
}

function renderWaferGrid(wafer) {
  const panel = document.getElementById("mispick-wafer-panel");
  const container = document.getElementById("mp-wafer-grid");
  container.innerHTML = "";
  if (!wafer || !wafer.cells || !wafer.cells.length) {
    panel.style.display = "none";
    return;
  }
  lastWaferData = wafer;
  panel.style.display = "";
  lastWaferPasteText = wafer.cells
    .slice()
    .sort((a, b) => a.x - b.x || a.y - b.y)
    .map((c) => `${c.x},${c.y},${c.bin}`)
    .join("\n");
  document.getElementById("mp-wafer-text").value = lastWaferPasteText;

  const cellMap = new Map(wafer.cells.map((c) => [`${c.x},${c.y}`, c.bin]));
  renderBinLegend("mp-wafer-bin-legend", cellMap);
  const xs = wafer.cells.map((c) => c.x);
  const ys = wafer.cells.map((c) => c.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);

  // T點 (2026/08/19 ask: "誤吸的圖檔沒有顯示T點 要補充出來這樣我才知道
  // 移動的位置在哪裡") — originally computed from reference_point_x via
  // the same formula as app.js's main-page marker, but 2026/08/19 later
  // that day: decompiled the real WaferCoordinate.exe (user provided the
  // .exe itself) and confirmed ReferencePointX/Y are parsed from the FRM
  // file but never referenced anywhere in its drawing code — the real
  // tool doesn't compute or mark a T點 from them at all. The user
  // explained their own method: eyeballing the (purely geometric) center
  // crosshair against where bin7/bin1 fall nearby — a manual visual call,
  // not a derivable value. So this is a manual input now (see
  // #mp-t-point-x/y), read fresh on every render, same as app.js's
  // currentRefPoint().
  const tx = parseInt(document.getElementById("mp-t-point-x").value, 10);
  const ty = parseInt(document.getElementById("mp-t-point-y").value, 10);
  const refPoint = Number.isFinite(tx) && Number.isFinite(ty) ? { x: tx, y: ty } : null;
  document.getElementById("mp-wafer-tpoint-legend").style.display = refPoint ? "" : "none";
  document.getElementById("mp-wafer-info").textContent =
    `LotNo=${wafer.lot_no} WaferID=${wafer.wafer_id}（${wafer.columns}x${wafer.rows}，共${wafer.cells.length}顆有資料）`;

  const xOrder = [];
  for (let x = minX; x <= maxX; x++) xOrder.push(x);
  if (mpFlipX) xOrder.reverse();
  const yOrder = [];
  for (let y = minY; y <= maxY; y++) yOrder.push(y);
  if (mpFlipY) yOrder.reverse();

  const headerRow = document.createElement("div");
  headerRow.className = "wafer-row";
  const corner = document.createElement("div");
  corner.className = "grid-axis-cell grid-axis-corner";
  headerRow.appendChild(corner);
  for (const x of xOrder) {
    const label = document.createElement("div");
    label.className = "grid-axis-cell";
    label.textContent = x;
    headerRow.appendChild(label);
  }
  container.appendChild(headerRow);

  for (const y of yOrder) {
    const row = document.createElement("div");
    row.className = "wafer-row";
    const rowLabel = document.createElement("div");
    rowLabel.className = "grid-axis-cell";
    rowLabel.textContent = y;
    row.appendChild(rowLabel);
    for (const x of xOrder) {
      const bin = cellMap.get(`${x},${y}`);
      const cell = document.createElement("div");
      cell.className = "wafer-cell";
      applyBinColor(cell, bin);
      cell.title = `${x}:${y}`;
      if (refPoint && refPoint.x === x && refPoint.y === y) {
        cell.classList.add("ref-point");
        cell.textContent = "T";
        cell.title = `${x}:${y} — T點`;
      }
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

function renderStrateFileList() {
  const el = document.getElementById("mp-strate-file-list");
  el.innerHTML = pendingStrateFiles
    .map(
      (f, i) =>
        `<span class="badge" style="margin:0.15rem">${f.name}　<a href="#" data-idx="${i}" class="mp-remove-strate-file" style="color:var(--danger,#dc2626)">移除</a></span>`
    )
    .join("");
  el.querySelectorAll(".mp-remove-strate-file").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      pendingStrateFiles.splice(Number(a.dataset.idx), 1);
      renderStrateFileList();
      document.getElementById("mp-btn-clear-strate-files").style.display = pendingStrateFiles.length ? "" : "none";
    });
  });
  document.getElementById("mp-btn-clear-strate-files").style.display = pendingStrateFiles.length ? "" : "none";
}

async function analyze() {
  const status = document.getElementById("mp-status");
  status.className = "";
  status.textContent = "分析中...";
  document.getElementById("mp-btn-download-csv").style.display = "none";
  lastCsv = null;

  let strateFiles;
  if (pendingStrateFiles.length) {
    strateFiles = [];
    for (const f of pendingStrateFiles) {
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

async function previewWaferMap() {
  const status = document.getElementById("mp-preview-status");
  status.className = "";
  status.textContent = "讀取中...";

  const payload = {
    lot_no: document.getElementById("mp_frm_lot_no").value,
    barcode_id: document.getElementById("mp_frm_barcode_id").value,
    frm_path: document.getElementById("mp_frm_path").value,
  };
  const res = await fetch("/api/frm", {
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

  // 2026/08/25：跟app.js同一次更正(見那邊resetWaferFlip的完整註解)——換一片
  // wafer要重設方向勾選框，不然上一片wafer調過的方向會無聲無息帶到這一片。
  mpFlipX = true;
  mpFlipY = false;
  document.getElementById("mp-wafer-flip-x").checked = true;
  document.getElementById("mp-wafer-flip-y").checked = false;
  renderWaferGrid(data);
  status.className = "ok";
  status.textContent = `已載入 LotNo=${data.lot_no} WaferID=${data.wafer_id}（${data.columns}x${data.rows}，共${data.cells.length}顆有資料）`;
  saveState();
}

document.getElementById("mp_strate_files").addEventListener("change", (e) => {
  const newFiles = [...(e.target.files || [])];
  for (const f of newFiles) {
    const alreadyIn = pendingStrateFiles.some((existing) => existing.name === f.name && existing.size === f.size);
    if (!alreadyIn) pendingStrateFiles.push(f);
  }
  e.target.value = ""; // allows re-picking the same file later and still firing "change"
  renderStrateFileList();
});
document.getElementById("mp-btn-clear-strate-files").addEventListener("click", () => {
  pendingStrateFiles = [];
  renderStrateFileList();
});

document.getElementById("mp-btn-preview-wafer").addEventListener("click", previewWaferMap);
document.getElementById("mp-btn-toggle-wafer-text").addEventListener("click", () => {
  const textarea = document.getElementById("mp-wafer-text");
  const copyBtn = document.getElementById("mp-btn-copy-wafer-text");
  const showing = textarea.style.display !== "none";
  textarea.style.display = showing ? "none" : "";
  copyBtn.style.display = showing ? "none" : "";
});
document.getElementById("mp-btn-copy-wafer-text").addEventListener("click", async () => {
  const copyBtn = document.getElementById("mp-btn-copy-wafer-text");
  const textarea = document.getElementById("mp-wafer-text");
  try {
    await navigator.clipboard.writeText(lastWaferPasteText);
    copyBtn.textContent = "已複製！";
  } catch (err) {
    textarea.select();
    copyBtn.textContent = "複製失敗，請手動選取文字複製";
  }
  setTimeout(() => {
    copyBtn.textContent = "複製到剪貼簿";
  }, 2000);
});

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
  "mp-t-point-x", "mp-t-point-y",
  "mp-visual-ref-x", "mp-visual-ref-y",
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

// T點 fields need a live re-render (not just a save) on every keystroke,
// so the marker moves as the user types in wherever they've determined it
// to be — re-renders whichever wafer is already showing, if any.
document.getElementById("mp-t-point-x").addEventListener("input", () => renderWaferGrid(lastWaferData));
document.getElementById("mp-t-point-y").addEventListener("input", () => renderWaferGrid(lastWaferData));
document.getElementById("mp-btn-convert-visual-ref").addEventListener("click", convertVisualRefPoint);
document.getElementById("mp-wafer-flip-x").addEventListener("change", (e) => {
  mpFlipX = e.target.checked;
  renderWaferGrid(lastWaferData);
});
document.getElementById("mp-wafer-flip-y").addEventListener("change", (e) => {
  mpFlipY = e.target.checked;
  renderWaferGrid(lastWaferData);
});

restoreState();
