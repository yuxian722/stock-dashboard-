// SECS LOG BINGO MAP 檢視器 — 簡化版獨立小工具的前端。
// 2026/10/29改版：原本是「每枚基板各自一張卡片，上下排列」，現在改成
// 「左邊一欄列出所有基板、點一枚，右邊固定分成wafer圖(左)/BINGO MAP(右)
// 兩半」——選取狀態跟著目前選到的basename走，不用每次都重新整理整頁。
//
// 正向/反向：純粹是畫面排列(列的順序倒過來，欄不動——跟bingomap/CLAUDE.md
// 記錄過的真實案例「Bingo Map Query報表自己的顯示轉換」同一種變換)，
// 兩張圖(wafer圖、BINGO MAP圖)都套用同一個orientation狀態，這樣切換時
// 兩張圖的「上下方向」會維持一致，不會變成各轉各的看不出對應關係。

let lastSubstrates = [];
let lastWaferMaps = [];
let selectedIndex = -1;
let orientation = "forward"; // "forward" | "reverse"
let currentEmployeeId = "";

// 2026/10/29新增：登入(工號)——不是帳密驗證，純粹是「每次使用都留下
// 工號可追溯」，所以每次開頁面都會跳登入畫面，但用localStorage記住上次
// 填過的工號當預設值(同一個人不用每次重打，真的換人用才要手動改)。
const EMPLOYEE_ID_STORAGE_KEY = "sbv_last_employee_id";

function showLoginOverlay() {
  document.getElementById("login-overlay").style.display = "flex";
  const input = document.getElementById("login-input");
  try {
    input.value = localStorage.getItem(EMPLOYEE_ID_STORAGE_KEY) || "";
  } catch (err) {
    // localStorage不可用(例如無痕視窗擋存取)——預設值留空，不影響登入本身
  }
  input.focus();
  input.select();
}

function doLogin() {
  const input = document.getElementById("login-input");
  const id = input.value.trim();
  const errorEl = document.getElementById("login-error");
  if (!id) {
    errorEl.textContent = "請輸入工號";
    return;
  }
  currentEmployeeId = id;
  try {
    localStorage.setItem(EMPLOYEE_ID_STORAGE_KEY, id);
  } catch (err) {
    // 存不進去就算了，不影響這次使用，只是下次預設值不會自動帶出來
  }
  errorEl.textContent = "";
  document.getElementById("current-employee-id").textContent = id;
  document.getElementById("login-overlay").style.display = "none";
}

document.getElementById("btn-login").addEventListener("click", doLogin);
document.getElementById("login-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doLogin();
});
document.getElementById("btn-switch-user").addEventListener("click", showLoginOverlay);
showLoginOverlay();

// Bin color palette — same convention as app.js/strate_xml.js的BIN_COLORS
// (這個專案一貫的做法：每個檔案各自維護一份，不是共用模組)，色碼來自
// 反編譯WaferCoordinate.exe的clsWaferMap.cs的DrawBinRect()，不是自己配的。
const BIN_COLORS = {
  "1": "#13ff13", "2": "#0000cd", "3": "#ff8c00", "4": "#c60060",
  "5": "#40e0d0", "6": "#838383", "7": "#ff59ff", "8": "#11ffff",
  "9": "#848400",
};
const BIN_COLOR_FALLBACK = "#e0ffff";

function binColor(bin) {
  return BIN_COLORS[bin] !== undefined ? BIN_COLORS[bin] : BIN_COLOR_FALLBACK;
}

function renderBinLegend(containerId, bins) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const sorted = [...bins].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  el.innerHTML = sorted.map((b) => `<span><i style="background:${binColor(b)}"></i>Bin ${b}</span>`).join("");
}

function arrayBufferToBase64(buf) {
  let binary = "";
  const bytes = new Uint8Array(buf);
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

// 2026/10/29新增：一次可以選多個檔案(ctrl/shift多選)，每個檔案各自丟給
// 後端解析(後端自己也會解壓縮.zip、甚至zip裡包zip)，結果合併成同一批——
// 對應使用者實際的工作方式：log資料夾裡放的是一天一個的.log.zip，想看
// 好幾天的話用這個，不用自己先手動合併檔案。
async function extractOneFile(file) {
  const buf = await file.arrayBuffer();
  const log_base64 = arrayBufferToBase64(buf);
  const res = await fetch("/api/simple_bingo/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ log_base64 }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(`${file.name}：${data.error || "解析失敗"}`);
  return data;
}

async function extractLog() {
  const fileInput = document.getElementById("log-file");
  const status = document.getElementById("status");
  const loading = document.getElementById("loading-indicator");
  const btn = document.getElementById("btn-extract");
  const files = [...fileInput.files];
  if (!files.length) {
    status.className = "error";
    status.textContent = "請先選擇log檔案（可以是.zip，也可以一次選多個）";
    return;
  }
  status.className = "";
  status.textContent = "";
  // 2026/10/29新增：解析中讓🐸一直跳，確認畫面是活的（不是按了沒反應），
  // 同時鎖住按鈕，避免使用者以為沒反應又多按一次造成同一批檔案重複解析。
  loading.classList.add("active");
  btn.disabled = true;

  let data;
  try {
    const results = [];
    for (const file of files) results.push(await extractOneFile(file));
    data = {
      substrates: results.flatMap((r) => r.substrates),
      wafer_maps: results.flatMap((r) => r.wafer_maps || []),
    };
  } catch (err) {
    status.className = "error";
    status.textContent = err.message;
    document.getElementById("result-area").style.display = "none";
    return;
  } finally {
    loading.classList.remove("active");
    btn.disabled = false;
  }

  lastSubstrates = data.substrates;
  lastWaferMaps = data.wafer_maps || [];
  status.className = "ok";
  status.textContent = `解析完成，找到 ${lastSubstrates.length} 枚基板。`;
  document.getElementById("result-area").style.display = "";
  renderList();
  selectSubstrate(0);
}

function renderList() {
  const list = document.getElementById("substrate-list");
  list.innerHTML = "";
  lastSubstrates.forEach((s, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sbv-list-item" + (i === selectedIndex ? " active" : "");
    btn.innerHTML = `<b>${s.substrate_id || "(無編號)"}</b><span>DIE ${s.num_dies} 顆</span>`;
    btn.addEventListener("click", () => selectSubstrate(i));
    list.appendChild(btn);
  });
}

function findWaferMapFor(substrate) {
  return lastWaferMaps.find((wm) => wm.frame_id === substrate.wafer_ring) || null;
}

function displayRow(row, minRow, maxRow) {
  return orientation === "reverse" ? maxRow - (row - minRow) : row;
}

function renderWaferPane(substrate) {
  const container = document.getElementById("wafer-grid");
  container.innerHTML = "";
  const wm = findWaferMapFor(substrate);
  if (!wm || !wm.cells.length) {
    container.innerHTML = '<p class="sbv-empty">這份log裡沒有找到這枚基板來源wafer（' +
      (substrate.wafer_ring || "無Wafer Ring") + '）的WaferStart資料。</p>';
    document.getElementById("wafer-bin-legend").innerHTML = "";
    return;
  }

  const cellMap = new Map(wm.cells.map((c) => [`${c.col},${c.row}`, c.bin]));
  renderBinLegend("wafer-bin-legend", new Set(wm.cells.map((c) => c.bin)));
  const highlight = new Set(substrate.wafer_positions.map((p) => `${p.col},${p.row}`));

  const minCol = Math.min(...wm.cells.map((c) => c.col));
  const maxCol = Math.max(...wm.cells.map((c) => c.col));
  const minRow = Math.min(...wm.cells.map((c) => c.row));
  const maxRow = Math.max(...wm.cells.map((c) => c.row));

  const rows = [];
  for (let row = minRow; row <= maxRow; row++) rows.push(row);
  rows.sort((a, b) => displayRow(a, minRow, maxRow) - displayRow(b, minRow, maxRow));

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

  for (const row of rows) {
    const rowEl = document.createElement("div");
    rowEl.className = "wafer-row";
    const rowLabel = document.createElement("div");
    rowLabel.className = "grid-axis-cell";
    rowLabel.textContent = row;
    rowEl.appendChild(rowLabel);
    for (let col = maxCol; col >= minCol; col--) {
      const cell = document.createElement("div");
      cell.className = "wafer-cell";
      const bin = cellMap.get(`${col},${row}`);
      if (bin !== undefined) {
        cell.classList.add("bin-cell");
        cell.style.setProperty("--bin-color", binColor(bin));
      }
      const key = `${col},${row}`;
      if (highlight.has(key)) {
        // .focus只加外框、不蓋掉底色(.referenced會用純色蓋掉格子)——這裡
        // 要同時看到「這格本來是什麼bin」跟「這格屬不屬於目前選到的
        // 基板」，兩個資訊都要留著，不能只顯示其中一個。
        cell.classList.add("focus");
      }
      cell.title = bin !== undefined ? `${col}:${row} — bin=${bin}` : `${col}:${row} — 無資料`;
      rowEl.appendChild(cell);
    }
    container.appendChild(rowEl);
  }
}

function renderBingoMapPane(substrate) {
  const container = document.getElementById("substrate-grid");
  container.innerHTML = "";
  const { min_col, max_col, min_row, max_row, positions } = substrate;
  const posByRowCol = new Map();
  for (const p of positions) posByRowCol.set(`${p.col},${p.row}`, p);

  const rows = [];
  for (let row = min_row; row <= max_row; row++) rows.push(row);
  rows.sort((a, b) => displayRow(a, min_row, max_row) - displayRow(b, min_row, max_row));

  const headerRow = document.createElement("div");
  headerRow.className = "wafer-row";
  const corner = document.createElement("div");
  corner.className = "grid-axis-cell substrate-axis-corner";
  headerRow.appendChild(corner);
  for (let col = min_col; col <= max_col; col++) {
    const label = document.createElement("div");
    label.className = "grid-axis-cell substrate-axis-cell";
    label.textContent = col;
    headerRow.appendChild(label);
  }
  container.appendChild(headerRow);

  for (const row of rows) {
    const rowEl = document.createElement("div");
    rowEl.className = "wafer-row";
    const rowLabel = document.createElement("div");
    rowLabel.className = "grid-axis-cell substrate-axis-cell";
    rowLabel.textContent = row;
    rowEl.appendChild(rowLabel);
    for (let col = min_col; col <= max_col; col++) {
      const cell = document.createElement("div");
      cell.className = "substrate-cell";
      const pos = posByRowCol.get(`${col},${row}`);
      if (pos) {
        cell.classList.add("filled");
        cell.title = `${col}:${row} — bin=${pos.bin}`;
      } else {
        cell.title = `${col}:${row} — 無die`;
      }
      rowEl.appendChild(cell);
    }
    container.appendChild(rowEl);
  }
}

// 2026/10/29新增：每次下載記一筆(工號/時間/流水號/方向)到後端的CSV——
// 這支工具唯一「真的對這份資料下決定」的動作就是下載，所以記錄點選在
// 這裡，不是每次切正向/反向或點清單都記(那只是在看)。故意不等這個
// fetch完成才觸發下載(await會讓使用者多等一次網路來回)，記錄失敗也
// 不應該讓人連檔案都拿不到，只在畫面上補一行警告。
async function logDownload(substrate) {
  try {
    const res = await fetch("/api/simple_bingo/log_download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        employee_id: currentEmployeeId,
        substrate_id: substrate.substrate_id,
        filename: substrate.filename,
        wafer_ring: substrate.wafer_ring,
        eqpid: substrate.eqpid,
        orientation,
      }),
    });
    if (!res.ok) throw new Error((await res.json()).error || "記錄失敗");
  } catch (err) {
    const status = document.getElementById("status");
    status.className = "error";
    status.textContent = `⚠ 下載紀錄沒有寫入成功（${err.message}），檔案本身已正常下載。`;
  }
}

function downloadSubstrate(substrate) {
  logDownload(substrate);
  const blob = new Blob([substrate.text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = substrate.filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function selectSubstrate(i) {
  if (!lastSubstrates.length) return;
  selectedIndex = i;
  const substrate = lastSubstrates[i];
  renderList();

  document.getElementById("detail-title").textContent = `流水號：${substrate.substrate_id || "(無編號)"}`;
  document.getElementById("detail-info").textContent =
    `Wafer Ring：${substrate.wafer_ring || "—"}　EQPID：${substrate.eqpid || "—"}　DIE數量：${substrate.num_dies}` +
    (substrate.num_other_layer_dies ? `（另有疊層${substrate.num_other_layer_dies}顆）` : "");

  const btn = document.getElementById("btn-download");
  btn.style.display = "";
  btn.textContent = `下載 ${substrate.filename}`;
  btn.onclick = () => downloadSubstrate(substrate);

  renderWaferPane(substrate);
  renderBingoMapPane(substrate);
}

document.getElementById("btn-extract").addEventListener("click", extractLog);
for (const el of document.querySelectorAll('input[name="orientation"]')) {
  el.addEventListener("change", (e) => {
    orientation = e.target.value;
    if (selectedIndex >= 0) selectSubstrate(selectedIndex);
  });
}
