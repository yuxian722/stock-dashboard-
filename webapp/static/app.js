// ---- State ----------------------------------------------------------------
// Two independent axes, on purpose (2026/08/18 redesign — see
// bingomap/CLAUDE.md): how many STACKED LAYERS (numLayers, f9=1..N) vs how
// many PHYSICAL WAFERS (1 shared, or 2 in "跨兩片wafer" mode) are in play.
// They used to be wired 1:1 (wafer panel i fed layer i only) — wrong: the
// user stacks N layers from the SAME wafer, and "跨兩片wafer" means both
// wafers should be able to feed ANY layer, not one wafer per layer.
//
// New interaction: clicking/dragging on a wafer grid STAGES coordinates
// (pending, not yet in any layer) rather than committing them directly.
// Clicking into a layer's BINGO MAP (when something is staged) COMMITS the
// whole staged queue into that layer, in order. This is what actually
// fixes the original "容易點錯層" complaint — the destination is chosen at
// the moment of commit (by clicking the layer you can see filling up),
// not via a separate switch button that's easy to leave on the wrong
// layer. Single click stages one coordinate; drag-select stages a batch —
// both routes converge on the same staging queue.
let targetQty = null;
let multiLayerEnabled = false;
let numLayers = 2; // only meaningful when multiLayerEnabled
let multiWaferEnabled = false; // true = a second, independent physical wafer panel exists
let picksByLayer = [[]]; // picksByLayer[i] = {x, y, bin, panel}[] — panel = which wafer panel it was staged from (0 or 1), for dedup/rendering only; stripped before /api/generate
let stagedPicks = []; // {x, y, bin, panel}[] — selected on a wafer grid, not yet written into any layer
let waferCellsByPanel = [new Map(), new Map()]; // waferCellsByPanel[i]: "x,y" -> bin (index 1 only used when multiWaferEnabled)
let waferBoundsByPanel = [null, null];
// T點 (Reference Point) — a fixed anchor mark WaferCoordinate.exe draws on
// the wafer image with a special texture. 2026/08/18, three guesses before
// landing here:
//   1. reference_point_x/y taken as a direct grid coordinate — wrong, a
//      photo showed that cell sitting well outside the wafer's actual die
//      area, nowhere near the real on-screen crosshair.
//   2. plain grid center (columns//2, rows//2) — wrong for a different
//      wafer/photo: the user pointed at the real T點 cell (hovering our
//      own grid) and read off "Wafer座標：18:0", nowhere near the center.
//   3. (current) the user explained the real tool's crosshair is a
//      180°-mirrored view of our DB-oriented rendering, and described the
//      correct cell in OUR coordinates directly: "上方中心線往右第五顆，
//      第一排" (top row, 5 cells right of the horizontal center line).
//      That "5" is exactly this file's own reference_point_x (5) — so
//      T點 = (columns//2 - reference_point_x, 0): an offset from the
//      wafer's horizontal center, along its own row 0 (the flat/notch
//      edge in this rendering), by reference_point_x cells. Verified
//      against the real file: gives exactly (18, 0) as reported.
// reference_point_y is NOT used — row 0 is fixed, not derived from it;
// unconfirmed whether that holds for a wafer whose notch/flat sits on a
// different edge. Only known when loaded via FRM (manually-pasted
// "x,y,bin" text has no columns/reference_point header to compute this
// from, so this stays null then).
let refPointByPanel = [null, null]; // {x, y} | null
let substratePositions = []; // ["col:row", ...] in blank_generator's own machine-type order — shared by every layer
let substrateBounds = null; // {minCol, maxCol, minRow, maxRow}
let focusedSubstratePosByLayer = [null]; // "col:row" clicked in that layer's BINGO MAP, for reverse lookup
let focusedWaferXYByLayer = [null]; // {x, y, panel} that focused position maps to, if filled
let usingTemplate = false; // true once a template .strate has been loaded via loadTemplate()
let skippedPositions = new Set(); // "col:row" substrate positions marked "不上片" — excluded from the fill order
let skipModeEnabled = false; // true = clicking a substrate cell toggles skip instead of commit/reverse-lookup

// Reference substrates: other, already-completed .strate files loaded
// purely as a read-only overlay on the (shared, panel 0) wafer map — "同一
// 片wafer的其他基板". Each entry's `positions` set already occupies wafer
// coordinates; per the user's confirmed answers, those coordinates must be
// blocked from being staged again ("要，直接降選取"), and each file must
// stay visually distinguishable on the grid ("分辨是哪一枚") rather than
// collapsing into one generic "occupied" marker — hence the per-file
// letter + color instead of reusing the layer-number digit badge.
const REFERENCE_COLORS = ["#e04b4b", "#0ea5a5", "#a855f7", "#ca8a04", "#059669", "#e0459e", "#0891b2", "#65a30d"];
let referenceSubstrates = []; // { label, color, positions: Set("x,y") }[]

function referenceLetter(i) {
  return i < 26 ? String.fromCharCode(65 + i) : `R${i + 1}`;
}

function isReferencedAt(panelIndex, x, y) {
  // Reference files carry no notion of "which physical wafer panel" any
  // more than a loaded template does (see loadTemplate()) — they describe
  // coordinates on THE physical wafer being referenced, which is always
  // panel 0 (the shared/first wafer that "跨兩片wafer" branches off of).
  if (panelIndex !== 0) return null;
  const key = `${x},${y}`;
  for (const ref of referenceSubstrates) {
    if (ref.positions.has(key)) return ref;
  }
  return null;
}

function effectiveNumLayers() {
  return multiLayerEnabled ? numLayers : 1;
}

function numWaferPanels() {
  return multiWaferEnabled ? 2 : 1;
}

// ---- DOM id helpers ---------------------------------------------------
// Wafer panels are indexed by PHYSICAL WAFER (0 or 1), independent of
// layer index — see the state comment above.
function waferIds(i) {
  const s = i === 0 ? "" : `_W${i}`;
  return {
    panel: `wafer-panel${s}`,
    frmLotNo: `frm_lot_no${s}`,
    frmBarcodeId: `frm_barcode_id${s}`,
    frmPath: `frm_path${s}`,
    btnLoadFrm: `btn-load-frm${s}`,
    frmStatus: `frm-status${s}`,
    waferInput: `wafer-input${s}`,
    btnLoadWafer: `btn-load-wafer${s}`,
    binLegend: `wafer-bin-legend${s}`,
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

// ---- Dynamic HTML: wafer panel 1 (only ever a second panel — "跨兩片
// wafer" is always exactly 2 physical wafers, decoupled from layer count) ---
function buildExtraWaferPanelHtml() {
  const ids = waferIds(1);
  return `
    <section class="panel" id="${ids.panel}" style="grid-column:1/-1">
      <h2><span class="step-badge">2</span>Wafer Bin 資料 — 第二片wafer</h2>
      <div class="notice">跨兩片wafer時，這裡讀取/貼上第二片wafer自己的wafer bin資料。兩片wafer選出來的座標都是先「待寫入」，
        點哪一層的BINGO MAP就寫入哪一層，跟這是第幾片wafer沒有關係。</div>
      <div class="grid2">
        <label>FRM Lot No <input id="${ids.frmLotNo}" value=""></label>
        <label>Barcode ID <input id="${ids.frmBarcodeId}" value=""></label>
      </div>
      <label style="margin-bottom:0.6rem">FRM根路徑 <input id="${ids.frmPath}" value="F:\\SMAP\\FRM\\"></label>
      <button id="${ids.btnLoadFrm}">自動讀取FRM檔案</button>
      <p id="${ids.frmStatus}" class="lyr-frm-status"></p>
      <div class="notice" style="margin-top:1rem">或手動貼上第二片wafer bin資料（每行 <code>x,y,bin</code>）</div>
      <textarea id="${ids.waferInput}" rows="6" placeholder="23,195,1&#10;23,196,1&#10;23,197,7"></textarea>
      <button class="secondary" id="${ids.btnLoadWafer}">載入第二片Wafer地圖(文字)</button>
      <div class="legend">
        <span id="${ids.binLegend}" style="display:contents"></span>
        <span><i style="background:#fff;border-color:#1a3fd6"></i>已寫入某一層</span>
        <span><i style="background:#fff;border-color:#f5900f;border-style:dashed"></i>已選取、待寫入</span>
        <span><i style="background:repeating-linear-gradient(45deg,#1e293b 0,#1e293b 2px,transparent 2px,transparent 5px);border-color:#1e293b"></i>T點（不能選取）</span>
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

// ---- UI rebuild on layer/wafer-config change --------------------------
function resetLayerState() {
  const n = effectiveNumLayers();
  picksByLayer = Array.from({ length: n }, () => []);
  stagedPicks = [];
  waferCellsByPanel = [waferCellsByPanel[0] || new Map(), new Map()];
  waferBoundsByPanel = [waferBoundsByPanel[0] || null, null];
  refPointByPanel = [refPointByPanel[0] || null, null];
  focusedSubstratePosByLayer = Array.from({ length: n }, () => null);
  focusedWaferXYByLayer = Array.from({ length: n }, () => null);
  document.getElementById("lookup-status").textContent = "";
}

function rebuildLayerUi() {
  const n = effectiveNumLayers();

  // --- wafer panels: 1, or exactly 2 in "跨兩片wafer" mode — independent of n ---
  const extraWaferContainer = document.getElementById("wafer-panels-extra");
  extraWaferContainer.innerHTML = "";
  if (multiWaferEnabled) {
    extraWaferContainer.insertAdjacentHTML("beforeend", buildExtraWaferPanelHtml());
    wireWaferPanelEvents(1);
  }

  // --- BINGO MAP blocks (layer 0 is the static block; 1..n-1 dynamic) ---
  const bingoWrap = document.getElementById("bingo-maps-wrap");
  bingoWrap.querySelectorAll(".bingo-map-block:not(#bingo-map-block-primary)").forEach((el) => el.remove());
  for (let i = 1; i < n; i++) {
    bingoWrap.insertAdjacentHTML("beforeend", buildExtraBingoMapBlockHtml(i));
    wireBingoBlockEvents(i);
  }

  document.getElementById("bingo-map-title-primary").textContent = n > 1 ? "第1層 BINGO MAP" : "BINGO MAP";
  document.getElementById("wafer-panel-title-suffix").textContent = multiWaferEnabled ? " — 第一片wafer" : "";
  document.getElementById("wafer-legend-picked").style.display = n > 1 || multiWaferEnabled ? "" : "none";
  document.getElementById("wafer-legend-staged").style.display = "";
  document.getElementById("stage-controls").style.display = "";
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
  // "跨兩片wafer" (multiWaferEnabled) is deliberately left untouched here —
  // a .strate file carries no notion of "which physical wafer panel" a die
  // came from, so there's nothing in the template to derive it from either
  // way, but that's not a reason to silently override whatever the user
  // currently has set. This used to force it to false unconditionally,
  // which meant checking "跨兩片wafer" and then loading a template made
  // the second wafer panel vanish with no explanation — exactly the
  // "找不到第二片wafer" bug report.
  resetLayerState();
  // A template file carries no notion of "which physical wafer panel" —
  // treat every loaded pick as panel 0 (the default single-wafer source).
  picksByLayer = data.layer_picks.length
    ? data.layer_picks.map((picks) => picks.map((p) => ({ ...p, panel: 0 })))
    : [[]];
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

// ---- Reference substrates (read-only overlay, see state comment above) --
function allPicksFromParsedFile(data) {
  // data.layer_picks is already [layer0picks, layer1picks, ..., currentLayerPicks]
  // (see webapp/app.py:_split_into_layer_picks) — flattening it gives every
  // wafer coordinate the file occupies, across every stacked layer it has.
  const positions = new Set();
  for (const layerPicks of data.layer_picks) {
    for (const p of layerPicks) positions.add(`${p.x},${p.y}`);
  }
  return positions;
}

async function loadReferenceFiles(files) {
  const status = document.getElementById("reference-status");
  status.className = "";
  status.textContent = "讀取中...";
  const loaded = [];
  const errors = [];
  for (const file of files) {
    const text = await file.text();
    try {
      const res = await fetch("/api/parse_strate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await res.json();
      if (!res.ok) {
        errors.push(`${file.name}：${data.error}`);
        continue;
      }
      loaded.push({ name: data.substrate_id || file.name, positions: allPicksFromParsedFile(data) });
    } catch (err) {
      errors.push(`${file.name}：讀取失敗`);
    }
  }
  referenceSubstrates = referenceSubstrates.concat(
    loaded.map((entry, i) => {
      const idx = referenceSubstrates.length + i;
      return { label: referenceLetter(idx), name: entry.name, color: REFERENCE_COLORS[idx % REFERENCE_COLORS.length], positions: entry.positions };
    })
  );
  renderReferenceLegend();
  status.className = errors.length ? "error" : loaded.length ? "ok" : "";
  const parts = [];
  if (loaded.length) parts.push(`已載入 ${loaded.length} 枚參考基板（共${referenceSubstrates.length}枚），佔用座標已不能再選取`);
  if (errors.length) parts.push(`失敗：${errors.join("；")}`);
  status.textContent = parts.join("　") || "沒有選擇任何檔案";
  document.getElementById("btn-clear-references").style.display = referenceSubstrates.length ? "" : "none";
  renderAll();
}

function renderReferenceLegend() {
  const el = document.getElementById("reference-legend");
  el.innerHTML = referenceSubstrates
    .map((ref) => `<span><i style="background:${ref.color};border-color:${ref.color}"></i>${ref.label} = ${ref.name}（${ref.positions.size}顆）</span>`)
    .join("");
}

function clearReferenceSubstrates() {
  referenceSubstrates = [];
  renderReferenceLegend();
  document.getElementById("btn-clear-references").style.display = "none";
  document.getElementById("reference-status").textContent = "已清除所有參考基板";
  document.getElementById("reference-status").className = "";
  document.getElementById("reference-files").value = "";
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

function fillablePositions() {
  // Positions marked "不上片" are excluded from the fill order entirely —
  // matches assign_dies()'s own "unfilled positions are simply absent"
  // rule (see bingomap/CLAUDE.md), just with a smaller starting list.
  return substratePositions.filter((pos) => !skippedPositions.has(pos));
}

// Bulk shortcut for "this run won't fill the whole tray" — keep the first
// N positions (in the blank skeleton's own fill order) fillable, and mark
// everything after that "不上片" in one action instead of manually
// clicking/dragging each trailing cell. This recomputes skippedPositions
// from scratch each time it's applied (any individually-marked skips from
// before are replaced), matching the notice text shown next to the button.
function applyEffectiveQty(n) {
  if (!Number.isFinite(n) || n < 0 || !substratePositions.length) return null;
  skippedPositions = new Set(substratePositions.slice(n));
  return { kept: substratePositions.length - skippedPositions.size, skipped: skippedPositions.size };
}

// ---- BINGO MAP (substrate grid) rendering ---------------------------------
function renderSubstrateGridInto(containerId, layerPicks, focusedPos) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";
  if (!substrateBounds) return;
  // First N picks (in commit order) fill the first N *fillable* positions
  // of the blank skeleton's own order (skipping any marked "不上片") —
  // this mirrors exactly what assign_dies()/assign_layers() does at
  // generate time, so this preview is never out of sync with the real
  // output.
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
  if (isFilled) {
    const pick = layerPicks[index];
    focusedWaferXYByLayer[layerIndex] = { x: pick.x, y: pick.y, panel: pick.panel };
    status.textContent = `${layerLabel}基板位置 ${pos} ↔ Wafer座標 ${pick.x}:${pick.y}${multiWaferEnabled ? `（第${pick.panel + 1}片wafer）` : ""}（第 ${index + 1} 顆）`;
    status.className = "notice";
  } else {
    focusedWaferXYByLayer[layerIndex] = null;
    status.textContent = `${layerLabel}基板位置 ${pos} 尚未對應到任何wafer座標（還沒點選到這一格）`;
    status.className = "notice";
  }
  renderAll();
  const targetGridId = isFilled ? waferIds(layerPicks[index].panel).grid : waferIds(0).grid;
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
  waferCellsByPanel[panelIndex] = cells;
  waferBoundsByPanel[panelIndex] = bounds;
  refPointByPanel[panelIndex] =
    data.columns && data.reference_point_x !== undefined
      ? { x: Math.floor(data.columns / 2) - data.reference_point_x, y: 0 }
      : null;
  status.className = "ok";
  const refNote = refPointByPanel[panelIndex]
    ? `，T點＝${refPointByPanel[panelIndex].x}:${refPointByPanel[panelIndex].y}（wafer圖上會用斜紋標示，是wafer水平中心線往右偏reference_point_x格、第一排的位置，麻煩比對一下跟WaferCoordinate.exe看到的是不是同一格）`
    : "";
  status.textContent = `已載入 LotNo=${data.lot_no} WaferID=${data.wafer_id} Layout=${data.wafer_type}（${data.columns}x${data.rows}，共${data.cells.length}顆有資料）${refNote}`;
  renderAll();
}

// Bin color palette — 2026/08/19 ask: "應該依據下載下來有什麼bin code就出現
// 不能只有Bin 1 Bin 7". Real wafer bin codes are always a single ASCII
// digit (bingomap/frm_reader.py's _decode_bin_kind does `int(chr(value))`,
// which only ever succeeds for one decimal digit) — a fixed 10-entry
// palette covers every real value; anything unexpected falls back to one
// shared gray rather than crashing or silently reusing another bin's color.
const BIN_COLORS = {
  "0": "#94a3b8", "1": "#4fb84a", "2": "#f59e0b", "3": "#ef4444",
  "4": "#8b5cf6", "5": "#3b82f6", "6": "#14b8a6", "7": "#d867d8",
  "8": "#92400e", "9": "#ca8a04",
};
const BIN_COLOR_FALLBACK = "#64748b";

function binColor(bin) {
  return BIN_COLORS[bin] !== undefined ? BIN_COLORS[bin] : BIN_COLOR_FALLBACK;
}

function applyBinColor(cell, bin) {
  if (bin === undefined) return;
  cell.classList.add("bin-cell");
  cell.style.setProperty("--bin-color", binColor(bin));
}

// Only lists bin codes actually present in `cells` (a Map of "x,y" -> bin)
// instead of a hardcoded Bin1/Bin7-only legend, since a real wafer can
// carry other bin codes too. `containerId` is expected to be a
// `display:contents` span so its children lay out as direct flex items of
// the surrounding `.legend` div (see index.html/app.js's
// buildExtraWaferPanelHtml).
function renderBinLegend(containerId, cells) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const bins = new Set(cells.values());
  const sorted = [...bins].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  el.innerHTML = sorted
    .map((b) => `<span><i style="background:${binColor(b)}"></i>Bin ${b}${b === "1" ? "（可選）" : "（不可選）"}</span>`)
    .join("");
}

// ---- Staging (wafer grid selections not yet written into a layer) ------
// A coordinate on a given physical wafer panel can only ever be consumed
// once, regardless of which layer it eventually lands in — this is the
// dedup rule that actually matters now that any panel can feed any layer.
function isCommittedOnPanel(panelIndex, x, y) {
  return picksByLayer.some((layerPicks) => layerPicks.some((p) => p.panel === panelIndex && p.x === x && p.y === y));
}

function isStagedOnPanel(panelIndex, x, y) {
  return stagedPicks.some((p) => p.panel === panelIndex && p.x === x && p.y === y);
}

function stageIndexOnPanel(panelIndex, x, y) {
  return stagedPicks.findIndex((p) => p.panel === panelIndex && p.x === x && p.y === y);
}

// Toggling: clicking an already-staged cell un-stages it (lets you correct
// a mis-click before committing); clicking a fresh bin-1, unused cell
// stages it.
function toggleStagePick(panelIndex, x, y, bin) {
  const existingIdx = stageIndexOnPanel(panelIndex, x, y);
  if (existingIdx >= 0) {
    stagedPicks.splice(existingIdx, 1);
    return true;
  }
  if (bin !== "1") return false;
  if (isCommittedOnPanel(panelIndex, x, y)) return false;
  if (isReferencedAt(panelIndex, x, y)) return false;
  stagedPicks.push({ x, y, bin, panel: panelIndex });
  return true;
}

function stagePickIfNew(panelIndex, x, y, bin) {
  if (bin !== "1") return false;
  if (isCommittedOnPanel(panelIndex, x, y) || isStagedOnPanel(panelIndex, x, y)) return false;
  if (isReferencedAt(panelIndex, x, y)) return false;
  stagedPicks.push({ x, y, bin, panel: panelIndex });
  return true;
}

function commitStagedPicksToLayer(layerIndex) {
  if (!stagedPicks.length) return 0;
  picksByLayer[layerIndex].push(...stagedPicks);
  const count = stagedPicks.length;
  stagedPicks = [];
  return count;
}

const GRID_AXIS_SIZE = 20; // must match .grid-axis-cell's width/height in style.css

function renderWaferPanel(panelIndex) {
  const ids = waferIds(panelIndex);
  const container = document.getElementById(ids.grid);
  if (!container) return;
  container.innerHTML = "";
  const cells = waferCellsByPanel[panelIndex];
  const bounds = waferBoundsByPanel[panelIndex];
  renderBinLegend(ids.binLegend, cells);
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
      cell.className = "wafer-cell";
      applyBinColor(cell, bin);
      let committedLayer = null;
      for (let li = 0; li < picksByLayer.length; li++) {
        if (picksByLayer[li].some((p) => p.panel === panelIndex && p.x === x && p.y === y)) {
          committedLayer = li;
          break;
        }
      }
      const ref = committedLayer === null ? isReferencedAt(panelIndex, x, y) : null;
      if (committedLayer !== null) {
        cell.classList.add("picked");
        cell.textContent = String(committedLayer + 1);
      } else if (isStagedOnPanel(panelIndex, x, y)) {
        cell.classList.add("staged");
      } else if (ref) {
        cell.classList.add("referenced");
        cell.style.setProperty("--ref-color", ref.color);
        cell.textContent = ref.label;
        cell.title = `${x}:${y} — 已被參考基板「${ref.name}」占用`;
      }
      const isFocused = focusedWaferXYByLayer.some((f) => f && f.panel === panelIndex && f.x === x && f.y === y);
      if (isFocused) cell.classList.add("focus");
      const refPoint = refPointByPanel[panelIndex];
      const isRefPoint = refPoint && refPoint.x === x && refPoint.y === y;
      if (isRefPoint) {
        cell.classList.add("ref-point");
        cell.dataset.refPoint = "1";
        if (!cell.textContent) cell.textContent = "T";
        cell.title = `${x}:${y} — T點`;
      }
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
  for (let i = 0; i < numWaferPanels(); i++) renderWaferPanel(i);
}

function scanRectangle(x1, x2, y1, y2, panelIndex) {
  const xLo = Math.min(x1, x2), xHi = Math.max(x1, x2);
  const yLo = Math.min(y1, y2), yHi = Math.max(y1, y2);
  const cells = waferCellsByPanel[panelIndex];
  for (let x = xLo; x <= xHi; x++) {
    for (let y = yLo; y <= yHi; y++) {
      stagePickIfNew(panelIndex, x, y, cells.get(`${x},${y}`));
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
  // layer's picks, so every layer stays visible and manageable at once.
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
    } else if (picksByLayer.slice(0, n).some((p) => p.length > 0) || waferBoundsByPanel[0]) {
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
  } else if (picks.length > 0 || waferBoundsByPanel[0]) {
    setStepFlow(3, { done: [1, 2] });
  }
}

function renderLayerStatus() {
  const status = document.getElementById("layer-status");
  const clearBtn = document.getElementById("btn-clear-staged");
  if (stagedPicks.length) {
    status.textContent = `已選取 ${stagedPicks.length} 顆wafer座標，尚未寫入：點下方任一層的BINGO MAP即可整批寫入該層。`;
    status.className = "notice";
    clearBtn.textContent = `清除待寫入的座標 (${stagedPicks.length})`;
  } else {
    status.textContent = "";
    status.className = "";
    clearBtn.textContent = "清除待寫入的座標";
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
      toggleStagePick(panelIndex, end.x, end.y, e.target.dataset.bin);
    } else {
      scanRectangle(localDragStart.x, end.x, localDragStart.y, end.y, panelIndex);
    }
    localDragStart = null;
    renderAll();
  });
  container.addEventListener("mouseover", (e) => {
    if (!e.target.classList.contains("wafer-cell")) return;
    const x = e.target.dataset.x, y = e.target.dataset.y;
    const ref = isReferencedAt(panelIndex, parseInt(x, 10), parseInt(y, 10));
    const refPointNote = e.target.dataset.refPoint ? "（T點）" : "";
    const label = ref && !e.target.classList.contains("picked") && !e.target.classList.contains("staged")
      ? `${x}:${y}（已被參考基板「${ref.name}」占用，不能選）${refPointNote}`
      : `Wafer座標：${x}:${y}${refPointNote}`;
    hoverStatus.textContent = label;
    showGridTooltip(tooltip, e.target, label);
  });
  container.addEventListener("mouseleave", () => {
    hoverStatus.textContent = "滑鼠移到格子上會顯示座標";
    hideGridTooltip(tooltip);
  });
}

function skipRectangleBetween(pos1, pos2) {
  // Drag-select for "不上片": mark every valid substrate position in the
  // rectangle, skipping cells that fall outside the actual substrate
  // shape (the bounding-box grid renders a plain cell for those, not a
  // real fillable position) — those must never end up counted in
  // skippedPositions.size, or effectiveTargetQty() would undercount.
  const [c1, r1] = pos1.split(":").map(Number);
  const [c2, r2] = pos2.split(":").map(Number);
  const colLo = Math.min(c1, c2), colHi = Math.max(c1, c2);
  const rowLo = Math.min(r1, r2), rowHi = Math.max(r1, r2);
  const validPositions = new Set(substratePositions);
  for (let col = colLo; col <= colHi; col++) {
    for (let row = rowLo; row <= rowHi; row++) {
      const pos = `${col}:${row}`;
      if (validPositions.has(pos)) skippedPositions.add(pos);
    }
  }
}

function handleSubstrateCellClick(pos, layerIndex) {
  if (skipModeEnabled) {
    if (skippedPositions.has(pos)) skippedPositions.delete(pos);
    else skippedPositions.add(pos);
    renderAll();
    return;
  }
  if (stagedPicks.length) {
    commitStagedPicksToLayer(layerIndex);
    renderAll();
    return;
  }
  reverseLookupSubstratePos(pos, layerIndex);
}

function wireSubstrateGridClicks(containerId, hoverStatusId, tooltipId, layerIndex) {
  const container = document.getElementById(containerId);
  const hoverStatus = document.getElementById(hoverStatusId);
  const tooltip = document.getElementById(tooltipId);
  let localDragStart = null;
  container.addEventListener("mousedown", (e) => {
    if (!e.target.classList.contains("substrate-cell")) return;
    localDragStart = e.target.dataset.pos;
  });
  container.addEventListener("mouseup", (e) => {
    if (!e.target.classList.contains("substrate-cell") || !localDragStart) return;
    const endPos = e.target.dataset.pos;
    if (endPos === localDragStart) {
      handleSubstrateCellClick(endPos, layerIndex);
    } else if (skipModeEnabled) {
      // Only skip-mode has a defined bulk action for a drag; outside skip
      // mode a drag across the BINGO MAP does nothing (commit/reverse-
      // lookup are single-target actions).
      skipRectangleBetween(localDragStart, endPos);
      renderAll();
    }
    localDragStart = null;
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
    waferCellsByPanel[panelIndex] = cells;
    waferBoundsByPanel[panelIndex] = bounds;
    // Manually-pasted "x,y,bin" text carries no FRM columns/rows header to
    // compute a T點/center from — clear any stale marker from a previous
    // FRM load.
    refPointByPanel[panelIndex] = null;
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
    : "如果上方wafer圖有選取「待寫入」的座標，點這裡任一格＝把那些座標整批寫入這一層。沒有待寫入座標時，點任一格可以反查它對應到哪個wafer座標（會在上方wafer圖上用橘框標示出來）。";
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
  // `panel` is frontend-only bookkeeping (which physical wafer a pick came
  // from, for dedup/rendering) — the backend only wants {x, y, bin}.
  const stripPanel = (picks) => picks.map(({ x, y, bin }) => ({ x, y, bin }));
  if (multiLayerEnabled) {
    payload.layers = picksByLayer.slice(0, numLayers).map(stripPanel);
  } else {
    payload.selections = stripPanel(picksByLayer[0]);
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
document.getElementById("reference-files").addEventListener("change", (e) => {
  const files = Array.from(e.target.files || []);
  if (!files.length) return;
  loadReferenceFiles(files);
});
document.getElementById("btn-clear-references").addEventListener("click", clearReferenceSubstrates);
document.getElementById("btn-clear").addEventListener("click", () => {
  resetLayerState();
  renderAll();
});
document.getElementById("btn-clear-staged").addEventListener("click", () => {
  stagedPicks = [];
  renderAll();
});
document.getElementById("btn-generate").addEventListener("click", generateStrate);

document.getElementById("multi_layer_enabled").addEventListener("change", (e) => {
  multiLayerEnabled = e.target.checked;
  document.getElementById("multi-layer-fields").style.display = multiLayerEnabled ? "" : "none";
  // "跨兩片wafer" (multiWaferEnabled) is deliberately NOT touched here —
  // it's independent of layer count (see the header notice text): even a
  // plain single-layer (第1層 only, no stacking) job can need two
  // physical wafers if one alone doesn't have enough good die.
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
document.getElementById("btn-apply-effective-qty").addEventListener("click", () => {
  const n = parseInt(document.getElementById("effective_qty_input").value, 10);
  const result = applyEffectiveQty(n);
  const status = document.getElementById("effective-qty-status");
  if (!result) {
    status.textContent = "請先產生空白骨架，並輸入一個不小於0的數量";
    return;
  }
  status.textContent =
    result.skipped > 0
      ? `已套用：前 ${result.kept} 格維持可上片，後面 ${result.skipped} 格已標記「不上片」。`
      : `已套用：設定的數量 ≥ 理論總數 ${substratePositions.length}，全部維持可上片，沒有格子被標記。`;
  renderAll();
});
setSkipMode(false);
rebuildLayerUi();
renderQtyStatus();
