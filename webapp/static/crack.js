let strateFiles = []; // {name, text}[]
let markedKeys = []; // ordered — crack numbering is just this order, 1-based
let focusWaferId = null;
let currentDocIndex = 0;
let lastData = null;
let lastCsv = null;

async function loadFiles() {
  const files = [...(document.getElementById("ck_strate_files").files || [])];
  const status = document.getElementById("ck-status");
  if (!files.length) {
    status.className = "error";
    status.textContent = "請至少選擇一份STRATE檔案";
    return;
  }
  strateFiles = [];
  for (const f of files) {
    strateFiles.push({ name: f.name, text: await f.text() });
  }
  markedKeys = [];
  focusWaferId = null;
  currentDocIndex = 0;
  await analyze();
}

async function analyze() {
  const status = document.getElementById("ck-status");
  status.className = "";
  status.textContent = "分析中...";

  const payload = {
    strate_files: strateFiles,
    marked_keys: markedKeys,
    focus_wafer_id: focusWaferId,
  };
  const res = await fetch("/api/crack/analyze", {
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

  lastData = data;
  focusWaferId = data.focus_wafer_id;
  if (currentDocIndex >= data.docs.length) currentDocIndex = 0;
  lastCsv = data.csv;

  status.className = "ok";
  status.textContent = `已載入 ${data.docs.length} 份STRATE，共 ${data.wafer_ids.length} 個完整Wafer ID，Crack：${markedKeys.length}點`;

  renderDocSelect(data);
  renderWaferSelect(data);
  renderStripGrid(data.docs[currentDocIndex]);
  renderWaferGrid(data.scatter);
  renderCrackTable(data.crack_table);
  document.getElementById("ck-btn-download-csv").style.display = data.crack_table.length ? "" : "none";
  saveState();
}

function renderDocSelect(data) {
  const sel = document.getElementById("ck_doc_select");
  sel.innerHTML = "";
  data.docs.forEach((d, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `${d.substrate_id}（${d.name}，${d.cells.length}筆可標記）`;
    sel.appendChild(opt);
  });
  sel.value = currentDocIndex;
}

function renderWaferSelect(data) {
  const sel = document.getElementById("ck_wafer_select");
  sel.innerHTML = "";
  data.wafer_ids.forEach((id) => {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = id;
    sel.appendChild(opt);
  });
  sel.value = focusWaferId;
}

function renderStripGrid(doc) {
  const container = document.getElementById("ck-strip-grid");
  container.innerHTML = "";
  if (!doc) return;

  const cellByPos = new Map(doc.cells.map((c) => [`${c.output_x}:${c.output_y}`, c]));
  const markedSet = new Set(markedKeys);

  const headerRow = document.createElement("div");
  headerRow.className = "wafer-row";
  const corner = document.createElement("div");
  corner.className = "substrate-axis-cell substrate-axis-corner";
  headerRow.appendChild(corner);
  for (let x = 0; x < doc.column; x++) {
    const label = document.createElement("div");
    label.className = "substrate-axis-cell";
    label.textContent = x;
    headerRow.appendChild(label);
  }
  container.appendChild(headerRow);

  for (let y = 0; y < doc.row; y++) {
    const rowEl = document.createElement("div");
    rowEl.className = "wafer-row";
    const rowLabel = document.createElement("div");
    rowLabel.className = "substrate-axis-cell";
    rowLabel.textContent = y + 1;
    rowEl.appendChild(rowLabel);
    for (let x = 0; x < doc.column; x++) {
      const cell = cellByPos.get(`${x}:${y}`);
      const el = document.createElement("div");
      el.className = "substrate-cell";
      if (!cell) {
        el.style.background = "#e5e7eb";
        el.title = "無資料，不能標記Crack";
      } else {
        el.dataset.key = cell.key;
        el.title = `${cell.output_coord}｜TX:TY ${cell.tx}:${cell.ty}｜Wafer ${cell.wafer_id} FX:FY ${cell.fx}:${cell.fy}`;
        if (markedSet.has(cell.key)) {
          // 跟renderWaferGrid()同一次修正(2026/08/21)：淡橘色太淺看不清楚，
          // 改成飽和紅色+白色粗體，兩邊Crack標示保持一致。
          el.style.background = "#ef4444";
          el.style.borderColor = "#991b1b";
          el.style.color = "#fff";
          el.style.fontWeight = "700";
          el.textContent = "C" + (markedKeys.indexOf(cell.key) + 1);
        }
      }
      rowEl.appendChild(el);
    }
    container.appendChild(rowEl);
  }
}

function renderWaferGrid(scatter) {
  const container = document.getElementById("ck-wafer-grid");
  const info = document.getElementById("ck-wafer-info");
  container.innerHTML = "";
  if (!scatter || !scatter.points.length) {
    info.textContent = "";
    return;
  }
  const xs = scatter.points.map((p) => p.x);
  const ys = scatter.points.map((p) => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  info.textContent = `已匯入 ${scatter.points.length} 個相異座標點｜NOTCH=${scatter.notch}｜局部座標範圍 X ${minX}~${maxX}、Y ${minY}~${maxY}（僅相對位置，非完整wafer絕對座標）`;

  const byPos = new Map(scatter.points.map((p) => [`${p.x}:${p.y}`, p]));
  for (let y = minY; y <= maxY; y++) {
    const rowEl = document.createElement("div");
    rowEl.className = "wafer-row";
    for (let x = minX; x <= maxX; x++) {
      const p = byPos.get(`${x}:${y}`);
      const el = document.createElement("div");
      el.className = "substrate-cell";
      if (p) {
        // 2026/08/21使用者回報「Crack的顏色太淺 看不清楚 綠色跟其他圖檔不一樣」
        // ——原本的淡綠色(#dcfce7)/淡橘色(#ffedd5)是這頁自己配的，跟其他頁面
        // wafer圖用的鮮綠色(#13ff13，真正WaferCoordinate.exe的bin1顏色)不一致，
        // 縮小畫面/截圖時幾乎看不出來。改成跟其他頁面一致的鮮綠色，Crack格子
        // 改成飽和紅色+白色粗體文字，對比更明顯。
        el.style.background = p.is_crack ? "#ef4444" : "#13ff13";
        if (p.is_crack) {
          el.style.borderColor = "#991b1b";
          el.style.color = "#fff";
          el.style.fontWeight = "700";
          el.textContent = "C" + p.crack_no;
        }
      }
      rowEl.appendChild(el);
    }
    container.appendChild(rowEl);
  }
}

function renderCrackTable(rows) {
  const wrap = document.getElementById("ck-table-wrap");
  wrap.innerHTML = "";
  if (!rows.length) {
    const p = document.createElement("p");
    p.className = "small";
    p.textContent = "尚未標記Crack。請在上方STRATE圖點選實物Crack格子。";
    wrap.appendChild(p);
    return;
  }
  const table = document.createElement("table");
  table.className = "tbl";
  table.innerHTML =
    "<thead><tr><th>Crack</th><th>Substrate ID</th><th>Block</th><th>座標</th><th>TX:TY</th><th>完整Wafer ID</th><th>FX:FY</th><th>NOTCH</th><th></th></tr></thead>";
  const tbody = document.createElement("tbody");
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td><b style="color:#c2410c">C${r.crack_no}</b></td><td>${r.substrate_id}</td><td>${r.output_block ?? ""}</td>` +
      `<td>${r.output_coord}</td><td>${r.tx}:${r.ty}</td><td>${r.wafer_id}</td><td>${r.fx}:${r.fy}</td><td>${r.notch}</td>` +
      `<td><button type="button" class="secondary ck-remove" data-key="${r.key}">刪除</button></td>`;
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  wrap.querySelectorAll(".ck-remove").forEach((btn) => {
    btn.addEventListener("click", () => {
      markedKeys = markedKeys.filter((k) => k !== btn.dataset.key);
      analyze();
    });
  });
}

function downloadCsv() {
  if (!lastCsv) return;
  const blob = new Blob([lastCsv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "Crack位置回推.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

document.getElementById("ck-btn-load").addEventListener("click", loadFiles);
document.getElementById("ck-btn-reset").addEventListener("click", () => {
  strateFiles = [];
  markedKeys = [];
  focusWaferId = null;
  currentDocIndex = 0;
  lastData = null;
  lastCsv = null;
  document.getElementById("ck_strate_files").value = "";
  document.getElementById("ck-status").textContent = "";
  document.getElementById("ck_doc_select").innerHTML = "";
  document.getElementById("ck_wafer_select").innerHTML = "";
  document.getElementById("ck-strip-grid").innerHTML = "";
  document.getElementById("ck-wafer-grid").innerHTML = "";
  document.getElementById("ck-wafer-info").textContent = "";
  document.getElementById("ck-table-wrap").innerHTML = "";
  document.getElementById("ck-btn-download-csv").style.display = "none";
  clearState();
});
document.getElementById("ck_doc_select").addEventListener("change", (e) => {
  currentDocIndex = Number(e.target.value);
  if (lastData) renderStripGrid(lastData.docs[currentDocIndex]);
  saveState();
});
document.getElementById("ck_wafer_select").addEventListener("change", (e) => {
  focusWaferId = e.target.value;
  analyze();
});
document.getElementById("ck-strip-grid").addEventListener("click", (e) => {
  const key = e.target.dataset.key;
  if (!key) return;
  const idx = markedKeys.indexOf(key);
  if (idx >= 0) markedKeys.splice(idx, 1);
  else markedKeys.push(key);
  analyze();
});
document.getElementById("ck-btn-download-csv").addEventListener("click", downloadCsv);

// ---- Persistence (2026/08/19 ask: "每個分頁在切換的時候資料不要不見" —
// only STRATE補檔/SECS格式化參數頁 had this so far; extending the same
// localStorage convention here). .strate files are plain text (unlike the
// STRATE補檔頁's UTF-16LE SECS log), so the raw file content itself is
// stored directly, no base64/re-parse-on-server round trip needed —
// analyze() already re-derives everything else from strateFiles+
// markedKeys+focusWaferId+currentDocIndex. ----
const CK_STORAGE_KEY = "bingomap_crack_state";

function saveState() {
  try {
    localStorage.setItem(
      CK_STORAGE_KEY,
      JSON.stringify({
        strateFiles,
        markedKeys,
        focusWaferId,
        currentDocIndex,
      })
    );
  } catch (err) {
    // localStorage unavailable or quota exceeded — just don't persist
  }
}

function clearState() {
  try {
    localStorage.removeItem(CK_STORAGE_KEY);
  } catch (err) {
    // ignore
  }
}

function restoreState() {
  const raw = localStorage.getItem(CK_STORAGE_KEY);
  if (!raw) return;
  let saved;
  try {
    saved = JSON.parse(raw);
  } catch (err) {
    return;
  }

  if (!saved.strateFiles || !saved.strateFiles.length) return;
  strateFiles = saved.strateFiles;
  markedKeys = saved.markedKeys || [];
  focusWaferId = saved.focusWaferId || null;
  currentDocIndex = saved.currentDocIndex || 0;
  analyze();
}

restoreState();
