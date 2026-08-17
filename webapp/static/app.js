// ---- State ----------------------------------------------------------------
// N-layer (一次上N顆) model: layer i is 0-indexed internally but always
// displayed as "第(i+1)層", and its f9 in the generated .strate is always
// str(i+1) — confirmed against a real 8-layer sample (see
// bingomap/tests/test_strate_eight_layer_real_sample.py): DIE_INFO always
// holds only the LAST layer (highest f9), everything else goes into one
// combined DIE_INFO_OTHER_LAYER section grouped by f9. Layer 0 always uses
// the original static DOM elements (ids with no suffix, or the
// "-primary"/no-suffix ones that predate this generalization); layers
// 1..N-1 are built dynamically with a "_L{i}" id suffix — see waferIds()/
// bingoIds() below. Changing multi_layer_enabled/num_layers/
// multi_wafer_enabled always fully resets picks and wafer data (see
// resetLayerState()) rather than trying to remap old per-layer state onto
// a new layer count — simpler and safer than guessing an intent-preserving
// remap for a rarely-changed, one-time-per-job setting.
let targetQty = null;
let multiLayerEnabled = false;
let numLayers = 2; // only meaningful when multiLayerEnabled
let multiWaferEnabled = false; // true = every layer has its own physical wafer
let picksByLayer = [[]]; // picksByLayer[i] = {x, y, bin}[]
let currentLayerIndex = 0; // which layer new picks on the SHARED wafer grid go to
let waferCellsByLayer = [new Map()]; // waferCellsByLayer[i]: "x,y" -> bin
let waferBoundsByLayer = [null];
let substratePositions = []; // ["col:row", ...] in blank_generator's own machine-type order — shared by every layer
let substrateBounds = null; // {minCol, maxCol, minRow, maxRow}
let focusedSubstratePosByLayer = [null]; // "col:row" clicked in that layer's BINGO MAP, for reverse lookup
let focusedWaferXYByLayer = [null]; // {x, y} that focused position maps to, if filled
let usingTemplate = false; // true once a template .strate has been loaded via loadTemplate()
let skippedPositions = new Set(); // "col:row" substrate positions marked "不上片" — excluded from the fill order
let skipModeEnabled = false; // true = clicking a substrate cell toggles skip instead of reverse-lookup

function effectiveNumLayers() {
  return multiLayerEnabled ? numLayers : 1;
}

// ---- Per-layer DOM id helpers ----------------------------------------------
function waferIds(i) {
  const s = i === 0 ? "" : `_L${i}`;
  return {
    panel: `wafer-panel${s}`,
    frmLotNo: `frm_lot_no${s}`,
    frmBarcodeId: `frm_barcode_id${s}`,
    frmPath: `frm_path${s}`,
    btnLoadFrm: `btn-load-frm${s}`,
    frmStatus: `frm-status${s}`,
    waferInput: `wafer-input${s}`,
    btnLoadWafer: `btn-load-wafer${s}`,
    hoverStatus: `wafer-hover-status${s}`,
    wrap: `wafer-wrap${s}`,
    grid: `wafer-grid${s}`,
    overlay: `wafer-overlay${s}`,
    tooltip: `wafer-tooltip${s}`,
  };
}

function bingoIds(i) {
  if (i === 0) {
    return {
      block: "bingo-map-block-primary",
      qty: "qty-status-primary",
      hoverStatus: "substrate-hover-status",
      wrap: "substrate-wrap",
      grid: "substrate-grid",
      tooltip: "substrate-tooltip",
      table: "pick-table",
    };
  }
  return {
    block: `bingo-map-block_L${i}`,
    qty: `qty-status_L${i}`,
    hoverStatus: `substrate-hover-status_L${i}`,
    wrap: `substrate-wrap_L${i}`,
    grid: `substrate-grid_L${i}`,
    tooltip: `substrate-tooltip_L${i}`,
    table: `pick-table_L${i}`,
  };
}

// ---- Dynamic HTML for layers 1..N-1 ---------------------------------------
function buildExtraWaferPanelHtml(i) {
  const ids = waferIds(i);
  return `
    <section class="panel" id="${ids.panel}" style="grid-column:1/-1">
      <h2><span class="step-badge">2</span>Wafer Bin 資料 — 第${i + 1}層（不同wafer）</h2>
      <div class="notice">第${i + 1}層使用自己的wafer，這裡獨立讀取/貼上第${i + 1}層自己的wafer bin資料。</div>
      <div class="grid2">
        <label>FRM Lot No <input id="${ids.frmLotNo}" value=""></label>
        <label>Barcode ID <input id="${ids.frmBarcodeId}" value=""></label>
      </div>
      <label style="margin-bottom:0.6rem">FRM根路徑 <input id="${ids.frmPath}" value="F:\\SMAP\\FRM\\"></label>
      <button id="${ids.btnLoadFrm}">自動讀取FRM檔案</button>
      <p id="${ids.frmStatus}" class="lyr-frm-status"></p>
      <div class="notice" style="margin-top:1rem">或手動貼上第${i + 1}層wafer bin資料（每行 <code>x,y,bin</code>）</div>
      <textarea id="${ids.waferInput}" rows="6" placeholder="23,195,1&#10;23,196,1&#10;23,197,7"></textarea>
      <button class="secondary" id="${ids.btnLoadWafer}">載入第${i + 1}層Wafer地圖(文字)</button>
      <div class="legend">
        <span><i style="background:#4fb84a"></i>Bin 1（可選）</span>
        <span><i style="background:#d867d8"></i>Bin 7（不可選）</span>
        <span><i style="background:#fff;border-color:#1a3fd6"></i>已點選（第${i + 1}層）</span>
      </div>
      <p id="${ids.hoverStatus}" class="grid-hover-status">滑鼠移到格子上會顯示座標</p>
      <div id="${ids.wrap}" class="lyr-wafer-wrap">
        <div id="${ids.grid}" class="lyr-wafer-grid"></div>
        <svg id="${ids.overlay}" class="lyr-wafer-overlay"></svg>
        <div class="grid-tooltip" id="${ids.tooltip}"></div>
      </div>
    </section>
  `;
}

function buildExtraBingoMapBlockHtml(i) {
  const ids = bingoIds(i);
  return `
    <div class="bingo-map-block" id="${ids.block}">
      <h3>第${i + 1}層 BINGO MAP</h3>
      <p id="${ids.qty}" class="badge"></p>
      <p id="${ids.hoverStatus}" class="grid-hover-status">滑鼠移到格子上會顯示座標</p>
      <div class="grid-wrap-inner" id="${ids.wrap}">
        <div id="${ids.grid}" class="lyr-substrate-grid"></div>
        <div class="grid-tooltip" id="${ids.tooltip}"></div>
      </div>
      <table id="${ids.table}" class="lyr-pick-table">
        <thead><tr><th>#</th><th>X</th><th>Y</th><th>Bin</th><th></th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  `;
}

// ---- UI rebuild on layer-config change --------------------------------
function resetLayerState() {
  const n = effectiveNumLayers();
  picksByLayer = Array.from({ length: n }, () => []);
  waferCellsByLayer = Array.from({ length: n }, () => new Map());
  waferBoundsByLayer = Array.from({ length: n }, () => null);
  focusedSubstratePosByLayer = Array.from({ length: n }, () => null);
  focusedWaferXYByLayer = Array.from({ length: n }, () => null);
  currentLayerIndex = 0;
  document.getElementById("lookup-status").textContent = "";
}

function rebuildLayerUi() {
  const n = effectiveNumLayers();

  // --- wafer panels (layer 0 is the static #wafer-panel; 1..n-1 dynamic) ---
  const extraWaferContainer = document.getElementById("wafer-panels-extra");
  extraWaferContainer.innerHTML = "";
  if (multiWaferEnabled && n > 1) {
    for (let i = 1; i < n; i++) {
      extraWaferContainer.insertAdjacentHTML("beforeend", buildExtraWaferPanelHtml(i));
      wireWaferPanelEvents(i);
    }
  }

  // --- layer-switch buttons (shared-wafer mode only) ---
  const switchContainer = document.getElementById("layer-switch");
  switchContainer.innerHTML = "";
  switchContainer.style.display = n > 1 && !multiWaferEnabled ? "" : "none";
  if (n > 1 && !multiWaferEnabled) {
    for (let i = 0; i < n; i++) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "secondary" + (i === currentLayerIndex ? " active-layer" : "");
      btn.textContent = `第${i + 1}層 (f9=${i + 1})`;
      btn.dataset.layerIndex = String(i);
      btn.addEventListener("click", () => setActiveLayer(i));
      switchContainer.appendChild(btn);
    }
  }

  // --- BINGO MAP blocks (layer 0 is the static block; 1..n-1 dynamic) ---
  const bingoWrap = document.getElementById("bingo-maps-wrap");
  bingoWrap.querySelectorAll(".bingo-map-block:not(#bingo-map-block-primary)").forEach((el) => el.remove());
  for (let i = 1; i < n; i++) {
    bingoWrap.insertAdjacentHTML("beforeend", buildExtraBingoMapBlockHtml(i));
    wireBingoBlockEvents(i);
  }

  document.getElementById("bingo-map-title-primary").textContent = n > 1 ? "第1層 BINGO MAP" : "BINGO MAP";
  document.getElementById("wafer-panel-title-suffix").textContent =
    n > 1 ? (multiWaferEnabled ? " — 第1層" : `（共${n}層共用同一片wafer，點選會加入下方選定的層）`) : "";
  document.getElementById("wafer-legend-picked").style.display = n > 1 ? "" : "none";
}

// ---- Header / blank / template -----------------------------------------
function setStepFlow(step, { done = [] } = {}) {
  for (let i = 1; i <= 4; i++) {
    const el = document.getElementById(`step-flow-${i}`);
    el.classList.toggle("active", i === step);
    el.classList.toggle("done", done.includes(i));
  }
}

function headerPayload() {
  return {
    assy_lot: document.getElementById("assy_lot").value,
    mapping_lot: document.getElementById("mapping_lot").value,
    eqpid: document.getElementById("eqpid").value,
    oper: document.getElementById("oper").value,
    substrate_id: document.getElementById("substrate_id").value,
    substrate_row: document.getElementById("substrate_row").value,
    substrate_column: document.getElementById("substrate_column").value,
    substrate_block: document.getElementById("substrate_block").value,
    notch: document.getElementById("notch").value,
    ref: document.getElementById("ref").value,
    convention: document.getElementById("convention").value,
    machine_type: document.getElementById("machine_type").value,
  };
}

async function loadBlank() {
  // Explicitly regenerating via convention/machine_type supersedes any
  // previously loaded template's position order — and any "不上片" marks,
  // since they're tied to the old position list which may no longer apply.
  usingTemplate = false;
  skippedPositions.clear();
  const res = await fetch("/api/blank", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(headerPayload()),
  });
  const data = await res.json();
  const status = document.getElementById("blank-status");
  if (!res.ok) {
    status.textContent = "錯誤：" + data.error;
    targetQty = null;
    substratePositions = [];
    substrateBounds = null;
  } else {
    targetQty = data.total_qty;
    substratePositions = data.positions;
    substrateBounds = computeSubstrateBounds(substratePositions);
    status.textContent = `空白骨架已產生，共 ${data.positions.length} 格，目標DIE數量 = ${targetQty}`;
    setStepFlow(2, { done: [1] });
  }
  renderAll();
}

async function loadTemplate(text) {
  const status = document.getElementById("template-status");
  status.className = "";
  status.textContent = "讀取中...";
  const res = await fetch("/api/parse_strate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  const data = await res.json();
  if (!res.ok) {
    status.className = "error";
    status.textContent = data.error;
    return;
  }

  document.getElementById("assy_lot").value = data.assy_lot;
  document.getElementById("mapping_lot").value = data.mapping_lot;
  document.getElementById("eqpid").value = data.eqpid;
  document.getElementById("oper").value = data.oper;
  document.getElementById("substrate_id").value = data.substrate_id;
  document.getElementById("substrate_row").value = data.substrate_row;
  document.getElementById("substrate_column").value = data.substrate_column;
  document.getElementById("substrate_block").value = data.substrate_block;
  document.getElementById("notch").value = data.notch;
  document.getElementById("ref").value = data.ref;
  document.getElementById("wafer_ring").value = data.wafer_ring;

  usingTemplate = true;
  skippedPositions.clear();
  targetQty = data.total_qty;
  substratePositions = data.positions;
  substrateBounds = computeSubstrateBounds(substratePositions);

  multiLayerEnabled = data.num_layers > 1;
  numLayers = Math.max(data.num_layers, 2);
  document.getElementById("multi_layer_enabled").checked = multiLayerEnabled;
  document.getElementById("num_layers").value = numLayers;
  document.getElementById("multi-layer-fields").style.display = multiLayerEnabled ? "" : "none";
  document.getElementById("multi-wafer-field").style.display = multiLayerEnabled ? "" : "none";
  multiWaferEnabled = false;
  document.getElementById("multi_wafer_enabled").checked = false;

  resetLayerState();
  picksByLayer = data.layer_picks.length ? data.layer_picks.map((picks) => picks.slice()) : [[]];
  rebuildLayerUi();
  renderAll();

  status.className = "ok";
  const layerNote = multiLayerEnabled ? `（共${data.num_layers}層）` : "";
  status.textContent =
    `已載入範本：共 ${data.total_qty} 個基板位置${layerNote}。` +
    `基板位置順序沿用範本原本的順序。可以直接調整基板流水號/時間後產生，或繼續編輯座標。`;
  document.getElementById("blank-status").textContent = "（目前使用範本的基板位置順序，不需要再按「產生空白骨架」——除非要改用DB/ESEC規則重新產生）";
  setStepFlow(4, { done: [1, 2, 3] });
}

function computeSubstrateBounds(positions) {
  if (!positions.length) return null;
  let minCol = Infinity, maxCol = -Infinity, minRow = Infinity, maxRow = -Infinity;
  for (const pos of positions) {
    const [col, row] = pos.split(":").map(Number);
    minCol = Math.min(minCol, col); maxCol = Math.max(maxCol, col);
    minRow = Math.min(minRow, row); maxRow = Math.max(maxRow, row);
  }
  return { minCol, maxCol, minRow, maxRow };
}

function fillablePositions() {
  // Positions marked "不上片" are excluded from the fill order entirely —
  // matches assign_dies()'s own "unfilled positions are simply absent"
  // rule (see bingomap/CLAUDE.md), just with a smaller starting list.
  return substratePositions.filter((pos) => !skippedPositions.has(pos));
}

// ---- BINGO MAP (substrate grid) rendering ---------------------------------
function renderSubstrateGridInto(containerId, layerPicks, focusedPos) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";
  if (!substrateBounds) return;
  // First N picks (in click/scan order) fill the first N *fillable*
  // positions of the blank skeleton's own order (skipping any marked
  // "不上片") — this mirrors exactly what assign_dies()/assign_layers()
  // does at generate time, so this preview is never out of sync with the
  // real output.
  const fillable = fillablePositions();
  const filled = new Set(fillable.slice(0, layerPicks.length));
  const nextPos = fillable[layerPicks.length];
  const { minCol, maxCol, minRow, maxRow } = substrateBounds;

  const headerRow = document.createElement("div");
  headerRow.className = "wafer-row";
  const corner = document.createElement("div");
  corner.className = "grid-axis-cell grid-axis-corner";
  headerRow.appendChild(corner);
  for (let col = minCol; col <= maxCol; col++) {
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
    for (let col = minCol; col <= maxCol; col++) {
      const pos = `${col}:${row}`;
      const cell = document.createElement("div");
      cell.className = "substrate-cell";
      if (skippedPositions.has(pos)) cell.classList.add("skipped");
      if (filled.has(pos)) cell.classList.add("filled");
      if (pos === nextPos) cell.classList.add("next");
      if (pos === focusedPos) cell.classList.add("focus");
      cell.dataset.pos = pos;
      cell.title = pos;
      rowEl.appendChild(cell);
    }
    container.appendChild(rowEl);
  }
}

function renderSubstrateGrid() {
  const n = effectiveNumLayers();
  for (let i = 0; i < n; i++) {
    const ids = bingoIds(i);
    renderSubstrateGridInto(ids.grid, picksByLayer[i], focusedSubstratePosByLayer[i]);
  }
}

function reverseLookupSubstratePos(pos, layerIndex) {
  const status = document.getElementById("lookup-status");
  const layerPicks = picksByLayer[layerIndex];
  const n = effectiveNumLayers();
  const layerLabel = n > 1 ? `第${layerIndex + 1}層：` : "";
  focusedSubstratePosByLayer[layerIndex] = pos;

  if (skippedPositions.has(pos)) {
    focusedWaferXYByLayer[layerIndex] = null;
    status.textContent = `${layerLabel}基板位置 ${pos} 已標記「不上片」，不會對應到任何wafer座標`;
    status.className = "notice";
    renderAll();
    return;
  }
  const index = fillablePositions().indexOf(pos);
  const isFilled = index >= 0 && index < layerPicks.length;
  const targetPanelIndex = multiWaferEnabled ? layerIndex : 0;
  const targetGridId = waferIds(targetPanelIndex).grid;
  if (isFilled) {
    const pick = layerPicks[index];
    focusedWaferXYByLayer[layerIndex] = { x: pick.x, y: pick.y };
    status.textContent = `${layerLabel}基板位置 ${pos} ↔ Wafer座標 ${pick.x}:${pick.y}（第 ${index + 1} 顆）`;
    status.className = "notice";
  } else {
    focusedWaferXYByLayer[layerIndex] = null;
    status.textContent = `${layerLabel}基板位置 ${pos} 尚未對應到任何wafer座標（還沒點選到這一格）`;
    status.className = "notice";
  }
  renderAll();
  const waferCellEl = document.querySelector(`#${targetGridId} .wafer-cell.focus`);
  if (waferCellEl) waferCellEl.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
}

// ---- Wafer bin data parsing -------------------------------------------
function parseWaferText(text) {
  const cells = new Map();
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const line of text.split("\n")) {
    const parts = line.trim().split(",");
    if (parts.length !== 3) continue;
    const [x, y, bin] = parts.map((p, i) => (i < 2 ? parseInt(p, 10) : p.trim()));
    if (Number.isNaN(x) || Number.isNaN(y)) continue;
    cells.set(`${x},${y}`, bin);
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  return { cells, bounds: cells.size ? { minX, maxX, minY, maxY } : null };
}

function waferCellsFromApiCells(apiCells) {
  const cells = new Map();
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const c of apiCells) {
    cells.set(`${c.x},${c.y}`, c.bin);
    minX = Math.min(minX, c.x); maxX = Math.max(maxX, c.x);
    minY = Math.min(minY, c.y); maxY = Math.max(maxY, c.y);
  }
  return { cells, bounds: cells.size ? { minX, maxX, minY, maxY } : null };
}

async function loadFrmIntoPanel(panelIndex) {
  const ids = waferIds(panelIndex);
  const status = document.getElementById(ids.frmStatus);
  status.className = "";
  status.textContent = "讀取中...";
  const payload = {
    lot_no: document.getElementById(ids.frmLotNo).value,
    barcode_id: document.getElementById(ids.frmBarcodeId).value,
    frm_path: document.getElementById(ids.frmPath).value,
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
  const { cells, bounds } = waferCellsFromApiCells(data.cells);
  waferCellsByLayer[panelIndex] = cells;
  waferBoundsByLayer[panelIndex] = bounds;
  status.className = "ok";
  status.textContent = `已載入 LotNo=${data.lot_no} WaferID=${data.wafer_id} Layout=${data.wafer_type}（${data.columns}x${data.rows}，共${data.cells.length}顆有資料）`;
  renderAll();
}

function cellClass(bin) {
  if (bin === "1") return "bin-1";
  if (bin === undefined) return "";
  return "bin-other";
}

function isPickedInLayer(layerIndex, x, y) {
  return picksByLayer[layerIndex].some((p) => p.x === x && p.y === y);
}

// Whether (x,y) is already used by ANY layer sharing the one physical
// wafer — the fix for "很容易點錯...座標不要重複": a given die site can
// only ever be consumed once, so it must not be pickable twice under two
// different layers. Only meaningful outside multi-wafer mode.
function isPickedAcrossSharedLayers(x, y) {
  const n = effectiveNumLayers();
  for (let i = 0; i < n; i++) {
    if (isPickedInLayer(i, x, y)) return true;
  }
  return false;
}

function addPickToLayer(layerIndex, x, y, bin) {
  if (bin !== "1") return false;
  const blocked = multiWaferEnabled ? isPickedInLayer(layerIndex, x, y) : isPickedAcrossSharedLayers(x, y);
  if (blocked) return false;
  picksByLayer[layerIndex].push({ x, y, bin });
  return true;
}

const GRID_AXIS_SIZE = 20; // must match .grid-axis-cell's width/height in style.css

function renderWaferPanel(panelIndex) {
  const ids = waferIds(panelIndex);
  const container = document.getElementById(ids.grid);
  if (!container) return;
  container.innerHTML = "";
  const cells = waferCellsByLayer[panelIndex];
  const bounds = waferBoundsByLayer[panelIndex];
  if (!bounds) {
    renderWaferOverlayInto(ids.overlay, ids.grid, null);
    return;
  }
  const { minX, maxX, minY, maxY } = bounds;

  // X axis is rendered right-to-left (0 at the right edge) to match the
  // real WaferCoordinate.exe tool's convention, where the wafer's origin
  // (0,0) sits at the top-right, not top-left — confirmed against a photo
  // of the real tool. Only the display order changes here; dataset.x/y on
  // each cell still carries the real coordinate.
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

  // In shared-wafer mode this one panel shows every layer's picks
  // overlaid (a cell can belong to at most one layer, since picks are
  // deduped across all of them); in multi-wafer mode this panel only
  // shows its own dedicated layer's picks.
  const layersOnThisPanel = multiWaferEnabled ? [panelIndex] : Array.from({ length: effectiveNumLayers() }, (_, i) => i);

  for (let y = minY; y <= maxY; y++) {
    const row = document.createElement("div");
    row.className = "wafer-row";
    const rowLabel = document.createElement("div");
    rowLabel.className = "grid-axis-cell";
    rowLabel.textContent = y;
    row.appendChild(rowLabel);
    for (let x = maxX; x >= minX; x--) {
      const bin = cells.get(`${x},${y}`);
      const cell = document.createElement("div");
      cell.className = "wafer-cell " + cellClass(bin);
      let pickedLayer = null;
      let focusedLayer = null;
      for (const li of layersOnThisPanel) {
        if (pickedLayer === null && isPickedInLayer(li, x, y)) pickedLayer = li;
        const f = focusedWaferXYByLayer[li];
        if (focusedLayer === null && f && f.x === x && f.y === y) focusedLayer = li;
      }
      if (pickedLayer !== null) {
        cell.classList.add("picked");
        cell.textContent = String(pickedLayer + 1);
      }
      if (focusedLayer !== null) cell.classList.add("focus");
      cell.dataset.x = x;
      cell.dataset.y = y;
      cell.dataset.bin = bin === undefined ? "" : bin;
      row.appendChild(cell);
    }
    container.appendChild(row);
  }
  renderWaferOverlayInto(ids.overlay, ids.grid, bounds);
}

function renderWaferOverlayInto(overlayId, containerId, bounds) {
  const svg = document.getElementById(overlayId);
  const grid = document.getElementById(containerId);
  if (!svg || !grid) return;
  if (!bounds) {
    svg.setAttribute("width", 0);
    svg.setAttribute("height", 0);
    svg.innerHTML = "";
    return;
  }
  // Offset by one axis-label row/column so the overlay only covers the
  // actual cell area, not the coordinate labels.
  const w = grid.offsetWidth - GRID_AXIS_SIZE;
  const h = grid.offsetHeight - GRID_AXIS_SIZE;
  svg.style.left = GRID_AXIS_SIZE + "px";
  svg.style.top = GRID_AXIS_SIZE + "px";
  svg.setAttribute("width", w);
  svg.setAttribute("height", h);
  // Approximate reference guide only — inscribed in the loaded grid's own
  // bounding box, not a calibrated wafer diameter. Mirrors the blue
  // ellipse + red crosshair WaferCoordinate.exe draws over its grid.
  svg.innerHTML = `
    <ellipse cx="${w / 2}" cy="${h / 2}" rx="${Math.max(w / 2 - 1, 0)}" ry="${Math.max(h / 2 - 1, 0)}"
      fill="none" stroke="#1a3fd6" stroke-width="1.5" opacity="0.5" />
    <line x1="0" y1="${h / 2}" x2="${w}" y2="${h / 2}" stroke="#e04b4b" stroke-width="1" opacity="0.45" />
    <line x1="${w / 2}" y1="0" x2="${w / 2}" y2="${h}" stroke="#e04b4b" stroke-width="1" opacity="0.45" />
  `;
}

function renderWaferGrid() {
  const n = effectiveNumLayers();
  if (multiWaferEnabled) {
    for (let i = 0; i < n; i++) renderWaferPanel(i);
  } else {
    renderWaferPanel(0);
  }
}

function scanRectangle(x1, x2, y1, y2, panelIndex) {
  const xLo = Math.min(x1, x2), xHi = Math.max(x1, x2);
  const yLo = Math.min(y1, y2), yHi = Math.max(y1, y2);
  const cells = waferCellsByLayer[panelIndex];
  const layerIndex = multiWaferEnabled ? panelIndex : currentLayerIndex;
  for (let x = xLo; x <= xHi; x++) {
    for (let y = yLo; y <= yHi; y++) {
      addPickToLayer(layerIndex, x, y, cells.get(`${x},${y}`));
    }
  }
}

// ---- Pick table -----------------------------------------------------------
function renderPickTableInto(tableId, layerPicks) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  if (!tbody) return;
  tbody.innerHTML = "";
  layerPicks.forEach((p, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${i + 1}</td><td>${p.x}</td><td>${p.y}</td><td>${p.bin}</td>
      <td><button data-idx="${i}" class="remove-btn">x</button></td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll(".remove-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      layerPicks.splice(parseInt(btn.dataset.idx, 10), 1);
      renderAll();
    });
  });
}

function renderPickTable() {
  // Each BINGO MAP block owns its own table, driven directly by its own
  // layer's picks — not by the "active layer" alias, so every layer stays
  // visible and manageable at once regardless of which layer new wafer
  // clicks are currently routed to.
  const n = effectiveNumLayers();
  for (let i = 0; i < n; i++) {
    const ids = bingoIds(i);
    renderPickTableInto(ids.table, picksByLayer[i]);
  }
}

// ---- Status / progress ----------------------------------------------------
function effectiveTargetQty() {
  // Positions marked "不上片" reduce how many dies are actually needed —
  // mirrors /api/generate's own skip_positions handling server-side.
  if (targetQty === null) return null;
  return targetQty - skippedPositions.size;
}

function renderQtyStatus() {
  const el = document.getElementById("qty-status");
  const effTarget = effectiveTargetQty();
  const target = effTarget === null ? "?" : effTarget;
  const skipNote = skippedPositions.size ? `（已標記不上片 ${skippedPositions.size} 格，目標已扣除）` : "";
  const n = effectiveNumLayers();

  if (n > 1) {
    const doneFlags = picksByLayer.slice(0, n).map((picks) => effTarget !== null && picks.length === effTarget);
    el.textContent = picksByLayer
      .slice(0, n)
      .map((picks, i) => `第${i + 1}層已選擇 ${picks.length} / 目標 ${target}`)
      .join("　") + skipNote;
    el.className = doneFlags.every(Boolean) ? "ok" : "bad";
    for (let i = 0; i < n; i++) {
      const badge = document.getElementById(bingoIds(i).qty);
      if (!badge) continue;
      badge.textContent = `${picksByLayer[i].length} / ${target}`;
      badge.className = "badge " + (doneFlags[i] ? "ok" : "bad");
    }
    if (effTarget === null) return;
    if (doneFlags.every(Boolean)) {
      setStepFlow(4, { done: [1, 2, 3] });
    } else if (picksByLayer.slice(0, n).some((p) => p.length > 0) || waferBoundsByLayer[0]) {
      setStepFlow(3, { done: [1, 2] });
    }
    return;
  }

  const picks = picksByLayer[0];
  el.textContent = `已選擇 ${picks.length} / 目標 ${target}${skipNote}`;
  const matched = effTarget !== null && picks.length === effTarget;
  el.className = matched ? "ok" : "bad";
  const primaryBadge = document.getElementById("qty-status-primary");
  if (primaryBadge) {
    primaryBadge.textContent = "";
    primaryBadge.className = "badge";
  }
  if (effTarget === null) return;
  if (matched) {
    setStepFlow(4, { done: [1, 2, 3] });
  } else if (picks.length > 0 || waferBoundsByLayer[0]) {
    setStepFlow(3, { done: [1, 2] });
  }
}

function renderLayerStatus() {
  const status = document.getElementById("layer-status");
  const n = effectiveNumLayers();
  if (n <= 1) {
    status.textContent = "";
    return;
  }
  const effTarget = effectiveTargetQty();
  const target = effTarget === null ? "?" : effTarget;
  const counts = picksByLayer.slice(0, n).map((p, i) => `第${i + 1}層 ${p.length}/${target}`).join("，");
  if (multiWaferEnabled) {
    status.textContent = `多wafer模式：每張wafer圖點選只會加入自己那一層（${counts}）`;
  } else {
    status.textContent = `目前wafer圖點選會加入：第${currentLayerIndex + 1}層（${counts}）`;
  }
}

function renderAll() {
  renderWaferGrid();
  renderSubstrateGrid();
  renderPickTable();
  renderQtyStatus();
  renderLayerStatus();
}

// ---- Floating tooltip -------------------------------------------------
// Follows the cursor over a grid, so the coordinate is visible right where
// you're looking instead of only in a fixed status line that can be
// scrolled out of view on a big grid. `cell` must be a descendant of
// `tooltipEl`'s own parent (the *-wrap container) so offsetLeft/offsetTop
// are relative to that same positioned ancestor.
function showGridTooltip(tooltipEl, cell, text) {
  if (!tooltipEl) return;
  tooltipEl.textContent = text;
  tooltipEl.style.left = `${cell.offsetLeft + cell.offsetWidth / 2}px`;
  tooltipEl.style.top = `${cell.offsetTop}px`;
  tooltipEl.classList.add("visible");
}

function hideGridTooltip(tooltipEl) {
  if (tooltipEl) tooltipEl.classList.remove("visible");
}

// ---- Event wiring (per wafer panel / per BINGO MAP block) ------------
function wireGridDragEvents(containerId, hoverStatusId, tooltipId, panelIndex) {
  const container = document.getElementById(containerId);
  const hoverStatus = document.getElementById(hoverStatusId);
  const tooltip = document.getElementById(tooltipId);
  let localDragStart = null;
  container.addEventListener("mousedown", (e) => {
    if (!e.target.classList.contains("wafer-cell")) return;
    localDragStart = { x: parseInt(e.target.dataset.x, 10), y: parseInt(e.target.dataset.y, 10) };
  });
  container.addEventListener("mouseup", (e) => {
    if (!e.target.classList.contains("wafer-cell") || !localDragStart) return;
    const end = { x: parseInt(e.target.dataset.x, 10), y: parseInt(e.target.dataset.y, 10) };
    if (end.x === localDragStart.x && end.y === localDragStart.y) {
      const layerIndex = multiWaferEnabled ? panelIndex : currentLayerIndex;
      addPickToLayer(layerIndex, end.x, end.y, e.target.dataset.bin);
    } else {
      scanRectangle(localDragStart.x, end.x, localDragStart.y, end.y, panelIndex);
    }
    localDragStart = null;
    renderAll();
  });
  container.addEventListener("mouseover", (e) => {
    if (!e.target.classList.contains("wafer-cell")) return;
    hoverStatus.textContent = `Wafer座標：${e.target.dataset.x}:${e.target.dataset.y}`;
    showGridTooltip(tooltip, e.target, `${e.target.dataset.x}:${e.target.dataset.y}`);
  });
  container.addEventListener("mouseleave", () => {
    hoverStatus.textContent = "滑鼠移到格子上會顯示座標";
    hideGridTooltip(tooltip);
  });
}

function wireSubstrateGridClicks(containerId, hoverStatusId, tooltipId, layerIndex) {
  const container = document.getElementById(containerId);
  const hoverStatus = document.getElementById(hoverStatusId);
  const tooltip = document.getElementById(tooltipId);
  container.addEventListener("click", (e) => {
    if (!e.target.classList.contains("substrate-cell")) return;
    const pos = e.target.dataset.pos;
    if (skipModeEnabled) {
      if (skippedPositions.has(pos)) skippedPositions.delete(pos);
      else skippedPositions.add(pos);
      renderAll();
      return;
    }
    reverseLookupSubstratePos(pos, layerIndex);
  });
  if (hoverStatus) {
    container.addEventListener("mouseover", (e) => {
      if (!e.target.classList.contains("substrate-cell")) return;
      hoverStatus.textContent = `基板座標：${e.target.dataset.pos}`;
      showGridTooltip(tooltip, e.target, e.target.dataset.pos);
    });
    container.addEventListener("mouseleave", () => {
      hoverStatus.textContent = "滑鼠移到格子上會顯示座標";
      hideGridTooltip(tooltip);
    });
  }
}

function wireWaferPanelEvents(panelIndex) {
  const ids = waferIds(panelIndex);
  document.getElementById(ids.btnLoadFrm).addEventListener("click", () => loadFrmIntoPanel(panelIndex));
  document.getElementById(ids.btnLoadWafer).addEventListener("click", () => {
    const { cells, bounds } = parseWaferText(document.getElementById(ids.waferInput).value);
    waferCellsByLayer[panelIndex] = cells;
    waferBoundsByLayer[panelIndex] = bounds;
    renderAll();
  });
  wireGridDragEvents(ids.grid, ids.hoverStatus, ids.tooltip, panelIndex);
}

function wireBingoBlockEvents(layerIndex) {
  const ids = bingoIds(layerIndex);
  wireSubstrateGridClicks(ids.grid, ids.hoverStatus, ids.tooltip, layerIndex);
}

// ---- Skip mode --------------------------------------------------------
function setSkipMode(enabled) {
  skipModeEnabled = enabled;
  const btn = document.getElementById("btn-skip-mode");
  btn.textContent = `標記「不上片」模式：${enabled ? "開啟" : "關閉"}`;
  btn.classList.toggle("skip-mode-on", enabled);
  document.getElementById("substrate-mode-hint").textContent = enabled
    ? "目前是「不上片」標記模式：點基板圖上任一格＝標記/取消該格不上片（黃色＝跳過，不會被wafer座標填入）。"
    : "點基板圖上任一格，可以反查它對應到哪個wafer座標（會在下方wafer圖上用橘框標示出來）。";
}

function setActiveLayer(layerIndex) {
  currentLayerIndex = layerIndex;
  document.querySelectorAll("#layer-switch button").forEach((btn) => {
    btn.classList.toggle("active-layer", parseInt(btn.dataset.layerIndex, 10) === layerIndex);
  });
  renderAll();
}

// ---- Generate -----------------------------------------------------------
async function generateStrate() {
  const status = document.getElementById("generate-status");
  status.className = "";
  status.textContent = "產生中...";

  const startTimeRaw = document.getElementById("start_time").value; // "YYYY-MM-DDTHH:MM"
  const payload = {
    ...headerPayload(),
    wafer_ring: document.getElementById("wafer_ring").value,
    start_time: startTimeRaw.length === 16 ? startTimeRaw + ":00" : startTimeRaw,
    interval_seconds: document.getElementById("interval_seconds").value,
    skip_positions: Array.from(skippedPositions),
  };
  if (multiLayerEnabled) {
    payload.layers = picksByLayer.slice(0, numLayers);
  } else {
    payload.selections = picksByLayer[0];
  }
  if (usingTemplate) {
    // Send the template's own position order verbatim so the backend
    // bypasses convention/machine_type re-derivation entirely.
    payload.template_positions = substratePositions;
  }

  const res = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const data = await res.json();
    status.className = "error";
    status.textContent = data.error;
    return;
  }

  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="(.+)"/);
  const filename = match ? match[1] : "output.strate";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  status.className = "ok";
  status.textContent = `已產生並下載：${filename}`;
  setStepFlow(4, { done: [1, 2, 3, 4] });
}

// ---- Initial wiring ---------------------------------------------------
document.getElementById("btn-blank").addEventListener("click", loadBlank);
document.getElementById("template-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const text = await file.text();
  document.getElementById("template-text").value = text;
  loadTemplate(text);
});
document.getElementById("btn-load-template").addEventListener("click", () => {
  loadTemplate(document.getElementById("template-text").value);
});
document.getElementById("btn-clear").addEventListener("click", () => {
  resetLayerState();
  renderAll();
});
document.getElementById("btn-generate").addEventListener("click", generateStrate);

document.getElementById("multi_layer_enabled").addEventListener("change", (e) => {
  multiLayerEnabled = e.target.checked;
  document.getElementById("multi-layer-fields").style.display = multiLayerEnabled ? "" : "none";
  document.getElementById("multi-wafer-field").style.display = multiLayerEnabled ? "" : "none";
  if (!multiLayerEnabled) {
    multiWaferEnabled = false;
    document.getElementById("multi_wafer_enabled").checked = false;
  }
  resetLayerState();
  rebuildLayerUi();
  renderAll();
});
document.getElementById("num_layers").addEventListener("change", (e) => {
  const n = parseInt(e.target.value, 10);
  numLayers = Number.isFinite(n) && n >= 2 ? n : 2;
  e.target.value = numLayers;
  resetLayerState();
  rebuildLayerUi();
  renderAll();
});
document.getElementById("multi_wafer_enabled").addEventListener("change", (e) => {
  multiWaferEnabled = e.target.checked;
  resetLayerState();
  rebuildLayerUi();
  renderAll();
});

wireWaferPanelEvents(0);
wireBingoBlockEvents(0);
document.getElementById("btn-skip-mode").addEventListener("click", () => setSkipMode(!skipModeEnabled));
setSkipMode(false);
rebuildLayerUi();
renderQtyStatus();
