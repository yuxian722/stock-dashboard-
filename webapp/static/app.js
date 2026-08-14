let targetQty = null;
let picksPrimary = []; // {x, y, bin}[] — layer f9=primary_layer (or the only layer, single-layer mode)
let picksOther = []; // layer f9=other_layer, only used when twoLayerEnabled
let picks = picksPrimary; // alias to whichever layer is currently active; reassigned by setActiveLayer()
let twoLayerEnabled = false;
let currentLayerKey = "primary"; // "primary" | "other"
let waferCells = new Map(); // "x,y" -> bin
let waferBounds = null;
let dragStart = null;
let substratePositions = []; // ["col:row", ...] in blank_generator's own machine-type order
let substrateBounds = null; // {minCol, maxCol, minRow, maxRow}
let focusedSubstratePos = null; // "col:row" clicked in the substrate grid, for reverse lookup
let focusedWaferXY = null; // {x, y} the focused substrate position maps to, if filled

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

function renderSubstrateGrid() {
  const container = document.getElementById("substrate-grid");
  container.innerHTML = "";
  if (!substrateBounds) return;
  // First N picks (in click/scan order) fill the first N positions of the
  // blank skeleton's own order — this mirrors exactly what assign_dies()
  // does at generate time (zips picks with blank.die_info positionally),
  // so this preview is never out of sync with the real output.
  const filled = new Set(substratePositions.slice(0, picks.length));
  const nextPos = substratePositions[picks.length];
  const { minCol, maxCol, minRow, maxRow } = substrateBounds;

  const headerRow = document.createElement("div");
  headerRow.className = "wafer-row";
  const corner = document.createElement("div");
  corner.className = "substrate-axis-cell substrate-axis-corner";
  headerRow.appendChild(corner);
  for (let col = minCol; col <= maxCol; col++) {
    const label = document.createElement("div");
    label.className = "substrate-axis-cell";
    label.textContent = col;
    headerRow.appendChild(label);
  }
  container.appendChild(headerRow);

  for (let row = minRow; row <= maxRow; row++) {
    const rowEl = document.createElement("div");
    rowEl.className = "wafer-row";
    const rowLabel = document.createElement("div");
    rowLabel.className = "substrate-axis-cell";
    rowLabel.textContent = row;
    rowEl.appendChild(rowLabel);
    for (let col = minCol; col <= maxCol; col++) {
      const pos = `${col}:${row}`;
      const cell = document.createElement("div");
      cell.className = "substrate-cell";
      if (filled.has(pos)) cell.classList.add("filled");
      if (pos === nextPos) cell.classList.add("next");
      if (pos === focusedSubstratePos) cell.classList.add("focus");
      cell.dataset.pos = pos;
      cell.title = pos;
      rowEl.appendChild(cell);
    }
    container.appendChild(rowEl);
  }
}

function reverseLookupSubstratePos(pos) {
  const status = document.getElementById("lookup-status");
  focusedSubstratePos = pos;
  const index = substratePositions.indexOf(pos);
  const isFilled = index >= 0 && index < picks.length;
  if (isFilled) {
    const pick = picks[index];
    focusedWaferXY = { x: pick.x, y: pick.y };
    status.textContent = `基板位置 ${pos} ↔ Wafer座標 ${pick.x}:${pick.y}（第 ${index + 1} 顆）`;
    status.className = "notice";
  } else {
    focusedWaferXY = null;
    status.textContent = `基板位置 ${pos} 尚未對應到任何wafer座標（還沒點選到這一格）`;
    status.className = "notice";
  }
  renderAll();
  const waferCellEl = document.querySelector(".wafer-cell.focus");
  if (waferCellEl) waferCellEl.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
}

function parseWaferInput(text) {
  waferCells = new Map();
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const line of text.split("\n")) {
    const parts = line.trim().split(",");
    if (parts.length !== 3) continue;
    const [x, y, bin] = parts.map((p, i) => (i < 2 ? parseInt(p, 10) : p.trim()));
    if (Number.isNaN(x) || Number.isNaN(y)) continue;
    waferCells.set(`${x},${y}`, bin);
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  waferBounds = waferCells.size ? { minX, maxX, minY, maxY } : null;
}

function loadWaferCellsFromCells(cells) {
  waferCells = new Map();
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const c of cells) {
    waferCells.set(`${c.x},${c.y}`, c.bin);
    minX = Math.min(minX, c.x); maxX = Math.max(maxX, c.x);
    minY = Math.min(minY, c.y); maxY = Math.max(maxY, c.y);
  }
  waferBounds = waferCells.size ? { minX, maxX, minY, maxY } : null;
}

async function loadFrm() {
  const status = document.getElementById("frm-status");
  status.className = "";
  status.textContent = "讀取中...";
  const payload = {
    lot_no: document.getElementById("frm_lot_no").value,
    barcode_id: document.getElementById("frm_barcode_id").value,
    frm_path: document.getElementById("frm_path").value,
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
  loadWaferCellsFromCells(data.cells);
  status.className = "ok";
  status.textContent = `已載入 LotNo=${data.lot_no} WaferID=${data.wafer_id} Layout=${data.wafer_type}（${data.columns}x${data.rows}，共${data.cells.length}顆有資料）`;
  renderAll();
}

function cellClass(bin) {
  if (bin === "1") return "bin-1";
  if (bin === undefined) return "";
  return "bin-other";
}

function isPicked(x, y) {
  return picks.some((p) => p.x === x && p.y === y);
}

function renderWaferGrid() {
  const container = document.getElementById("wafer-grid");
  container.innerHTML = "";
  if (!waferBounds) return;
  const { minX, maxX, minY, maxY } = waferBounds;
  for (let y = minY; y <= maxY; y++) {
    const row = document.createElement("div");
    row.className = "wafer-row";
    for (let x = minX; x <= maxX; x++) {
      const bin = waferCells.get(`${x},${y}`);
      const cell = document.createElement("div");
      cell.className = "wafer-cell " + cellClass(bin);
      if (isPicked(x, y)) cell.classList.add("picked");
      if (focusedWaferXY && focusedWaferXY.x === x && focusedWaferXY.y === y) cell.classList.add("focus");
      cell.dataset.x = x;
      cell.dataset.y = y;
      cell.dataset.bin = bin === undefined ? "" : bin;
      row.appendChild(cell);
    }
    container.appendChild(row);
  }
  renderWaferOverlay();
}

function renderWaferOverlay() {
  const svg = document.getElementById("wafer-overlay");
  const grid = document.getElementById("wafer-grid");
  if (!waferBounds) {
    svg.setAttribute("width", 0);
    svg.setAttribute("height", 0);
    svg.innerHTML = "";
    return;
  }
  const w = grid.offsetWidth;
  const h = grid.offsetHeight;
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

function addPick(x, y, bin) {
  if (bin !== "1") return false;
  if (isPicked(x, y)) return false;
  picks.push({ x, y, bin });
  return true;
}

function scanRectangle(x1, x2, y1, y2) {
  const xLo = Math.min(x1, x2), xHi = Math.max(x1, x2);
  const yLo = Math.min(y1, y2), yHi = Math.max(y1, y2);
  for (let x = xLo; x <= xHi; x++) {
    for (let y = yLo; y <= yHi; y++) {
      addPick(x, y, waferCells.get(`${x},${y}`));
    }
  }
}

function renderPickTable() {
  const tbody = document.querySelector("#pick-table tbody");
  tbody.innerHTML = "";
  picks.forEach((p, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${i + 1}</td><td>${p.x}</td><td>${p.y}</td><td>${p.bin}</td>
      <td><button data-idx="${i}" class="remove-btn">x</button></td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll(".remove-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      picks.splice(parseInt(btn.dataset.idx, 10), 1);
      renderAll();
    });
  });
}

function renderQtyStatus() {
  const el = document.getElementById("qty-status");
  const target = targetQty === null ? "?" : targetQty;

  if (twoLayerEnabled) {
    const primaryDone = targetQty !== null && picksPrimary.length === targetQty;
    const otherDone = targetQty !== null && picksOther.length === targetQty;
    el.textContent = `主層已選擇 ${picksPrimary.length} / 目標 ${target}　次層已選擇 ${picksOther.length} / 目標 ${target}`;
    el.className = primaryDone && otherDone ? "ok" : "bad";
    if (targetQty === null) return;
    if (primaryDone && otherDone) {
      setStepFlow(4, { done: [1, 2, 3] });
    } else if (picksPrimary.length > 0 || picksOther.length > 0 || waferBounds) {
      setStepFlow(3, { done: [1, 2] });
    }
    return;
  }

  el.textContent = `已選擇 ${picks.length} / 目標 ${target}`;
  const matched = targetQty !== null && picks.length === targetQty;
  el.className = matched ? "ok" : "bad";
  if (targetQty === null) return;
  if (matched) {
    setStepFlow(4, { done: [1, 2, 3] });
  } else if (picks.length > 0 || waferBounds) {
    setStepFlow(3, { done: [1, 2] });
  }
}

function renderLayerStatus() {
  if (!twoLayerEnabled) return;
  const status = document.getElementById("layer-status");
  const target = targetQty === null ? "?" : targetQty;
  const layerName = currentLayerKey === "primary" ? "主層" : "次層";
  status.textContent = `目前編輯：${layerName}（主層 ${picksPrimary.length}/${target}，次層 ${picksOther.length}/${target}）`;
}

function renderAll() {
  renderWaferGrid();
  renderSubstrateGrid();
  renderPickTable();
  renderQtyStatus();
  renderLayerStatus();
}

function wireWaferGridEvents() {
  const container = document.getElementById("wafer-grid");
  container.addEventListener("mousedown", (e) => {
    if (!e.target.classList.contains("wafer-cell")) return;
    dragStart = { x: parseInt(e.target.dataset.x, 10), y: parseInt(e.target.dataset.y, 10) };
  });
  container.addEventListener("mouseup", (e) => {
    if (!e.target.classList.contains("wafer-cell") || !dragStart) return;
    const end = { x: parseInt(e.target.dataset.x, 10), y: parseInt(e.target.dataset.y, 10) };
    if (end.x === dragStart.x && end.y === dragStart.y) {
      addPick(end.x, end.y, e.target.dataset.bin);
    } else {
      scanRectangle(dragStart.x, end.x, dragStart.y, end.y);
    }
    dragStart = null;
    renderAll();
  });
}

function wireSubstrateGridEvents() {
  document.getElementById("substrate-grid").addEventListener("click", (e) => {
    if (!e.target.classList.contains("substrate-cell")) return;
    reverseLookupSubstratePos(e.target.dataset.pos);
  });
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
document.getElementById("btn-load-frm").addEventListener("click", loadFrm);
document.getElementById("btn-load-wafer").addEventListener("click", () => {
  parseWaferInput(document.getElementById("wafer-input").value);
  renderAll();
});
document.getElementById("btn-clear").addEventListener("click", () => {
  picksPrimary.length = 0;
  picksOther.length = 0;
  focusedSubstratePos = null;
  focusedWaferXY = null;
  document.getElementById("lookup-status").textContent = "";
  renderAll();
});
document.getElementById("btn-generate").addEventListener("click", generateStrate);
document.getElementById("two_layer_enabled").addEventListener("change", (e) => {
  twoLayerEnabled = e.target.checked;
  document.getElementById("two-layer-fields").style.display = twoLayerEnabled ? "" : "none";
  document.getElementById("layer-switch").style.display = twoLayerEnabled ? "" : "none";
  setActiveLayer("primary");
});
document.getElementById("primary_layer").addEventListener("input", (e) => {
  document.getElementById("layer-primary-label").textContent = e.target.value;
});
document.getElementById("other_layer").addEventListener("input", (e) => {
  document.getElementById("layer-other-label").textContent = e.target.value;
});
document.getElementById("btn-layer-primary").addEventListener("click", () => setActiveLayer("primary"));
document.getElementById("btn-layer-other").addEventListener("click", () => setActiveLayer("other"));
wireWaferGridEvents();
wireSubstrateGridEvents();
renderQtyStatus();
