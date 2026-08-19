// ④ STRATE補檔 XML合併 — extract already-complete substrate data and
// wafer bin maps directly from a SECS/AFC transaction log (see
// bingomap/secs_log.py). The log's real encoding is UTF-16LE with no
// BOM, which a plain `file.text()` read mis-decodes (same failure mode
// as reading the raw bytes as ASCII) — so the file is sent as base64 and
// decoded server-side by decode_secs_log() instead of trusting the
// browser's own text decoding.
let lastLogBase64 = null;

function arrayBufferToBase64(buf) {
  let binary = "";
  const bytes = new Uint8Array(buf);
  const chunkSize = 0x8000; // avoid call-stack limits on String.fromCharCode for large files
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

// Same palette/letter convention as the main page's "參考同一片wafer的
//其他基板" overlay (app.js) — reused here to answer the follow-up ask
// "讓我知道對應你一枚strate": render the wafer bin map as an actual grid
// and color each substrate's own die positions in on it, so it's visibly
// obvious which cells on the wafer belong to which extracted substrate.
const SUBSTRATE_COLORS = ["#e04b4b", "#0ea5a5", "#a855f7", "#ca8a04", "#059669", "#e0459e", "#0891b2", "#65a30d"];

function substrateLetter(i) {
  return i < 26 ? String.fromCharCode(65 + i) : `S${i + 1}`;
}

function cellClass(bin) {
  if (bin === "1") return "bin-1";
  if (bin === undefined) return "";
  return "bin-other";
}

const GRID_AXIS_SIZE = 20; // must match .grid-axis-cell's width/height in style.css

// containerId: element to render the grid into. wm: one wafer_maps entry
// (columns/rows/cells). matchedSubstrates: [{label, color, name,
// positions: Set("x,y")}] — already-assigned colors/letters for the
// substrates that came from this same wafer (matched by wafer_ring ===
// frame_id in renderWaferMaps()).
// 2026/08/18: the user reported a batch of substrates' overlaid positions
// rendering outside the wafer's visible boundary and suspected an axis
// mix-up — pointed back at the real .frm-file convention as "the correct
// one" to follow. Checked: the FRM tool's own status bar (see the T點
// investigation in the main page) confirms COL is the HORIZONTAL axis,
// ROW is VERTICAL — but bingomap/secs_log.py's wafer_map_from_element()
// stores cells keyed by DIE_INFO's own "X:Y" labels directly (x = row
// index 0..RowCount-1, y = column-position-within-row 0..ColCount-1, see
// its own module docstring) — DIE_INFO's "X" and "Y" labels do NOT line
// up with which axis is horizontal vs vertical on screen. This function
// must render whichever field actually has ColCount's cardinality (y,
// here) horizontally and RowCount's cardinality (x) vertically — NOT
// just "x horizontal" by name, or the whole picture renders rotated 90°
// with overlay dots landing in the (real, populated-shape-shaped) blank
// corners of that rotated rectangle, exactly matching what was reported.
function renderWaferGrid(containerId, wm, matchedSubstrates) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  if (!wm.cells.length) return;

  const cellMap = new Map(wm.cells.map((c) => [`${c.x},${c.y}`, c.bin]));
  const rowVals = wm.cells.map((c) => c.x); // RowCount-sized axis -> vertical
  const colVals = wm.cells.map((c) => c.y); // ColCount-sized axis -> horizontal
  const minRow = Math.min(...rowVals), maxRow = Math.max(...rowVals);
  const minCol = Math.min(...colVals), maxCol = Math.max(...colVals);

  const headerRow = document.createElement("div");
  headerRow.className = "wafer-row";
  const corner = document.createElement("div");
  corner.className = "grid-axis-cell grid-axis-corner";
  headerRow.appendChild(corner);
  for (let col = maxCol; col >= minCol; col--) {
    const label = document.createElement("div");
    label.className = "grid-axis-cell";
    label.textContent = col;
    headerRow.appendChild(label);
  }
  container.appendChild(headerRow);

  for (let row = minRow; row <= maxRow; row++) {
    const rowEl = document.createElement("div");
    rowEl.className = "wafer-row";
    const rowLabel = document.createElement("div");
    rowLabel.className = "grid-axis-cell";
    rowLabel.textContent = row;
    rowEl.appendChild(rowLabel);
    for (let col = maxCol; col >= minCol; col--) {
      const bin = cellMap.get(`${row},${col}`);
      const cell = document.createElement("div");
      cell.className = "wafer-cell " + cellClass(bin);
      const key = `${row},${col}`;
      const owner = matchedSubstrates.find((s) => s.positions.has(key));
      if (owner) {
        cell.classList.add("referenced");
        cell.style.setProperty("--ref-color", owner.color);
        cell.textContent = owner.label;
        cell.title = `${row}:${col} — 基板「${owner.name}」`;
      } else {
        cell.title = `${row}:${col}`;
      }
      rowEl.appendChild(cell);
    }
    container.appendChild(rowEl);
  }
}

function renderWaferLegend(containerId, matchedSubstrates) {
  const el = document.getElementById(containerId);
  if (!matchedSubstrates.length) {
    el.innerHTML = '<span class="small">這片wafer在上面的StrateMap清單裡沒有找到對應的基板。</span>';
    return;
  }
  el.innerHTML = matchedSubstrates
    .map((s) => `<span><i style="background:${s.color};border-color:${s.color}"></i>${s.label} = ${s.name}（${s.positions.size}顆）</span>`)
    .join("");
}

function downloadText(filename, text) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function renderSubstrates(substrates) {
  const panel = document.getElementById("sx-substrates-panel");
  const tbody = document.querySelector("#sx-substrates-table tbody");
  tbody.innerHTML = "";
  document.getElementById("sx-substrate-count").textContent = substrates.length;
  panel.style.display = substrates.length ? "" : "none";

  substrates.forEach((s) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${s.index + 1}</td><td>${s.substrate_id}</td><td>${s.wafer_ring}</td><td>${s.eqpid}</td>` +
      `<td>${s.num_dies}</td><td>${s.num_other_layer_dies}</td><td>${s.total_bond_die_qty}</td><td>${s.good_die}</td>` +
      `<td>${s.last_timestamp}</td><td><button type="button" class="secondary sx-btn-download-one">下載</button></td>`;
    tr.querySelector(".sx-btn-download-one").addEventListener("click", () => downloadText(s.filename, s.text));
    tbody.appendChild(tr);
  });
}

function renderWaferMaps(waferMaps, substrates) {
  const panel = document.getElementById("sx-wafer-maps-panel");
  const list = document.getElementById("sx-wafer-maps-list");
  list.innerHTML = "";
  document.getElementById("sx-wafer-map-count").textContent = waferMaps.length;
  panel.style.display = waferMaps.length ? "" : "none";

  waferMaps.forEach((wm) => {
    // Substrates whose wafer_ring matches this wafer's own frame_id —
    // the answer to "讓我知道對應你一枚strate": these are the substrates
    // this specific wafer's dies were bonded into.
    const owners = substrates.filter((s) => s.wafer_ring === wm.frame_id);
    const matchedSubstrates = owners.map((s, i) => ({
      label: substrateLetter(i),
      color: SUBSTRATE_COLORS[i % SUBSTRATE_COLORS.length],
      name: s.substrate_id || `#${s.index + 1}`,
      positions: new Set(s.die_positions.map((p) => `${p.x},${p.y}`)),
    }));

    const box = document.createElement("div");
    box.className = "notice";
    box.style.marginTop = "0.6rem";
    const textareaId = `sx-wafer-map-text-${wm.index}`;
    const gridId = `sx-wafer-map-grid-${wm.index}`;
    const legendId = `sx-wafer-map-legend-${wm.index}`;
    box.innerHTML =
      `<b>Frame ID：${wm.frame_id}</b>　Wafer ID：${wm.wafer_id}　尺寸：${wm.columns}x${wm.rows}　有資料的格子：${wm.num_cells}顆<br>` +
      `<button type="button" class="secondary sx-btn-toggle-text">顯示/複製座標文字</button>` +
      `<button type="button" class="secondary sx-btn-copy-text" style="display:none">複製到剪貼簿</button>` +
      `<textarea id="${textareaId}" rows="6" readonly style="display:none;width:100%;margin-top:0.4rem"></textarea>` +
      `<div class="legend" id="${legendId}" style="margin-top:0.6rem"></div>` +
      `<div class="lyr-wafer-wrap"><div id="${gridId}" class="lyr-wafer-grid"></div></div>`;
    const textarea = box.querySelector(`#${textareaId}`);
    textarea.value = wm.paste_text;
    const toggleBtn = box.querySelector(".sx-btn-toggle-text");
    const copyBtn = box.querySelector(".sx-btn-copy-text");
    toggleBtn.addEventListener("click", () => {
      const showing = textarea.style.display !== "none";
      textarea.style.display = showing ? "none" : "";
      copyBtn.style.display = showing ? "none" : "";
    });
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(wm.paste_text);
        copyBtn.textContent = "已複製！";
      } catch (err) {
        textarea.select();
        copyBtn.textContent = "複製失敗，請手動選取文字複製";
      }
      setTimeout(() => {
        copyBtn.textContent = "複製到剪貼簿";
      }, 2000);
    });
    list.appendChild(box);

    renderWaferLegend(legendId, matchedSubstrates);
    renderWaferGrid(gridId, wm, matchedSubstrates);
  });
}

async function extractLog() {
  const status = document.getElementById("sx-status");
  const fileInput = document.getElementById("sx_log_file");
  const file = fileInput.files && fileInput.files[0];
  if (!file) {
    status.className = "error";
    status.textContent = "請先選擇一個log檔案";
    return;
  }

  status.className = "";
  status.textContent = "讀取中...";

  const buf = await file.arrayBuffer();
  lastLogBase64 = arrayBufferToBase64(buf);

  const res = await fetch("/api/strate_xml/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ log_base64: lastLogBase64 }),
  });
  const data = await res.json();
  if (!res.ok) {
    status.className = "error";
    status.textContent = data.error;
    return;
  }

  renderSubstrates(data.substrates);
  renderWaferMaps(data.wafer_maps, data.substrates);
  saveState(file.name, lastLogBase64, data);

  status.className = "ok";
  status.textContent = `解析完成：共找到 ${data.substrates.length} 筆基板資料、${data.wafer_maps.length} 筆wafer bin map資料。`;
}

// ---- Persistence (2026/08/18 ask: "我切換分頁的時候檔案不要不見") ----
// This is a plain multi-page app (each nav tab is a full page load, not
// an SPA) — navigating away and back always re-runs this script from
// scratch. Since the actual File the user picked can't be restored (the
// browser won't let a page re-populate a file input for security
// reasons), what's saved instead is the EXTRACTED RESULT (small — mostly
// text — even for the real 29-substrate/10-wafer log) so the page can
// redraw itself immediately without asking for a re-upload. The raw log
// itself (base64, potentially several MB) is saved too on a best-effort
// basis so "全部下載(.zip)" keeps working after a restore — if it doesn't
// fit under localStorage's quota, everything else still restores, only
// the zip button then needs a fresh upload (explained in the status
// text). localStorage (not sessionStorage) so a reload or coming back
// tomorrow still finds it, not just a same-session tab switch.
const SX_STORAGE_RESULT = "bingomap_strate_xml_result";
const SX_STORAGE_LOG = "bingomap_strate_xml_log_base64";
const SX_STORAGE_FILENAME = "bingomap_strate_xml_filename";

function saveState(filename, logBase64, data) {
  try {
    localStorage.setItem(SX_STORAGE_RESULT, JSON.stringify(data));
    localStorage.setItem(SX_STORAGE_FILENAME, filename);
  } catch (err) {
    return; // localStorage unavailable entirely (private mode etc.) — just don't persist
  }
  try {
    localStorage.setItem(SX_STORAGE_LOG, logBase64);
  } catch (err) {
    localStorage.removeItem(SX_STORAGE_LOG); // too large for quota — drop it, keep the rest
  }
}

function restoreState() {
  const raw = localStorage.getItem(SX_STORAGE_RESULT);
  if (!raw) return;
  let data;
  try {
    data = JSON.parse(raw);
  } catch (err) {
    return;
  }
  lastLogBase64 = localStorage.getItem(SX_STORAGE_LOG); // may be null — see saveState()
  const filename = localStorage.getItem(SX_STORAGE_FILENAME) || "";

  renderSubstrates(data.substrates);
  renderWaferMaps(data.wafer_maps, data.substrates);

  const status = document.getElementById("sx-status");
  status.className = "ok";
  const zipNote = lastLogBase64 ? "" : "（檔案內容太大沒能一起保留，「全部下載zip」要重新選一次同一個log檔案才能用）";
  status.textContent =
    `已還原上次解析過的結果${filename ? `（${filename}）` : ""}：共 ${data.substrates.length} 筆基板資料、` +
    `${data.wafer_maps.length} 筆wafer bin map資料。${zipNote}`;
}

async function downloadZip() {
  const status = document.getElementById("sx-status");
  if (!lastLogBase64) {
    status.className = "error";
    status.textContent = "請先解析log";
    return;
  }
  const res = await fetch("/api/strate_xml/download_zip", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ log_base64: lastLogBase64 }),
  });
  if (!res.ok) {
    const data = await res.json();
    status.className = "error";
    status.textContent = data.error;
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "strate_xml_extract.zip";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

document.getElementById("sx-btn-extract").addEventListener("click", extractLog);
document.getElementById("sx-btn-download-zip").addEventListener("click", downloadZip);
restoreState();
