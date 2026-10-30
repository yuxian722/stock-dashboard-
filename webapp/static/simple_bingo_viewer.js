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

// 2026/10/29新增：「選擇整個資料夾」——使用者反映分別好幾天的基板，各自
// 來源wafer的WaferStart事件常常落在不同天的log檔案裡，一個個Ctrl/Shift
// 手動多選很容易漏掉；改用`webkitdirectory`讓瀏覽器把整個資料夾(含子
// 資料夾)的檔案一次丟進來，前端自己過濾只留看得懂的副檔名(資料夾裡
// 常常還混著跟log無關的檔案，例如ini/縮圖快取，不能整批硬塞給後端)。
// `pendingFiles`是「選一般多個檔案」跟「選整個資料夾」共用的那份清單——
// 兩種選法互斥，後選的那次會蓋掉前一次的結果，不會疊加混在一起。
// 2026/10/30新增`.strate`：使用者手上有時候已經是現成的.strate檔案
// (不是SECS log)，後端`_is_strate_text()`看內容自動分辨要用哪種方式
// 解析，前端這裡只負責「別把看起來無關的檔案也送進去」這一層過濾。
const LOG_FILE_EXTENSIONS = [".log", ".txt", ".zip", ".strate"];
function isLogLikeFile(file) {
  const name = file.name.toLowerCase();
  return LOG_FILE_EXTENSIONS.some((ext) => name.endsWith(ext));
}

let pendingFiles = [];

document.getElementById("log-file").addEventListener("change", (e) => {
  pendingFiles = [...e.target.files];
  document.getElementById("folder-picked-label").textContent = "";
});

document.getElementById("btn-pick-folder").addEventListener("click", () => {
  document.getElementById("log-folder").click();
});

document.getElementById("log-folder").addEventListener("change", (e) => {
  const all = [...e.target.files];
  pendingFiles = all.filter(isLogLikeFile);
  document.getElementById("log-file").value = "";
  const label = document.getElementById("folder-picked-label");
  const skipped = all.length - pendingFiles.length;
  label.textContent = `已選資料夾，找到 ${pendingFiles.length} 個log檔案` +
    (skipped ? `（略過 ${skipped} 個非log檔案）` : "");
});

async function extractLog() {
  const status = document.getElementById("status");
  const loading = document.getElementById("loading-indicator");
  const loadingText = document.getElementById("loading-text");
  const btn = document.getElementById("btn-extract");
  const files = pendingFiles;
  if (!files.length) {
    status.className = "error";
    status.textContent = "請先選擇log檔案（可以是.zip，也可以一次選多個，或選整個資料夾）";
    return;
  }
  status.className = "";
  status.textContent = "";
  // 2026/10/29新增：解析中讓🐸一直跳，確認畫面是活的（不是按了沒反應），
  // 同時鎖住按鈕，避免使用者以為沒反應又多按一次造成同一批檔案重複解析。
  loading.classList.add("active");
  btn.disabled = true;

  // 2026/10/29修正重大bug：「選整個資料夾」上傳499個檔案時，一碰到第一個
  // 沒有StrateMap資料的檔案（資料夾裡混著跟STRATE無關的log，例如
  // Trace*.log，後端對這種檔案一律回400）整批就直接中斷、前面已經解析
  // 成功的檔案全部被丟掉，使用者完全看不到任何結果。改成逐一個別try/catch
  // ——單一檔案失敗只記錄下來，不中斷其他檔案的解析；全部跑完之後，只要
  // 有任何一個檔案成功就顯示結果，並且把「略過幾個檔案」的統計一起列出來，
  // 不是靜默吞掉也不是整批報廢。
  const results = [];
  const failures = [];
  try {
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      loadingText.textContent = `解析中，請稍候...（第 ${i + 1}/${files.length} 個檔案：${file.name}）`;
      try {
        results.push(await extractOneFile(file));
      } catch (err) {
        failures.push({ name: file.name, message: err.message });
      }
    }
  } finally {
    loading.classList.remove("active");
    btn.disabled = false;
  }

  if (!results.length) {
    status.className = "error";
    status.textContent = `選的 ${files.length} 個檔案都沒有解析出基板資料` +
      (failures.length ? `（例如「${failures[0].name}」：${failures[0].message}）` : "");
    document.getElementById("result-area").style.display = "none";
    return;
  }

  lastSubstrates = results.flatMap((r) => r.substrates);
  lastWaferMaps = results.flatMap((r) => r.wafer_maps || []);
  status.className = failures.length ? "" : "ok";
  status.textContent = `解析完成，找到 ${lastSubstrates.length} 枚基板（共 ${files.length} 個檔案，成功 ${results.length} 個` +
    (failures.length ? `，略過 ${failures.length} 個沒有基板資料的檔案）` : `）`);
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
  // 2026/10/30新增：使用者反映「下載檔案要多一項全部下載」——清單一次
  // 可能有20幾枚基板，一枚一枚點下載太累。按鈕文字跟著目前這批的枚數走，
  // 清單是空的就整個隱藏(沒有可以下載的東西)。
  const allBtn = document.getElementById("btn-download-all");
  allBtn.style.display = lastSubstrates.length ? "" : "none";
  allBtn.textContent = `全部下載（共 ${lastSubstrates.length} 枚，.zip）`;
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
      (substrate.wafer_ring || "無Wafer Ring") +
      '）的WaferStart資料——通常是因為這片來源wafer是在<b>別份log</b>（不同時段/天）被掃描記錄的，' +
      '不在目前這批上傳範圍裡。右邊這枚本身的BINGO MAP資料不受影響，仍然完整；' +
      '如果想看這片wafer的圖，把相關那幾天的log一起多選上傳即可（不影響已經解析出來的其他基板）。</p>';
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
      // 2026/10/29新增：只有「良品(bin=1)、還沒被這枚基板自己用掉」的
      // 格子才能點選/框選，跟app.js的toggleStagePick()同一條規則(不能
      // 手動塞一顆壞die進良品位置)。dataset存真正的col/row(不受正向/反向
      // 顯示排序影響，跟.focus判斷用同一份座標)，drag-select事件處理器
      // 直接讀這個，不用另外反推畫面排序。即使不能選也存col/row/bin——
      // 點到不能選的格子時，click handler要能根據這些資料給出「為什麼
      // 不能選」的具體提示，不能像一開始那樣完全沒反應(使用者誤以為是
      // 功能壞掉)。
      cell.dataset.col = col;
      cell.dataset.row = row;
      if (bin !== undefined) cell.dataset.bin = bin;
      if (bin === "1" && !highlight.has(key)) {
        cell.classList.add("pickable");
        if (stagedPicks.some((p) => p.x === col && p.y === row)) {
          cell.classList.add("staged");
        }
      }
      cell.title = bin !== undefined ? `${col}:${row} — bin=${bin}` : `${col}:${row} — 無資料`;
      rowEl.appendChild(cell);
    }
    container.appendChild(rowEl);
  }
}

// ---- 2026/10/29新增、同日改版：手動建立全新基板 ------------------------
// 第一版做成「補進目前選到的這枚基板自己的空白位置、合併回同一份檔案」，
// 使用者看了畫面後回報「你是不是誤會我的意思」——要的是完全獨立、不綁定
// 清單裡任何一枚基板的全新基板：自己輸入SUBSTRATE_ID，從wafer圖挑die
// 填進一張完全空白的BINGO MAP，下載一份獨立全新的.strate檔案，不跟任何
// 既有資料合併(用AskUserQuestion當面確認過這個方向)。
//
// stagedPicks在這一版裡本身就是「這枚全新基板的全部內容」，不是「暫存、
// 等套用」——框選的當下直接即時重畫空白BINGO MAP預覽(newSubstrateTargets()
// 純粹是座標排序的小函式，不是.strate格式序列化，複製一份在前端做預覽
// 風險很低；真正送出下載時，後端還是會用StrateFile.parse()/to_text()
// 重新產生一次正式格式，前端這份只是「看起來對不對」的即時預覽，不是
// 最終依據)。
let stagedPicks = []; // {x, y, bin}[]
let waferDragStart = null;
let pickStatusResetTimer = null;

function togglePick(col, row, bin) {
  const idx = stagedPicks.findIndex((p) => p.x === col && p.y === row);
  if (idx >= 0) {
    stagedPicks.splice(idx, 1);
    return;
  }
  stagedPicks.push({ x: col, y: row, bin });
}

function stagePickIfNew(col, row, bin) {
  if (stagedPicks.some((p) => p.x === col && p.y === row)) return;
  stagedPicks.push({ x: col, y: row, bin });
}

function scanPickRectangle(start, end) {
  const colLo = Math.min(start.col, end.col), colHi = Math.max(start.col, end.col);
  const rowLo = Math.min(start.row, end.row), rowHi = Math.max(start.row, end.row);
  document.querySelectorAll("#wafer-grid .wafer-cell.pickable").forEach((cell) => {
    const col = Number(cell.dataset.col), row = Number(cell.dataset.row);
    if (col >= colLo && col <= colHi && row >= rowLo && row <= rowHi) {
      stagePickIfNew(col, row, cell.dataset.bin);
    }
  });
}

function updatePickControls() {
  const status = document.getElementById("pick-status");
  const downloadBtn = document.getElementById("btn-download-new");
  const idInput = document.getElementById("new-substrate-id");
  status.textContent = `已選 ${stagedPicks.length} 顆`;
  downloadBtn.disabled = stagedPicks.length === 0 || !idInput.value.trim();
}

function refreshPickUI() {
  updatePickControls();
  if (selectedIndex >= 0) {
    renderWaferPane(lastSubstrates[selectedIndex]);
    renderNewSubstratePreview(lastSubstrates[selectedIndex]);
  }
}

const waferGridEl = document.getElementById("wafer-grid");
waferGridEl.addEventListener("mousedown", (e) => {
  const cell = e.target.closest(".wafer-cell.pickable");
  if (!cell) return;
  waferDragStart = { col: Number(cell.dataset.col), row: Number(cell.dataset.row) };
});
waferGridEl.addEventListener("mouseup", (e) => {
  const cell = e.target.closest(".wafer-cell.pickable");
  if (!cell || !waferDragStart) {
    waferDragStart = null;
    return;
  }
  const end = { col: Number(cell.dataset.col), row: Number(cell.dataset.row) };
  if (end.col === waferDragStart.col && end.row === waferDragStart.row) {
    togglePick(end.col, end.row, cell.dataset.bin);
  } else {
    scanPickRectangle(waferDragStart, end);
  }
  waferDragStart = null;
  refreshPickUI();
});

// 2026/10/29新增：點到不能選的格子(非良品、或已經被這枚基板自己用掉)
// 原本完全沒有任何反應——使用者誤以為是「功能壞掉」，實際上是點錯格子。
// 這裡用plain click(不是drag的mousedown/mouseup，避免跟上面那組重複
// 觸發)補一句具體原因，短暫顯示在pick-status位置、1.8秒後自動還原成
// 正常的「已選N顆」。
waferGridEl.addEventListener("click", (e) => {
  const cell = e.target.closest(".wafer-cell");
  if (!cell || cell.classList.contains("pickable")) return;
  const bin = cell.dataset.bin;
  let reason;
  if (bin === undefined) {
    reason = "這個位置在wafer圖上沒有die資料，不能選。";
  } else if (bin !== "1") {
    reason = `這格是bin=${bin}(非良品)，不能選——只能選良品(bin=1)。`;
  } else {
    reason = "這格已經被目前這枚基板自己用掉了，不能重複選。";
  }
  const status = document.getElementById("pick-status");
  status.textContent = reason;
  clearTimeout(pickStatusResetTimer);
  pickStatusResetTimer = setTimeout(updatePickControls, 1800);
});

document.getElementById("btn-clear-picks").addEventListener("click", () => {
  stagedPicks = [];
  refreshPickUI();
});

document.getElementById("new-substrate-id").addEventListener("input", updatePickControls);

async function downloadNewSubstrate() {
  const idInput = document.getElementById("new-substrate-id");
  const substrateId = idInput.value.trim();
  if (!stagedPicks.length || !substrateId || selectedIndex < 0) return;
  const template = lastSubstrates[selectedIndex];
  const status = document.getElementById("status");
  const downloadBtn = document.getElementById("btn-download-new");
  downloadBtn.disabled = true;
  try {
    const res = await fetch("/api/simple_bingo/build_new_substrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        template_text: template.text,
        substrate_id: substrateId,
        wafer_ring: template.wafer_ring,
        picks: stagedPicks,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "建立失敗");
    status.className = "ok";
    status.textContent = `已建立新基板「${data.substrate.substrate_id}」，開始下載。`;
    downloadSubstrate(data.substrate);
  } catch (err) {
    status.className = "error";
    status.textContent = err.message;
  } finally {
    updatePickControls();
  }
}

document.getElementById("btn-download-new").addEventListener("click", downloadNewSubstrate);

// 全新基板的形狀借用「目前選到的這一枚」當樣板(同一片wafer上的基板通常
// 同形狀)，用它的bounding box(min/max col/row)當範圍、column-major排序
// (欄由小到大、每欄內列由小到大)——跟後端build_new_substrate()用同一種
// 排序邏輯，保證前端這份即時預覽跟下載後的正式檔案排列順序一致。
function newSubstrateTargets(substrate) {
  const targets = [];
  for (let col = substrate.min_col; col <= substrate.max_col; col++) {
    for (let row = substrate.min_row; row <= substrate.max_row; row++) {
      targets.push({ col, row });
    }
  }
  return targets;
}

function renderNewSubstratePreview(substrate) {
  const targets = newSubstrateTargets(substrate);
  const positions = stagedPicks
    .map((pick, i) => (targets[i] ? { col: targets[i].col, row: targets[i].row, bin: pick.bin } : null))
    .filter(Boolean);
  renderSubstrateGrid("substrate-grid-new", substrate, positions, "還沒選");
}

function renderSubstrateGrid(containerId, substrate, positions, emptyLabel) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  const { min_col, max_col, min_row, max_row } = substrate;
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
        cell.title = `${col}:${row} — ${emptyLabel}`;
      }
      rowEl.appendChild(cell);
    }
    container.appendChild(rowEl);
  }
}

function renderBingoMapPane(substrate) {
  renderSubstrateGrid("substrate-grid", substrate, substrate.positions, "無die");
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

// ---- 2026/10/30新增：「全部下載」打包成一個.zip -------------------------
// 這支工具一貫「不依賴外部CDN/函式庫」(見module docstring)，打包zip也
// 不例外——自己寫一個只支援STORED(不壓縮)項目的最小ZIP產生器，不是真的
// 要省壓縮率(.strate檔案都很小，壓不壓差異不大)，是換掉「額外帶一份
// DEFLATE壓縮實作」的複雜度，STORED只需要CRC-32+照ZIP規格排版二進位
// 欄位，不需要真的壓縮演算法。
function crc32(bytes) {
  let crc = ~0;
  for (let i = 0; i < bytes.length; i++) {
    crc ^= bytes[i];
    for (let bit = 0; bit < 8; bit++) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return ~crc >>> 0;
}

function buildZip(entries) {
  // entries: [{name, data: Uint8Array}] — STORED-only zip per PKZIP APPNOTE
  // §4.3: local file header(30B固定) + 檔名 + 資料，逐一項目重複；接著
  // 一份central directory(每項46B固定+檔名)；最後end of central directory
  // (22B固定)收尾。compressed size跟uncompressed size寫一樣的值(因為沒有
  // 壓縮)，method固定填0(= stored)。
  const encoder = new TextEncoder();
  const localChunks = [];
  const centralChunks = [];
  let offset = 0;

  for (const entry of entries) {
    const nameBytes = encoder.encode(entry.name);
    const data = entry.data;
    const crc = crc32(data);

    // 2026/10/30：第一版這裡的欄位位移抄錯了——照搬了central directory的
    // 排版(sig/version made by/version needed/...)，但local file header
    // 沒有「version made by」這個欄位，少了2 bytes，後面全部欄位(crc起)
    // 都因此多偏移了2 bytes，寫出來的zip乍看能建出來、Playwright下載也
    // 正常觸發，但Python的zipfile.testzip()一讀就報「File name in
    // directory and header differ」——這種格式類bug光靠「看起來有跑」
    // 完全抓不到，靠真正拿標準工具(Python zipfile)讀回來交叉驗證才抓到，
    // 跟這個專案一貫「不能只看起來對」的原則一致。正確的local file
    // header欄位位移：sig(0,4B) version(4,2B) flags(6,2B) method(8,2B)
    // modtime(10,2B) moddate(12,2B) crc(14,4B) compsize(18,4B)
    // uncompsize(22,4B) namelen(26,2B) extralen(28,2B)，總共30 bytes。
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true); // version needed to extract
    local.setUint16(6, 0, true); // general purpose flag
    local.setUint16(8, 0, true); // method = stored
    local.setUint16(10, 0, true); // mod time
    local.setUint16(12, 0x21, true); // mod date(任意合法值，這些.strate檔名裡本來就有時間戳記)
    local.setUint32(14, crc, true);
    local.setUint32(18, data.length, true); // compressed size
    local.setUint32(22, data.length, true); // uncompressed size
    local.setUint16(26, nameBytes.length, true);
    // extra field length(位移30)留0，不用再寫

    localChunks.push(new Uint8Array(local.buffer), nameBytes, data);

    const central = new DataView(new ArrayBuffer(46));
    central.setUint32(0, 0x02014b50, true);
    central.setUint16(4, 20, true); // version made by
    central.setUint16(6, 20, true); // version needed
    central.setUint16(8, 0, true);
    central.setUint16(10, 0, true);
    central.setUint16(12, 0, true);
    central.setUint16(14, 0x21, true);
    central.setUint32(16, crc, true);
    central.setUint32(20, data.length, true);
    central.setUint32(24, data.length, true);
    central.setUint16(28, nameBytes.length, true);
    central.setUint16(30, 0, true); // extra length
    central.setUint16(32, 0, true); // comment length
    central.setUint16(34, 0, true); // disk number start
    central.setUint16(36, 0, true); // internal attrs
    central.setUint32(38, 0, true); // external attrs
    central.setUint32(42, offset, true); // local header offset

    centralChunks.push(new Uint8Array(central.buffer), nameBytes);

    offset += local.byteLength + nameBytes.length + data.length;
  }

  const centralStart = offset;
  const centralSize = centralChunks.reduce((sum, c) => sum + c.length, 0);

  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(4, 0, true);
  end.setUint16(6, 0, true);
  end.setUint16(8, entries.length, true); // entries on this disk
  end.setUint16(10, entries.length, true); // entries total
  end.setUint32(12, centralSize, true);
  end.setUint32(16, centralStart, true);
  end.setUint16(20, 0, true); // comment length

  const allChunks = [...localChunks, ...centralChunks, new Uint8Array(end.buffer)];
  const total = allChunks.reduce((sum, c) => sum + c.length, 0);
  const out = new Uint8Array(total);
  let pos = 0;
  for (const chunk of allChunks) {
    out.set(chunk, pos);
    pos += chunk.length;
  }
  return out;
}

// 清單裡每一枚都各自記一筆下載紀錄(跟使用者一枚一枚點下載的稽核效果
// 一樣，只是這次是一次按鈕觸發N筆)，再把全部.strate內容打包成一個zip
// 觸發瀏覽器下載——正向/反向不影響內容(純顯示層轉換，見module docstring)，
// 直接用每枚substrate.text本來的內容，不用管目前畫面上切的是哪個方向。
function downloadAllSubstrates() {
  if (!lastSubstrates.length) return;
  const encoder = new TextEncoder();
  const usedNames = new Set();
  const entries = lastSubstrates.map((s) => {
    let name = s.filename || `${s.substrate_id || "substrate"}.strate`;
    while (usedNames.has(name)) name = `_${name}`; // 極少見的檔名撞名，前面加底線避免互相覆蓋
    usedNames.add(name);
    logDownload(s);
    return { name, data: encoder.encode(s.text) };
  });

  const zipBytes = buildZip(entries);
  const blob = new Blob([zipBytes], { type: "application/zip" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const ts = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  a.download = `BINGO_MAP_全部基板_${ts.getFullYear()}${pad(ts.getMonth() + 1)}${pad(ts.getDate())}${pad(ts.getHours())}${pad(ts.getMinutes())}.zip`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

document.getElementById("btn-download-all").addEventListener("click", downloadAllSubstrates);

// 2026/10/29新增：勾選後直接在畫面上看這一枚的.strate原始內容——跟
// downloadSubstrate()下載拿到的substrate.text是同一份資料，不用真的存
// 一次檔案才能核對裡面的欄位。checkbox狀態故意不隨切換基板重置(勾著就
// 一直顯示)，這樣逐枚核對時不用每切一枚就重勾一次。
function renderRawStrateBox(substrate) {
  const box = document.getElementById("raw-strate-box");
  const checked = document.getElementById("chk-raw-strate").checked;
  if (checked && substrate) {
    box.textContent = substrate.text;
    box.style.display = "";
  } else {
    box.style.display = "none";
  }
}

function selectSubstrate(i) {
  if (!lastSubstrates.length) return;
  // 切換基板時清掉「手動建立全新基板」的選取——wafer座標、樣板欄位都是
  // 跟著「目前選到的這一枚」走的，換一枚之後舊的選取已經不適用，留著
  // 只會讓人誤以為還能套用到新樣板上。流水號輸入框也一併清空，避免
  // 不小心沿用上一枚的輸入值下載出錯誤的檔案。
  stagedPicks = [];
  document.getElementById("new-substrate-id").value = "";
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
  renderNewSubstratePreview(substrate);
  renderRawStrateBox(substrate);
  updatePickControls();
}

document.getElementById("chk-raw-strate").addEventListener("change", () => {
  renderRawStrateBox(selectedIndex >= 0 ? lastSubstrates[selectedIndex] : null);
});

document.getElementById("btn-extract").addEventListener("click", extractLog);
for (const el of document.querySelectorAll('input[name="orientation"]')) {
  el.addEventListener("change", (e) => {
    orientation = e.target.value;
    if (selectedIndex >= 0) selectSubstrate(selectedIndex);
  });
}
