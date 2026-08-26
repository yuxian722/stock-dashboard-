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

const GRID_AXIS_SIZE = 20; // must match .grid-axis-cell's width/height in style.css

// T點 for this log's own layout (EU014). Not derivable from the log
// itself (WaferStart's T2_POINT is always "NA" here) — confirmed
// 2026/08/19 against a real screenshot of the actual "WaferCoordinate"
// tool (this project's whole namesake, decompiled in frm_reader.py — NOT
// the separate "目視檢查" viewer) for wafer FC2643: its own "position"
// readout showed X:46, Y:15 (1-based, out of its own Columns=46/Rows=24)
// while hovering the T點 mark, i.e. (col=45, row=14) 0-based.
//
// 2026/08/21大更正：這裡原本寫的是`{x:14,y:45}`，是套用log的DIE_INFO
// 原始row:col座標算出來的——但那時候還沒發現DIE_INFO的wafer_xy其實是
// row:col、不是.strate標準格式的col:row(見bingomap/secs_log.py的
// `_swap_wafer_xy()`docstring)。修正這個座標系統之後(renderWaferGrid
// 現在跟這個網站其他頁面一樣，x=欄/col、y=列/row)，T點座標本身當然也
// 要對應改成`(col=45, row=14)`——巧合的是，這剛好跟①補資料頁2026/08/20
// 用完全獨立的另一組真實資料(目視檢查Ref.Point換算成DB規則)反推出來的
// 公式一致：`T點X = columns - Ref.Y = 46-1 = 45`、
// `T點Y = rows + Ref.X = 24+(-10) = 14`——兩條完全不同的調查路線
// 得到同一個答案，等於互相佐證這次的修正方向是對的。
const SECS_T_POINT = { x: 45, y: 14 };

// containerId: element to render the grid into. wm: one wafer_maps entry
// (columns/rows/cells). matchedSubstrates: [{label, color, name,
// positions: Set("x,y")}] — already-assigned colors/letters for the
// substrates that came from this same wafer (matched by wafer_ring ===
// frame_id in renderWaferMaps()).
// 2026/08/18-19: the user reported substrates' overlaid positions
// rendering outside the wafer's visible boundary and pointed at needing
// to match "the wafer coordinate file"'s own orientation — this round of
// guessing settled (wrongly, see below) on treating DIE_INFO's raw first
// wafer_xy component as the vertical/RowCount axis and the second as the
// horizontal/ColCount axis, matching WaferCoordinate.exe's own
// Columns=46/Rows=24 landscape rendering.
//
// 2026/08/21大更正：問題不是這裡的水平/垂直方向選錯，是根本欄位語意
// 搞反了——反編譯/交叉比對真實資料才發現，log的`<DIE_INFO>`原始
// `wafer_xy`欄位本身是`row:col`，但`.strate`檔案格式的`wafer_xy`標準
// 是`col:row`(直接等於wafer MAP座標，DB規則不用轉換，見
// `bingomap/secs_log.py`的`_swap_wafer_xy()`)——`bingomap/secs_log.py`
// 現在已經把這個欄位語意在後端統一成`col:row`(呼叫端這裡收到的
// `wm.cells`/`s.die_positions`都已經是`{x:col, y:row}`，跟這個網站
// 其他頁面的wafer座標慣例一致)，這裡只要跟著把「x當col(水平)、
// y當row(垂直)」畫，不用再自己另外判斷方向。
// 2026/08/25：使用者在①補資料/②誤吸偏移頁拿掉X/Y軸反轉勾選框、改成
// 0/90/180/270度角度選單之後，直接說「其他分頁也一樣」——這裡的wafer圖
// 跟那兩頁是同一種東西(真實wafer bin座標)，所以套用同一套設計：排列
// 順序永遠固定(欄0在右邊、列0在最上面，見renderWaferGrid()本來就是這樣
// 寫死的，不用改)，角度選單改變的是直接重新計算每一顆die的座標，跟另外
// 兩頁的rotateWaferCells()/rotateWaferArray()用同一條公式。因為這裡除了
// wafer bin資料本身，還會疊一層「哪些格子屬於哪個基板」的顏色標示
// (matchedSubstrates)，兩者用的是同一個wafer、同一個座標系統，所以要
// 一起旋轉，不然基板標示會跟旋轉後的bin顏色對不齊。
// 2026/08/26：跟app.js/mispick.js同一次更正——角度只能旋轉，湊不出鏡像，
// 使用者比對真正的WaferCoordinate.exe後回報圖是鏡像的，加一個獨立的
// mirror參數，對旋轉後的座標再做一次水平翻轉。
function rotateWaferMapAndSubstrates(wm, matchedSubstrates, angleDeg, mirror) {
  if (!wm.cells.length) return { wm, matchedSubstrates };
  const xs = wm.cells.map((c) => c.x);
  const ys = wm.cells.map((c) => c.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const spanX = maxX - minX, spanY = maxY - minY;
  const rotatedSpanX = angleDeg === 90 || angleDeg === 270 ? spanY : spanX;
  const rotatePoint = (x, y) => {
    const u = x - minX, v = y - minY;
    let nu, nv;
    if (angleDeg === 90) { nu = v; nv = spanX - u; }
    else if (angleDeg === 180) { nu = spanX - u; nv = spanY - v; }
    else if (angleDeg === 270) { nu = spanY - v; nv = u; }
    else { nu = u; nv = v; } // 0
    if (mirror) nu = rotatedSpanX - nu;
    return [nu, nv];
  };
  const cells = wm.cells.map((c) => {
    const [nx, ny] = rotatePoint(c.x, c.y);
    return { x: nx, y: ny, bin: c.bin };
  });
  const pasteText = cells
    .slice()
    .sort((a, b) => a.x - b.x || a.y - b.y)
    .map((c) => `${c.x},${c.y},${c.bin}`)
    .join("\n");
  const newWm = {
    ...wm,
    cells,
    paste_text: pasteText,
    columns: angleDeg === 90 || angleDeg === 270 ? wm.rows : wm.columns,
    rows: angleDeg === 90 || angleDeg === 270 ? wm.columns : wm.rows,
  };
  const newMatched = matchedSubstrates.map((s) => ({
    ...s,
    positions: new Set(
      [...s.positions].map((key) => {
        const [x, y] = key.split(",").map(Number);
        const [nx, ny] = rotatePoint(x, y);
        return `${nx},${ny}`;
      })
    ),
  }));
  return { wm: newWm, matchedSubstrates: newMatched };
}

function renderWaferGrid(containerId, wm, matchedSubstrates) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  if (!wm.cells.length) return;

  const cellMap = new Map(wm.cells.map((c) => [`${c.x},${c.y}`, c.bin]));
  renderBinLegend(`${containerId}-bin-legend`, cellMap);
  const colVals = wm.cells.map((c) => c.x); // ColCount-sized axis -> horizontal
  const rowVals = wm.cells.map((c) => c.y); // RowCount-sized axis -> vertical
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
      const bin = cellMap.get(`${col},${row}`);
      const cell = document.createElement("div");
      cell.className = "wafer-cell";
      applyBinColor(cell, bin);
      const key = `${col},${row}`;
      const owner = matchedSubstrates.find((s) => s.positions.has(key));
      const isTPoint = col === SECS_T_POINT.x && row === SECS_T_POINT.y;
      if (isTPoint) cell.classList.add("ref-point");
      if (owner) {
        cell.classList.add("referenced");
        cell.style.setProperty("--ref-color", owner.color);
        cell.textContent = owner.label;
        cell.title = `${col}:${row}${isTPoint ? " — T點" : ""} — 基板「${owner.name}」`;
      } else if (isTPoint) {
        cell.textContent = "T";
        cell.title = `${col}:${row} — T點`;
      } else {
        cell.title = `${col}:${row}`;
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
    const angleId = `sx-wafer-map-angle-${wm.index}`;
    const mirrorId = `sx-wafer-map-mirror-${wm.index}`;
    box.innerHTML =
      `<b>Frame ID：${wm.frame_id}</b>　Wafer ID：${wm.wafer_id}　尺寸：${wm.columns}x${wm.rows}　有資料的格子：${wm.num_cells}顆<br>` +
      `<button type="button" class="secondary sx-btn-toggle-text">顯示/複製座標文字</button>` +
      `<button type="button" class="secondary sx-btn-copy-text" style="display:none">複製到剪貼簿</button>` +
      `<textarea id="${textareaId}" rows="6" readonly style="display:none;width:100%;margin-top:0.4rem"></textarea>` +
      `<label style="margin-top:0.4rem;display:inline-block">wafer角度（座標0,0固定右上角，不受角度/鏡像影響）
        <select id="${angleId}">
          <option value="0" selected>0°</option>
          <option value="90">90°</option>
          <option value="180">180°</option>
          <option value="270">270°</option>
        </select>
      </label>` +
      `<label style="margin-left:0.6rem"><input type="checkbox" id="${mirrorId}"> 鏡像</label>` +
      `<div class="legend" id="${gridId}-bin-legend" style="margin-top:0.6rem"></div>` +
      `<div class="legend" id="${legendId}" style="margin-top:0.2rem"></div>` +
      `<div class="lyr-wafer-wrap"><div id="${gridId}" class="lyr-wafer-grid"></div></div>`;
    const textarea = box.querySelector(`#${textareaId}`);
    const toggleBtn = box.querySelector(".sx-btn-toggle-text");
    const copyBtn = box.querySelector(".sx-btn-copy-text");
    toggleBtn.addEventListener("click", () => {
      const showing = textarea.style.display !== "none";
      textarea.style.display = showing ? "none" : "";
      copyBtn.style.display = showing ? "none" : "";
    });
    let currentPasteText = wm.paste_text;
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(currentPasteText);
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

    const rerender = () => {
      const angleDeg = Number(box.querySelector(`#${angleId}`).value);
      const mirror = box.querySelector(`#${mirrorId}`).checked;
      const rotated = rotateWaferMapAndSubstrates(wm, matchedSubstrates, angleDeg, mirror);
      currentPasteText = rotated.wm.paste_text;
      textarea.value = currentPasteText;
      renderWaferLegend(legendId, rotated.matchedSubstrates);
      renderWaferGrid(gridId, rotated.wm, rotated.matchedSubstrates);
    };
    box.querySelector(`#${angleId}`).addEventListener("change", rerender);
    box.querySelector(`#${mirrorId}`).addEventListener("change", rerender);
    rerender();
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
