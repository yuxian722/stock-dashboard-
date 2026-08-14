let targetQty = null;
let picks = []; // {x, y, bin}
let waferCells = new Map(); // "x,y" -> bin
let waferBounds = null;
let dragStart = null;

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
  } else {
    targetQty = data.total_qty;
    status.textContent = `空白骨架已產生，共 ${data.positions.length} 格，目標DIE數量 = ${targetQty}`;
  }
  renderQtyStatus();
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
  el.textContent = `已選擇 ${picks.length} / 目標 ${target}`;
  el.className = targetQty !== null && picks.length === targetQty ? "ok" : "bad";
}

function renderAll() {
  renderWaferGrid();
  renderPickTable();
  renderQtyStatus();
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
    selections: picks,
  };

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
}

document.getElementById("btn-blank").addEventListener("click", loadBlank);
document.getElementById("btn-load-wafer").addEventListener("click", () => {
  parseWaferInput(document.getElementById("wafer-input").value);
  renderAll();
});
document.getElementById("btn-clear").addEventListener("click", () => {
  picks = [];
  renderAll();
});
document.getElementById("btn-generate").addEventListener("click", generateStrate);
wireWaferGridEvents();
renderQtyStatus();
