let targetQty = null;
let picksPrimary = []; // {x, y, bin}[] — layer f9=primary_layer (or the only layer, single-layer mode)
let picksOther = []; // layer f9=other_layer, only used when twoLayerEnabled
let picks = picksPrimary; // alias to whichever layer is "active" for the shared wafer grid; reassigned by setActiveLayer()
let twoLayerEnabled = false;
let dualWaferEnabled = false; // true = primary/other layers come from two independently-loaded wafers
let currentLayerKey = "primary"; // "primary" | "other" — which layer the shared wafer grid's clicks feed
let waferCells = new Map(); // "x,y" -> bin — primary wafer (also the only/shared wafer outside dual-wafer mode)
let waferBounds = null;
let waferCellsOther = new Map(); // only used when dualWaferEnabled
let waferBoundsOther = null;
let dragStart = null;
let dragStartOther = null;
let substratePositions = []; // ["col:row", ...] in blank_generator's own machine-type order — shared by both layers
let substrateBounds = null; // {minCol, maxCol, minRow, maxRow}
let focusedSubstratePos = null; // "col:row" clicked in the primary BINGO MAP, for reverse lookup
let focusedSubstratePosOther = null; // same, for the other-layer BINGO MAP
let focusedWaferXY = null; // {x, y} the focused primary-layer position maps to, if filled
let focusedWaferXYOther = null; // {x, y} the focused other-layer position maps to, if filled
let usingTemplate = false; // true once a template .strate has been loaded via loadTemplate()
let skippedPositions = new Set(); // "col:row" substrate positions marked "不上片" — excluded from the fill order
let skipModeEnabled = false; // true = clicking a substrate cell toggles skip instead of reverse-lookup

function setActiveLayer(key) {
  currentLayerKey = key;
  picks = key === "primary" ? picksPrimary : picksOther;
  document.getElementById("btn-layer-primary").classList.toggle("active-layer", key === "primary");
  document.getElementById("btn-layer-other").classList.toggle("active-layer", key === "other");
  renderAll();
}

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

  picksPrimary.length = 0;
  picksPrimary.push(...data.picks);
  picksOther.length = 0;

  const checkbox = document.getElementById("two_layer_enabled");
  twoLayerEnabled = data.two_layer;
  checkbox.checked = twoLayerEnabled;
  setTwoLayerUiVisibility();
  if (twoLayerEnabled) {
    document.getElementById("primary_layer").value = data.primary_layer;
    document.getElementById("other_layer").value = data.other_layer;
    document.getElementById("layer-primary-label").textContent = data.primary_layer;
    document.getElementById("layer-other-label").textContent = data.other_layer;
    picksOther.push(...data.other_picks);
  }
  setActiveLayer("primary"); // also calls renderAll()

  status.className = "ok";
  const otherNote = twoLayerEnabled ? `（含次層 ${data.other_picks.length} 顆）` : "";
  status.textContent =
    `已載入範本：共 ${data.total_qty} 個基板位置、主層已對應 ${data.picks.length} 顆${otherNote}。` +
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

function renderSubstrateGridInto(containerId, layerPicks, focusedPos) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  if (!substrateBounds) return;
  // First N picks (in click/scan order) fill the first N *fillable*
  // positions of the blank skeleton's own order (skipping any marked
  // "不上片") — this mirrors exactly what assign_dies() does at generate
  // time, so this preview is never out of sync with the real output.
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
  renderSubstrateGridInto("substrate-grid", picksPrimary, focusedSubstratePos);
  if (twoLayerEnabled) {
    renderSubstrateGridInto("substrate-grid-other", picksOther, focusedSubstratePosOther);
  }
}

function reverseLookupSubstratePos(pos, layer) {
  const status = document.getElementById("lookup-status");
  const layerPicks = layer === "other" ? picksOther : picksPrimary;
  const layerLabel = twoLayerEnabled ? (layer === "other" ? "次層：" : "主層：") : "";
  if (layer === "other") focusedSubstratePosOther = pos;
  else focusedSubstratePos = pos;

  if (skippedPositions.has(pos)) {
    if (layer === "other") focusedWaferXYOther = null;
    else focusedWaferXY = null;
    status.textContent = `${layerLabel}基板位置 ${pos} 已標記「不上片」，不會對應到任何wafer座標`;
    status.className = "notice";
    renderAll();
    return;
  }
  const index = fillablePositions().indexOf(pos);
  const isFilled = index >= 0 && index < layerPicks.length;
  const targetGridId = layer === "other" && dualWaferEnabled ? "wafer-grid-other" : "wafer-grid";
  if (isFilled) {
    const pick = layerPicks[index];
    if (layer === "other") focusedWaferXYOther = { x: pick.x, y: pick.y };
    else focusedWaferXY = { x: pick.x, y: pick.y };
    status.textContent = `${layerLabel}基板位置 ${pos} ↔ Wafer座標 ${pick.x}:${pick.y}（第 ${index + 1} 顆）`;
    status.className = "notice";
  } else {
    if (layer === "other") focusedWaferXYOther = null;
    else focusedWaferXY = null;
    status.textContent = `${layerLabel}基板位置 ${pos} 尚未對應到任何wafer座標（還沒點選到這一格）`;
    status.className = "notice";
  }
  renderAll();
  const waferCellEl = document.querySelector(`#${targetGridId} .wafer-cell.focus`);
  if (waferCellEl) waferCellEl.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
}

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

async function loadFrmInto(prefix, targetIsOther) {
  const status = document.getElementById(`frm-status${prefix}`);
  status.className = "";
  status.textContent = "讀取中...";
  const payload = {
    lot_no: document.getElementById(`frm_lot_no${prefix}`).value,
    barcode_id: document.getElementById(`frm_barcode_id${prefix}`).value,
    frm_path: document.getElementById(`frm_path${prefix}`).value,
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
  if (targetIsOther) {
    waferCellsOther = cells;
    waferBoundsOther = bounds;
  } else {
    waferCells = cells;
    waferBounds = bounds;
  }
  status.className = "ok";
  status.textContent = `已載入 LotNo=${data.lot_no} WaferID=${data.wafer_id} Layout=${data.wafer_type}（${data.columns}x${data.rows}，共${data.cells.length}顆有資料）`;
  renderAll();
}

function cellClass(bin) {
  if (bin === "1") return "bin-1";
  if (bin === undefined) return "";
  return "bin-other";
}

function isPickedIn(layerPicks, x, y) {
  return layerPicks.some((p) => p.x === x && p.y === y);
}

// Whether (x,y) is already used by EITHER layer — the fix for "很容易點錯
// ...座標不要重複": when both layers share one physical wafer, a given die
// site can only ever be consumed once, so it must not be pickable twice
// under two different layers. Only meaningful outside dual-wafer mode.
function isPickedGlobal(x, y) {
  return isPickedIn(picksPrimary, x, y) || isPickedIn(picksOther, x, y);
}

const GRID_AXIS_SIZE = 20; // must match .grid-axis-cell's width/height in style.css

function renderWaferGridInto(containerId, overlayId, cells, bounds, gridKind) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";
  if (!bounds) {
    renderWaferOverlayInto(overlayId, containerId, null);
    return;
  }
  const { minX, maxX, minY, maxY } = bounds;

  // X axis is rendered right-to-left (0 at the right edge) to match the
  // real WaferCoordinate.exe tool's convention, where the wafer's origin
  // (0,0) sits at the top-right, not top-left. Confirmed against a photo
  // of the real tool the user sent — its column header reads high→low
  // left to right. Only the display order changes here; dataset.x/y on
  // each cell still carries the real coordinate, so picking/dragging/
  // reverse-lookup are unaffected.
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

  const focusPrimary = focusedWaferXY;
  // In shared-wafer two-layer mode (not dual-wafer), the other layer's
  // focused coordinate lives on this same grid too.
  const focusOtherHere = gridKind === "primary" && twoLayerEnabled && !dualWaferEnabled ? focusedWaferXYOther : null;
  const focusHere = gridKind === "other" ? focusedWaferXYOther : focusPrimary;

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
      if (gridKind === "primary") {
        if (isPickedIn(picksPrimary, x, y)) cell.classList.add("picked");
        if (twoLayerEnabled && !dualWaferEnabled && isPickedIn(picksOther, x, y)) cell.classList.add("picked-other");
      } else {
        if (isPickedIn(picksOther, x, y)) cell.classList.add("picked");
      }
      if (focusHere && focusHere.x === x && focusHere.y === y) cell.classList.add("focus");
      if (focusOtherHere && focusOtherHere.x === x && focusOtherHere.y === y) cell.classList.add("focus");
      cell.dataset.x = x;
      cell.dataset.y = y;
      cell.dataset.bin = bin === undefined ? "" : bin;
      row.appendChild(cell);
    }
    container.appendChild(row);
  }
  renderWaferOverlayInto(overlayId, containerId, bounds);
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
  renderWaferGridInto("wafer-grid", "wafer-overlay", waferCells, waferBounds, "primary");
  if (dualWaferEnabled) {
    renderWaferGridInto("wafer-grid-other", "wafer-overlay-other", waferCellsOther, waferBoundsOther, "other");
  }
}

function addPickPrimaryGrid(x, y, bin) {
  if (bin !== "1") return false;
  const sharedTwoLayer = twoLayerEnabled && !dualWaferEnabled;
  if (sharedTwoLayer ? isPickedGlobal(x, y) : isPickedIn(picksPrimary, x, y)) return false;
  (sharedTwoLayer ? picks : picksPrimary).push({ x, y, bin });
  return true;
}

function addPickOtherGrid(x, y, bin) {
  // Only used when dualWaferEnabled — this grid's data is an independent
  // physical wafer, so it only ever feeds picksOther with its own scope.
  if (bin !== "1") return false;
  if (isPickedIn(picksOther, x, y)) return false;
  picksOther.push({ x, y, bin });
  return true;
}

function scanRectangle(x1, x2, y1, y2, gridKind = "primary") {
  const xLo = Math.min(x1, x2), xHi = Math.max(x1, x2);
  const yLo = Math.min(y1, y2), yHi = Math.max(y1, y2);
  const cells = gridKind === "other" ? waferCellsOther : waferCells;
  const addFn = gridKind === "other" ? addPickOtherGrid : addPickPrimaryGrid;
  for (let x = xLo; x <= xHi; x++) {
    for (let y = yLo; y <= yHi; y++) {
      addFn(x, y, cells.get(`${x},${y}`));
    }
  }
}

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
  // layer's picks — not by the "active layer" alias, so both stay visible
  // and manageable at once regardless of which layer new wafer clicks are
  // currently routed to.
  renderPickTableInto("pick-table", picksPrimary);
  if (twoLayerEnabled) {
    renderPickTableInto("pick-table-other", picksOther);
  }
}

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

  const primaryBadge = document.getElementById("qty-status-primary");
  const otherBadge = document.getElementById("qty-status-other");

  if (twoLayerEnabled) {
    const primaryDone = effTarget !== null && picksPrimary.length === effTarget;
    const otherDone = effTarget !== null && picksOther.length === effTarget;
    el.textContent = `主層已選擇 ${picksPrimary.length} / 目標 ${target}　次層已選擇 ${picksOther.length} / 目標 ${target}${skipNote}`;
    el.className = primaryDone && otherDone ? "ok" : "bad";
    if (primaryBadge) {
      primaryBadge.textContent = `${picksPrimary.length} / ${target}`;
      primaryBadge.className = "badge " + (primaryDone ? "ok" : "bad");
    }
    if (otherBadge) {
      otherBadge.textContent = `${picksOther.length} / ${target}`;
      otherBadge.className = "badge " + (otherDone ? "ok" : "bad");
    }
    if (effTarget === null) return;
    if (primaryDone && otherDone) {
      setStepFlow(4, { done: [1, 2, 3] });
    } else if (picksPrimary.length > 0 || picksOther.length > 0 || waferBounds) {
      setStepFlow(3, { done: [1, 2] });
    }
    return;
  }

  el.textContent = `已選擇 ${picks.length} / 目標 ${target}${skipNote}`;
  const matched = effTarget !== null && picks.length === effTarget;
  el.className = matched ? "ok" : "bad";
  if (primaryBadge) {
    primaryBadge.textContent = "";
    primaryBadge.className = "badge";
  }
  if (effTarget === null) return;
  if (matched) {
    setStepFlow(4, { done: [1, 2, 3] });
  } else if (picks.length > 0 || waferBounds) {
    setStepFlow(3, { done: [1, 2] });
  }
}

function renderLayerStatus() {
  const status = document.getElementById("layer-status");
  if (!twoLayerEnabled) {
    status.textContent = "";
    return;
  }
  const effTarget = effectiveTargetQty();
  const target = effTarget === null ? "?" : effTarget;
  if (dualWaferEnabled) {
    status.textContent = `雙wafer模式：左圖(主層 wafer)點選會加入主層，右圖(次層 wafer)點選會加入次層（主層 ${picksPrimary.length}/${target}，次層 ${picksOther.length}/${target}）`;
  } else {
    const layerName = currentLayerKey === "primary" ? "主層" : "次層";
    status.textContent = `目前wafer圖點選會加入：${layerName}（主層 ${picksPrimary.length}/${target}，次層 ${picksOther.length}/${target}）`;
  }
}

function renderAll() {
  renderWaferGrid();
  renderSubstrateGrid();
  renderPickTable();
  renderQtyStatus();
  renderLayerStatus();
}

function wireGridDragEvents(containerId, hoverStatusId, gridKindForPick) {
  const container = document.getElementById(containerId);
  const hoverStatus = document.getElementById(hoverStatusId);
  let localDragStart = null;
  container.addEventListener("mousedown", (e) => {
    if (!e.target.classList.contains("wafer-cell")) return;
    localDragStart = { x: parseInt(e.target.dataset.x, 10), y: parseInt(e.target.dataset.y, 10) };
  });
  container.addEventListener("mouseup", (e) => {
    if (!e.target.classList.contains("wafer-cell") || !localDragStart) return;
    const end = { x: parseInt(e.target.dataset.x, 10), y: parseInt(e.target.dataset.y, 10) };
    if (end.x === localDragStart.x && end.y === localDragStart.y) {
      (gridKindForPick === "other" ? addPickOtherGrid : addPickPrimaryGrid)(end.x, end.y, e.target.dataset.bin);
    } else {
      scanRectangle(localDragStart.x, end.x, localDragStart.y, end.y, gridKindForPick);
    }
    localDragStart = null;
    renderAll();
  });
  container.addEventListener("mouseover", (e) => {
    if (!e.target.classList.contains("wafer-cell")) return;
    hoverStatus.textContent = `Wafer座標：${e.target.dataset.x}:${e.target.dataset.y}`;
  });
  container.addEventListener("mouseleave", () => {
    hoverStatus.textContent = "滑鼠移到格子上會顯示座標";
  });
}

function setSkipMode(enabled) {
  skipModeEnabled = enabled;
  const btn = document.getElementById("btn-skip-mode");
  btn.textContent = `標記「不上片」模式：${enabled ? "開啟" : "關閉"}`;
  btn.classList.toggle("skip-mode-on", enabled);
  document.getElementById("substrate-mode-hint").textContent = enabled
    ? "目前是「不上片」標記模式：點基板圖上任一格＝標記/取消該格不上片（黃色＝跳過，不會被wafer座標填入）。"
    : "點基板圖上任一格，可以反查它對應到哪個wafer座標（會在下方wafer圖上用橘框標示出來）。";
}

function wireSubstrateGridClicks(containerId, hoverStatusId, layer) {
  const container = document.getElementById(containerId);
  const hoverStatus = document.getElementById(hoverStatusId);
  container.addEventListener("click", (e) => {
    if (!e.target.classList.contains("substrate-cell")) return;
    const pos = e.target.dataset.pos;
    if (skipModeEnabled) {
      if (skippedPositions.has(pos)) skippedPositions.delete(pos);
      else skippedPositions.add(pos);
      renderAll();
      return;
    }
    reverseLookupSubstratePos(pos, layer);
  });
  if (hoverStatus) {
    container.addEventListener("mouseover", (e) => {
      if (!e.target.classList.contains("substrate-cell")) return;
      hoverStatus.textContent = `基板座標：${e.target.dataset.pos}`;
    });
    container.addEventListener("mouseleave", () => {
      hoverStatus.textContent = "滑鼠移到格子上會顯示座標";
    });
  }
}

function setTwoLayerUiVisibility() {
  document.getElementById("two-layer-fields").style.display = twoLayerEnabled ? "" : "none";
  document.getElementById("dual-wafer-field").style.display = twoLayerEnabled ? "" : "none";
  document.getElementById("bingo-map-block-other").style.display = twoLayerEnabled ? "" : "none";
  document.getElementById("bingo-map-title-primary").textContent = twoLayerEnabled ? "主層 BINGO MAP" : "BINGO MAP";
  document.getElementById("wafer-legend-other-picked").style.display = twoLayerEnabled && !dualWaferEnabled ? "" : "none";
  document.getElementById("layer-switch").style.display = twoLayerEnabled && !dualWaferEnabled ? "" : "none";
  document.getElementById("wafer-panel-title-suffix").textContent = twoLayerEnabled
    ? dualWaferEnabled ? " — 主層" : "（主層/次層共用，點選會加入下方選定的層）"
    : "";
  document.getElementById("wafer-panel-other").style.display = twoLayerEnabled && dualWaferEnabled ? "" : "none";
}

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
  if (twoLayerEnabled) {
    payload.two_layer = true;
    payload.primary_selections = picksPrimary;
    payload.other_selections = picksOther;
    payload.primary_layer = document.getElementById("primary_layer").value;
    payload.other_layer = document.getElementById("other_layer").value;
  } else {
    payload.selections = picks;
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
document.getElementById("btn-load-frm").addEventListener("click", () => loadFrmInto("", false));
document.getElementById("btn-load-wafer").addEventListener("click", () => {
  const { cells, bounds } = parseWaferText(document.getElementById("wafer-input").value);
  waferCells = cells;
  waferBounds = bounds;
  renderAll();
});
document.getElementById("btn-load-frm-other").addEventListener("click", () => loadFrmInto("_other", true));
document.getElementById("btn-load-wafer-other").addEventListener("click", () => {
  const { cells, bounds } = parseWaferText(document.getElementById("wafer-input-other").value);
  waferCellsOther = cells;
  waferBoundsOther = bounds;
  renderAll();
});
document.getElementById("btn-clear").addEventListener("click", () => {
  picksPrimary.length = 0;
  picksOther.length = 0;
  focusedSubstratePos = null;
  focusedSubstratePosOther = null;
  focusedWaferXY = null;
  focusedWaferXYOther = null;
  document.getElementById("lookup-status").textContent = "";
  renderAll();
});
document.getElementById("btn-generate").addEventListener("click", generateStrate);
document.getElementById("two_layer_enabled").addEventListener("change", (e) => {
  twoLayerEnabled = e.target.checked;
  if (!twoLayerEnabled) {
    dualWaferEnabled = false;
    document.getElementById("dual_wafer_enabled").checked = false;
  }
  setTwoLayerUiVisibility();
  setActiveLayer("primary");
});
document.getElementById("dual_wafer_enabled").addEventListener("change", (e) => {
  dualWaferEnabled = e.target.checked;
  setTwoLayerUiVisibility();
  renderAll();
});
document.getElementById("primary_layer").addEventListener("input", (e) => {
  document.getElementById("layer-primary-label").textContent = e.target.value;
});
document.getElementById("other_layer").addEventListener("input", (e) => {
  document.getElementById("layer-other-label").textContent = e.target.value;
});
document.getElementById("btn-layer-primary").addEventListener("click", () => setActiveLayer("primary"));
document.getElementById("btn-layer-other").addEventListener("click", () => setActiveLayer("other"));
wireGridDragEvents("wafer-grid", "wafer-hover-status", "primary");
wireGridDragEvents("wafer-grid-other", "wafer-hover-status-other", "other");
wireSubstrateGridClicks("substrate-grid", "substrate-hover-status", "primary");
wireSubstrateGridClicks("substrate-grid-other", "substrate-hover-status-other", "other");
document.getElementById("btn-skip-mode").addEventListener("click", () => setSkipMode(!skipModeEnabled));
setSkipMode(false);
setTwoLayerUiVisibility();
renderQtyStatus();
