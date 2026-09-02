// ---- wafer角度/鏡像跨①②頁同步 --------------------------------------------
// 跟app.js同一次更正，公式必須完全一致(兩邊各自維護一份)——見那邊
// SHARED_WAFER_ANGLE_KEY的完整說明。使用者反映①②兩頁各自獨立記住角度，
// 同一片wafer在兩頁角度沒對齊時分布位置看起來不一樣，容易誤會成資料錯。
const SHARED_WAFER_ANGLE_KEY = "bingomap_shared_wafer_angle";

function waferAngleStorageId(lotNo, barcodeId) {
  const l = (lotNo || "").trim(), b = (barcodeId || "").trim();
  if (!l || !b) return null;
  return `${l}|${b}`;
}

function loadSharedWaferAngle(lotNo, barcodeId) {
  const id = waferAngleStorageId(lotNo, barcodeId);
  if (!id) return null;
  try {
    const raw = localStorage.getItem(SHARED_WAFER_ANGLE_KEY);
    if (!raw) return null;
    const entry = JSON.parse(raw)[id];
    return entry && Number.isFinite(entry.angle) ? entry : null;
  } catch (err) {
    return null;
  }
}

function saveSharedWaferAngle(lotNo, barcodeId, angle, mirror) {
  const id = waferAngleStorageId(lotNo, barcodeId);
  if (!id) return;
  try {
    const raw = localStorage.getItem(SHARED_WAFER_ANGLE_KEY);
    const map = raw ? JSON.parse(raw) : {};
    map[id] = { angle, mirror };
    localStorage.setItem(SHARED_WAFER_ANGLE_KEY, JSON.stringify(map));
  } catch (err) {
    // localStorage unavailable/quota exceeded — just don't persist
  }
}

let lastCsv = null;
let lastWaferData = null; // last {columns, rows, lot_no, wafer_id, cells} passed to renderWaferGrid() — so the T點 fields can re-render live on every keystroke without re-fetching
// 2026/08/25大改版：跟app.js同一次更正，見那邊waferAngleByPanel/
// rotateWaferCells()的完整註解——拿掉X/Y軸反轉勾選框，改成單一的0/90/
// 180/270度角度選單，選了角度直接重新算出每一顆die的座標(連複製出去的
// 座標文字也是算過的這組)，畫格子的順序永遠固定(欄0在右邊、列0在最上
// 面)，這樣「0,0永遠在右上角」是結構上保證成立。這裡的預覽圖純粹是給
// 使用者「看一下這片wafer的bin圖、複製座標文字用」的參考功能，實際誤吸
// 偏移分析(/api/mispick/analyze)完全在後端用DB/ESEC既有公式計算，不會
// 讀取這裡的角度設定，所以角度調整只影響這個預覽/複製文字，不影響分析
// 結果正確性。
let mpAngle = 0; // 0 | 90 | 180 | 270
let mpMirror = false;
let mpRawWafer = null; // pristine {columns, rows, lot_no, wafer_id, cells} as loaded — angle/mirror changes re-derive from this

// 2026/09/02新增：使用者回報「BINGO MAP的紅框要在正常的wafer圖檔對應
// 哪一顆，我才可以知道那顆bingomap紅框跟wafer圖的那一顆是被誤吸」——
// 每次分析完成後，把所有substrate的action_rows(強制點除/人工確認，帶
// action_no)攤平存在這裡，raw座標(fx,fy)，renderWaferGrid()畫圖時再轉成
// 當下角度/鏡像設定下的顯示座標，疊在wafer圖上——跟BINGO MAP結果表用
// 同一個action_no當標籤，兩張圖上同一個數字就是同一顆。
let lastMispickActionMarkers = []; // {fx, fy, decision, action_no, substrateName}[]

// 2026/08/26：跟app.js同一次更正，見那邊rotateWaferCells()的完整註解——
// 角度只能旋轉，湊不出鏡像，使用者比對真正的WaferCoordinate.exe後回報
// 圖是鏡像的，加一個獨立的鏡像參數，對旋轉後的座標再做一次水平翻轉。
// 跟app.js的rotateWaferCells()是同一條公式，只是操作的是這頁用的
// {x,y,bin}[]陣列而不是Map，兩邊要保持公式一致。
function waferRawBounds(cells) {
  if (!cells || !cells.length) return null;
  const xs = cells.map((c) => c.x);
  const ys = cells.map((c) => c.y);
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}

// Single-point version of rotateWaferArray()'s formula, pulled out so the
// mis-pick marker overlay (see renderWaferGrid()'s `markers` — 2026/09/02)
// can place a marker at a raw wafer_xy (from action_rows' fx/fy, NOT the
// rotated display coords) without duplicating the rotation math a second
// time and risking the two drifting apart, the same class of bug that
// caused the T點公式 mismatch earlier in this project (see CLAUDE.md).
function rotateWaferPoint(x, y, rawBounds, angleDeg, mirror) {
  if (!rawBounds) return null;
  const { minX, maxX, minY, maxY } = rawBounds;
  const spanX = maxX - minX, spanY = maxY - minY;
  const rotatedSpanX = angleDeg === 90 || angleDeg === 270 ? spanY : spanX;
  const u = x - minX, v = y - minY;
  let nu, nv;
  if (angleDeg === 90) { nu = v; nv = spanX - u; }
  else if (angleDeg === 180) { nu = spanX - u; nv = spanY - v; }
  else if (angleDeg === 270) { nu = spanY - v; nv = u; }
  else { nu = u; nv = v; }
  if (mirror) nu = rotatedSpanX - nu;
  return { x: nu, y: nv };
}

function rotateWaferArray(wafer, angleDeg, mirror) {
  if (!wafer || !wafer.cells.length) return wafer;
  const rawBounds = waferRawBounds(wafer.cells);
  const cells = wafer.cells.map((c) => {
    const p = rotateWaferPoint(c.x, c.y, rawBounds, angleDeg, mirror);
    return { x: p.x, y: p.y, bin: c.bin };
  });
  return { ...wafer, cells, columns: angleDeg === 90 || angleDeg === 270 ? wafer.rows : wafer.columns, rows: angleDeg === 90 || angleDeg === 270 ? wafer.columns : wafer.rows };
}
// Kept so nudge buttons (which re-run analyze() without the user touching
// the file input again) and a restored session both keep working — a
// plain <input type=file> can never be re-populated by JS after a page
// reload (browser security), so the actual file CONTENTS are cached here
// instead the first time they're read, and reused whenever the input
// itself is empty. See analyze()'s file-reading block below.
let lastStrateFiles = [];

// 2026/08/25：使用者反映「誤吸偏移只能一個檔案load進去，換下一個檔案都
// 沒反應」——查證後這是<input type=file multiple>的原生行為：每次重新
// 打開選擇檔案視窗，只要沒有在同一次視窗裡用Ctrl/Shift多選，瀏覽器就會
// 用這次選到的檔案「整批換掉」上一次選的，不會累加，即使原本就有multiple
// 屬性也一樣——所以分好幾次選、每次只選一份的話，只有最後一次選的那份會
// 留著，前面選的會被使用者以為「消失了/沒反應」。修法：不要直接在analyze()
// 裡讀取input.files，改成每次change事件都把新選到的檔案累加進這個陣列
// (用檔名+大小去重複)，並在畫面上列出目前累加了哪些檔案，可以個別移除或
// 整批清除；input本身每次change後清空(value = "")，這樣同一個檔案再選一次
// 也能正常觸發change(瀏覽器對同一個檔案不會觸發change，清空value可以繞過)。
let pendingStrateFiles = []; // File[] — accumulated across multiple "選擇檔案" interactions

// ---- Visual grids (added 2026/08/18: user asked to see the actual wafer
// MAP here too, not just a table — and to have force-delete positions
// shown as a red outline directly on each substrate's own BINGO MAP,
// updating live as the offset is nudged with direction buttons). Reuses
// the same .wafer-cell/.substrate-cell CSS the main 補資料 page uses. ----
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

// 2026/08/19 ask "誤吸的分頁無法下載wafer mapping" — this page's wafer MAP
// used to only ever appear as a side effect of running the full mispick
// analysis (which needs a STRATE file AND the完整Wafer ID filled in first).
// Added a standalone "預覽/讀取wafer MAP" button (see previewWaferMap()
// below) that hits the same /api/frm endpoint the main page's own "自動
// 讀取FRM檔案" uses, so the wafer bin map can be checked/copied out on its
// own — plus the "顯示/複製座標文字" affordance STRATE補檔頁 already has,
// which is the more literal reading of "下載" (there's nothing to actually
// download as a file here, same as the main page's own wafer grid, but
// copy-to-clipboard text in the established x,y,bin format covers the
// same need — paste-able straight into the main page's manual textarea).
let lastWaferPasteText = "";

// Convenience auto-fill (2026/08/19): converts "目視檢查"'s own "Ref.
// Point" reading into T點 X/Y — see app.js's waferDimsByPanel comment for
// the formula/derivation (confirmed against a real example: Ref. Point
// (-10, 1) on a 46x24 wafer -> DB-rule (45, 14), matching
// WaferCoordinate.exe's own display exactly). Not a replacement for the
// manual T點 fields — just saves doing this arithmetic by hand; still
// only confirmed against one example.
function convertVisualRefPoint() {
  if (!lastWaferData) {
    document.getElementById("mp-preview-status").className = "error";
    document.getElementById("mp-preview-status").textContent = "請先預覽/讀取wafer MAP，才知道columns/rows可以換算";
    return;
  }
  const refX = parseInt(document.getElementById("mp-visual-ref-x").value, 10);
  const refY = parseInt(document.getElementById("mp-visual-ref-y").value, 10);
  if (!Number.isFinite(refX) || !Number.isFinite(refY)) {
    document.getElementById("mp-preview-status").className = "error";
    document.getElementById("mp-preview-status").textContent = "請先填目視檢查顯示的Ref. Point X跟Y";
    return;
  }
  // 2026/08/31更正：這條公式(columns-Ref.Y / rows+Ref.X)是2026/08/19用
  // 真實資料驗證過的，但那次驗證是在frm_to_wafer_bin_map()還沒對調x/y
  // 之前做的(見bingomap/CLAUDE.md的die_map key順序那則)——後來wafer圖
  // 實際渲染用的cells已經對調過，但這條公式的兩個輸出("columns"算出來的
  // 那個、"rows"算出來的那個)分別要填進哪個欄位(T點X/T點Y)沒有跟著對調，
  // 導致算出來的T點Y可能超出wafer圖實際的列數範圍，T點標記永遠不會出現
  // ——使用者回報「給了T點座標都沒有出現T點位置」才抓到。用真實FRM資料
  // 驗證：cells的x範圍大小等於rows、y範圍大小等於columns(兩者已對調)，
  // 所以這裡兩個算式的輸出也要對調著填，公式本身(哪個算式對應哪個
  // Ref.軸)完全不變，只是改填到哪個欄位。
  document.getElementById("mp-t-point-x").value = lastWaferData.rows + refX;
  document.getElementById("mp-t-point-y").value = lastWaferData.columns - refY;
  saveState(); // setting .value in JS doesn't fire "input", so this won't auto-save otherwise
  renderWaferGrid(lastWaferData);
}

// 目前選定的機台偏移量(dx,dy) — 跟bingomap/mispick_analysis.py的
// make_offset()算dx/dy的規則完全一樣(單軸，X填dx、Y填dy)，只用在下面
// 「套用目前偏移後的T點」那張圖，不影響實際分析(分析是後端算的)。
function currentOffsetDelta() {
  const axis = document.getElementById("mp_offset_axis").value;
  const value = parseInt(document.getElementById("mp_offset_value").value, 10) || 0;
  return { dx: axis === "X" ? value : 0, dy: axis === "Y" ? value : 0 };
}

// 畫一張wafer bin圖到指定的容器，refPoint(選填)是要標T點的那一格。抽出來
// 是因為2026/08/27改成同時畫兩張圖(見下面renderWaferGrid())：左邊是原始
// wafer圖(沒有套用偏移)，右邊套用目前機台偏移量。
//
// 2026/08/27再更正：一開始只把T點的標記移動、底下的bin色塊(green/purple/
// gray)完全不動——結果兩張圖除了T點那一格幾乎長得一模一樣，使用者直接
// 指出這是錯的：「因為T點代表整個圖的起始點，當偏移時應該整個圖檔都要
// 跟這偏，本來這顆是bin1有可能把bin7變成bin1，T點往左偏但是應該也會有
// 三顆灰色在旁邊」——也就是說，T點只是這個偏移(dx,dy)的其中一個點，應該
// 是「整片bin色塊圖形」跟著T點做同一個剛體平移，T點附近原本的鄰居(灰色/
// 紫色格子)要整組一起移動、彼此的相對位置不變，才看得出偏移之後哪個
// 位置的die現在對應到哪個bin。改成`shift`參數：畫面上(x,y)這一格顯示的
// bin，改成去查`cellMap.get(x-shift.dx, y-shift.dy)`——也就是「wafer原始
// (x,y)這顆die，偏移後畫在螢幕(x+shift.dx, y+shift.dy)」，跟refPoint(T點)
// 用同一個(x+dx, y+dy)規則搬移，兩者維持相對位置一致。
// `markers`(選填)：Map<"x,y", {decision, action_no, label}>，座標已經是
// 這張圖當下的顯示座標(呼叫端先用rotateWaferPoint()轉過)。兩張圖(左邊
// 原始/右邊套用偏移)畫的是同一組screen(x,y)位置——這一格「應該」對應
// 哪個原始wafer座標(fx,fy)在兩張圖上永遠一樣，差別只在這一格「顯示的
// bin顏色」(cellMap查表用的key)有沒有套用shift，所以標記直接疊在同一個
// screen(x,y)即可，兩張圖都疊得上。
function renderOneWaferGrid(containerId, xOrder, yOrder, cellMap, refPoint, shift, markers) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  const dx = shift ? shift.dx : 0;
  const dy = shift ? shift.dy : 0;

  const headerRow = document.createElement("div");
  headerRow.className = "wafer-row";
  const corner = document.createElement("div");
  corner.className = "grid-axis-cell grid-axis-corner";
  headerRow.appendChild(corner);
  for (const x of xOrder) {
    const label = document.createElement("div");
    label.className = "grid-axis-cell";
    label.textContent = x;
    headerRow.appendChild(label);
  }
  container.appendChild(headerRow);

  for (const y of yOrder) {
    const row = document.createElement("div");
    row.className = "wafer-row";
    const rowLabel = document.createElement("div");
    rowLabel.className = "grid-axis-cell";
    rowLabel.textContent = y;
    row.appendChild(rowLabel);
    for (const x of xOrder) {
      const bin = cellMap.get(`${x - dx},${y - dy}`);
      const cell = document.createElement("div");
      cell.className = "wafer-cell";
      applyBinColor(cell, bin);
      cell.title = `${x}:${y}`;
      const marker = markers && markers.get(`${x},${y}`);
      if (marker) {
        cell.classList.add(marker.decision === "FORCE_DELETE_ACTUAL_BIN_NG" ? "mp-force-marker" : "mp-review-marker");
        cell.textContent = String(marker.action_no);
        cell.title = `${x}:${y} — ${marker.label}`;
      }
      if (refPoint && refPoint.x === x && refPoint.y === y) {
        cell.classList.add("ref-point");
        cell.textContent = "T";
        cell.title = `${x}:${y} — T點` + (marker ? `／${marker.label}` : "");
      }
      row.appendChild(cell);
    }
    container.appendChild(row);
  }
}

function renderWaferGrid(wafer) {
  const panel = document.getElementById("mispick-wafer-panel");
  if (!wafer || !wafer.cells || !wafer.cells.length) {
    document.getElementById("mp-wafer-grid").innerHTML = "";
    document.getElementById("mp-wafer-grid-shifted").innerHTML = "";
    panel.style.display = "none";
    return;
  }
  lastWaferData = wafer;
  panel.style.display = "";
  lastWaferPasteText = wafer.cells
    .slice()
    .sort((a, b) => a.x - b.x || a.y - b.y)
    .map((c) => `${c.x},${c.y},${c.bin}`)
    .join("\n");
  document.getElementById("mp-wafer-text").value = lastWaferPasteText;

  const cellMap = new Map(wafer.cells.map((c) => [`${c.x},${c.y}`, c.bin]));
  renderBinLegend("mp-wafer-bin-legend", cellMap);
  const xs = wafer.cells.map((c) => c.x);
  const ys = wafer.cells.map((c) => c.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);

  // T點 (2026/08/19 ask: "誤吸的圖檔沒有顯示T點 要補充出來這樣我才知道
  // 移動的位置在哪裡") — originally computed from reference_point_x via
  // the same formula as app.js's main-page marker, but 2026/08/19 later
  // that day: decompiled the real WaferCoordinate.exe (user provided the
  // .exe itself) and confirmed ReferencePointX/Y are parsed from the FRM
  // file but never referenced anywhere in its drawing code — the real
  // tool doesn't compute or mark a T點 from them at all. The user
  // explained their own method: eyeballing the (purely geometric) center
  // crosshair against where bin7/bin1 fall nearby — a manual visual call,
  // not a derivable value. So this is a manual input now (see
  // #mp-t-point-x/y), read fresh on every render, same as app.js's
  // currentRefPoint().
  const tx = parseInt(document.getElementById("mp-t-point-x").value, 10);
  const ty = parseInt(document.getElementById("mp-t-point-y").value, 10);
  const refPoint = Number.isFinite(tx) && Number.isFinite(ty) ? { x: tx, y: ty } : null;
  // 2026/08/27新增，同一天再更正成整片圖形一起平移(見renderOneWaferGrid()
  // 的完整說明)：右邊那張圖套用目前的機台偏移量(dx,dy)，T點跟它附近的
  // bin色塊整組一起移動，不是只有T點的標記自己動——偏移量是0(沒有偏移)
  // 時兩張圖會完全一樣，這是預期行為。
  const { dx, dy } = currentOffsetDelta();
  const shift = { dx, dy };
  const shiftedRefPoint = refPoint ? { x: refPoint.x + dx, y: refPoint.y + dy } : null;
  document.getElementById("mp-wafer-tpoint-legend").style.display = refPoint ? "" : "none";
  document.getElementById("mp-wafer-marker-legend").style.display = lastMispickActionMarkers.length ? "" : "none";
  document.getElementById("mp-wafer-info").textContent =
    `LotNo=${wafer.lot_no} WaferID=${wafer.wafer_id}（${wafer.columns}x${wafer.rows}，共${wafer.cells.length}顆有資料）`;
  document.getElementById("mp-wafer-grid-shifted-label").textContent =
    dx === 0 && dy === 0
      ? "套用目前偏移後的整片wafer圖（目前偏移量為0，跟左圖相同）"
      : `套用目前偏移後的整片wafer圖（X${dx >= 0 ? "+" : ""}${dx}、Y${dy >= 0 ? "+" : ""}${dy}）`;

  // 排列順序永遠固定(欄0在右邊、列0在最上面) — 方向調整交給mpAngle在座標
  // 本身上處理(見rotateWaferArray())，不再是可切換的顯示順序。
  const xOrder = [];
  for (let x = minX; x <= maxX; x++) xOrder.push(x);
  xOrder.reverse();
  const yOrder = [];
  for (let y = minY; y <= maxY; y++) yOrder.push(y);

  // 誤吸標記(見lastMispickActionMarkers的說明)：fx/fy是STRATE的原始wafer
  // 座標，這裡的xOrder/yOrder是「這張wafer(`wafer`參數)已經套用過目前
  // mpAngle/mpMirror」之後的顯示座標——要疊上去，得先用同一套
  // rotateWaferPoint()公式把fx/fy轉成顯示座標，用的bounds必須是「旋轉前」
  // 的原始bounds(mpRawWafer.cells)，不能用這裡已經轉過的minX/maxX/minY/
  // maxY，兩者不是同一個座標系。兩張圖(原始/套用偏移)疊在同一個screen
  // (x,y)，理由見renderOneWaferGrid()的markers參數註解。
  const rawBounds = waferRawBounds(mpRawWafer && mpRawWafer.cells);
  const markers = new Map();
  for (const m of lastMispickActionMarkers) {
    const p = rotateWaferPoint(m.fx, m.fy, rawBounds, mpAngle, mpMirror);
    if (!p) continue;
    markers.set(`${p.x},${p.y}`, {
      decision: m.decision,
      action_no: m.action_no,
      label: `第${m.action_no}顆(${m.substrateName})－${decisionLabel(m.decision)}`,
    });
  }

  renderOneWaferGrid("mp-wafer-grid", xOrder, yOrder, cellMap, refPoint, { dx: 0, dy: 0 }, markers);
  renderOneWaferGrid("mp-wafer-grid-shifted", xOrder, yOrder, cellMap, shiftedRefPoint, shift, markers);
}

function renderSubstrateGrid(containerId, sub) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";
  if (!sub.substrate_column || !sub.substrate_row) return;

  // 2026/08/31更正：一個基板位置(tx,ty)可能同時被好幾層(f9)的die佔用
  // (疊層基板)，每一層各自獨立分類、可能有不同的判定結果——原本直接把
  // grid_cells建成單一Map(同一個key重複出現時後面的蓋掉前面的)，導致
  // 「強制點除」被同一格另一層的「正常」判定悄悄蓋掉，畫面上完全看不到
  // 紅框，即使上方文字統計仍然正確算出「強制點除N」——使用者發現數字對
  // 但畫面上找不到那幾顆紅框，才抓到這個問題(「強制點除應該會出現紅色
  // 框框在bingomap圖檔內，這樣我不知道是哪一顆」)。
  //
  // 已改成：同一個位置的所有判定都保留(byPos是位置→判定陣列)，畫面優先
  // 顯示最需要處理的那個(強制點除>人工確認>其他)決定要不要畫紅/黃框，
  // hover文字列出這一格全部層的判定，不會只顯示贏的那一個、讓其他層的
  // 資訊完全消失。
  const DECISION_PRIORITY = { FORCE_DELETE_ACTUAL_BIN_NG: 2, REVIEW_ACTUAL_BIN_REVIEW: 1 };
  const byPos = new Map();
  for (const c of sub.grid_cells) {
    const key = `${c.tx},${c.ty}`;
    if (!byPos.has(key)) byPos.set(key, []);
    byPos.get(key).push(c);
  }

  // 2026/08/31新增：使用者回報「0:0,0:1明明.strate裡有die，BINGO MAP卻
  // 顯示空白」——這個位置的die其實屬於別的wafer_ring，被這次分析排除
  // (analyze_substrate()的wafer_ring過濾，跟上面「排除(非目標Wafer)」的
  // 提示同一批)，所以完全不會進grid_cells，畫面上只能顯示成跟「這個位置
  // 本來就沒上片」一樣的空白格，兩種情況肉眼完全分不出來。用
  // sub.excluded_grid_cells把這些位置另外標出來(斜紋灰底)，跟真正空白
  // 的格子區分開。
  const excludedByPos = new Map();
  for (const c of sub.excluded_grid_cells || []) {
    const key = `${c.tx},${c.ty}`;
    if (!excludedByPos.has(key)) excludedByPos.set(key, []);
    excludedByPos.get(key).push(c);
  }

  // 2026/08/31：跟①補資料頁app.js的renderSubstrateGridInto()同一次修正
  // ——欄(col)由小到大要畫在螢幕「右邊」，0:0固定在右上角，使用者拿①補
  // 資料頁跟機台實際作業畫面現場核對過，見bingomap/CLAUDE.md。這裡是
  // 同一種BINGO MAP格子圖，套用同一個規則。
  const colOrder = [];
  for (let x = 0; x < sub.substrate_column; x++) colOrder.push(x);
  colOrder.reverse();

  const headerRow = document.createElement("div");
  headerRow.className = "wafer-row";
  const corner = document.createElement("div");
  corner.className = "grid-axis-cell grid-axis-corner";
  headerRow.appendChild(corner);
  for (const x of colOrder) {
    const label = document.createElement("div");
    label.className = "grid-axis-cell";
    label.textContent = x;
    headerRow.appendChild(label);
  }
  container.appendChild(headerRow);

  for (let y = 0; y < sub.substrate_row; y++) {
    const row = document.createElement("div");
    row.className = "wafer-row";
    const rowLabel = document.createElement("div");
    rowLabel.className = "grid-axis-cell";
    rowLabel.textContent = y;
    row.appendChild(rowLabel);
    for (const x of colOrder) {
      const cell = document.createElement("div");
      cell.className = "substrate-cell";
      const infos = byPos.get(`${x},${y}`);
      const excludedInfos = excludedByPos.get(`${x},${y}`);
      if (infos && infos.length) {
        cell.classList.add("filled");
        const sorted = [...infos].sort(
          (a, b) => (DECISION_PRIORITY[b.decision] || 0) - (DECISION_PRIORITY[a.decision] || 0)
        );
        const winner = sorted[0];
        if (winner.decision === "FORCE_DELETE_ACTUAL_BIN_NG") cell.classList.add("mp-force");
        else if (winner.decision === "REVIEW_ACTUAL_BIN_REVIEW") cell.classList.add("mp-review");
        let title =
          `${x}:${y} — ` +
          sorted.map((info) => `${decisionLabel(info.decision)}（第${info.layer === "other" ? "2" : "1"}層）`).join("；");
        // 同一個位置也可能「有些層屬於目前比對的wafer(分析了)、有些層
        // 屬於別的wafer(被排除)」——兩種資訊都列出來，不要只顯示其中一種。
        if (excludedInfos && excludedInfos.length) {
          const rings = [...new Set(excludedInfos.map((c) => c.wafer_ring))].join("、");
          title += `；另有其他層屬於wafer_ring=${rings}(非目標wafer，未分析)`;
        }
        cell.title = title;
      } else if (excludedInfos && excludedInfos.length) {
        cell.classList.add("mp-excluded");
        const rings = [...new Set(excludedInfos.map((c) => c.wafer_ring))].join("、");
        cell.title = `${x}:${y} — 此位置有die，但屬於wafer_ring=${rings}(不是你目前比對的目標wafer，未列入這次分析)`;
      } else {
        cell.title = `${x}:${y}`;
      }
      row.appendChild(cell);
    }
    container.appendChild(row);
  }
}

function decisionLabel(decision) {
  if (decision === "FORCE_DELETE_ACTUAL_BIN_NG") return "強制點除";
  if (decision === "REVIEW_ACTUAL_BIN_REVIEW") return "人工確認";
  if (decision === "OK_ACTUAL_GOOD_BIN") return "正常";
  if (decision === "ACTUAL_OTHER_BIN_DIAGNOSTIC") return "異常";
  return decision;
}

function decisionClass(decision) {
  if (decision === "FORCE_DELETE_ACTUAL_BIN_NG") return "bad";
  if (decision === "REVIEW_ACTUAL_BIN_REVIEW") return "warnRow";
  return "";
}

function renderResults(data) {
  mpRawWafer = data.wafer;
  lastMispickActionMarkers = data.substrates
    .filter((sub) => !sub.error)
    .flatMap((sub) =>
      sub.action_rows.map((r) => ({
        fx: r.fx, fy: r.fy, decision: r.decision, action_no: r.action_no, substrateName: sub.name,
      }))
    );
  renderWaferGrid(rotateWaferArray(mpRawWafer, mpAngle, mpMirror));

  const container = document.getElementById("mp-results");
  container.innerHTML = "";

  data.substrates.forEach((sub, idx) => {
    const box = document.createElement("div");
    box.className = "notice";
    box.style.marginTop = "0.8rem";

    if (sub.error) {
      box.classList.add("error");
      box.innerHTML = `<b>${sub.name}</b>（Substrate ID: ${sub.substrate_id ?? "?"}）<br>錯誤：${sub.error}`;
      container.appendChild(box);
      return;
    }

    const s = sub.summary;
    const head = document.createElement("div");
    head.innerHTML =
      `<b>${sub.name}</b>（Substrate ID: ${sub.substrate_id}）｜` +
      `強制點除 ${s.force_delete}｜人工確認 ${s.review}｜異常 ${s.anomaly}｜正常 ${s.ok}｜其他 ${s.other}｜` +
      `排除(非目標Wafer) ${sub.excluded_count}`;
    container.appendChild(head);

    // 2026/08/27新增：排除數字本身看不出來是「使用者Wafer ID打錯字」還是
    // 「這份STRATE本來就是同一個LOT裡別的實體wafer」——把STRATE裡實際
    // 記錄到的wafer_ring攤開來跟目前輸入框比對，直接告訴使用者差在哪，
    // 不用自己開檔案找。排除比例達100%(整份STRATE一顆都沒分析到、BINGO
    // MAP格子圖會整片空白)時特別用醒目樣式標出來，這是最容易被誤以為
    // 「軟體壞了/沒資料」的情況。
    if (sub.excluded_count > 0 && sub.excluded_wafer_rings && sub.excluded_wafer_rings.length) {
      const targetWaferRing = document.getElementById("mp_wafer_ring").value.trim();
      const totalDies = s.force_delete + s.review + s.anomaly + s.ok + s.other + sub.excluded_count;
      const allExcluded = sub.excluded_count === totalDies;
      const note = document.createElement("div");
      note.className = allExcluded ? "notice error" : "notice";
      note.style.marginTop = "0.3rem";
      note.innerHTML =
        (allExcluded
          ? `⚠️ 這份STRATE全部${sub.excluded_count}顆die都被排除，沒有任何一顆進入分析(BINGO MAP會是空白)。`
          : `這份STRATE有${sub.excluded_count}顆die被排除。`) +
        `實際記錄到的wafer_ring是：<b>${sub.excluded_wafer_rings.join("、")}</b>` +
        (targetWaferRing
          ? `，你目前填的「要比對的完整Wafer ID」是：<b>${targetWaferRing}</b>——請確認是否打錯字，` +
            "或這份STRATE本來就是同一個LOT裡另一片實體wafer(改填正確的Wafer ID重新分析即可)。"
          : "，「要比對的完整Wafer ID」欄位目前是空的，請填入這份STRATE實際對應的Wafer ID。");
      container.appendChild(note);
    }

    const gridId = `mp-substrate-grid-${idx}`;
    const gridWrap = document.createElement("div");
    gridWrap.className = "lyr-wafer-wrap";
    gridWrap.style.marginTop = "0.4rem";
    gridWrap.innerHTML = `<div id="${gridId}" class="lyr-substrate-grid"></div>`;
    container.appendChild(gridWrap);
    renderSubstrateGrid(gridId, sub);

    if (sub.action_rows.length) {
      const table = document.createElement("table");
      table.className = "tbl";
      table.style.marginTop = "0.5rem";
      // 2026/09/02新增fx:fy(STRATE的原始wafer_xy)、原本BIN欄位——使用者回報
      // 一個mis-pick案例，拿wafer預覽圖上滑鼠停留看到的座標去對這張表，結果
      // 兜不起來；查出來預覽圖的座標是套用了wafer角度(0/90/180/270度)之後
      // 的顯示座標，跟STRATE檔案裡真正的wafer_xy(這張表格底層用來算偏移的
      // 那組數字)是兩個不同的座標系，肉眼比對很容易搞混。這張表原本只有
      // TX:TY(基板位置)跟actual_bin(偏移後的BIN)，沒有任何欄位直接顯示
      // 偏移計算實際用的原始wafer座標跟原本BIN，逼使用者得去猜——現在直接
      // 把這兩個算式的輸入/輸出都攤在表格上，不用再對照預覽圖。
      table.innerHTML =
        "<thead><tr><th>No.</th><th>判定</th><th>Layer</th><th>Block</th><th>座標</th><th>TX:TY</th>" +
        "<th>原始Wafer座標</th><th>原本BIN</th><th>實際BIN</th></tr></thead>";
      const tbody = document.createElement("tbody");
      for (const r of sub.action_rows) {
        const tr = document.createElement("tr");
        tr.className = decisionClass(r.decision);
        tr.innerHTML =
          `<td>${r.action_no}</td><td>${decisionLabel(r.decision)}</td><td>${r.layer}</td>` +
          `<td>${r.output_block ?? ""}</td><td>${r.output_coord}</td><td>${r.tx}:${r.ty}</td>` +
          `<td>${r.fx}:${r.fy}</td><td>${r.nominal_bin ?? ""}</td><td>${r.actual_bin}</td>`;
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      container.appendChild(table);
    } else {
      const none = document.createElement("p");
      none.className = "small";
      none.textContent = "沒有需要點除或人工確認的位置。";
      container.appendChild(none);
    }
  });
}

function renderStrateFileList() {
  const el = document.getElementById("mp-strate-file-list");
  el.innerHTML = pendingStrateFiles
    .map(
      (f, i) =>
        `<span class="badge" style="margin:0.15rem">${f.name}　<a href="#" data-idx="${i}" class="mp-remove-strate-file" style="color:var(--danger,#dc2626)">移除</a></span>`
    )
    .join("");
  el.querySelectorAll(".mp-remove-strate-file").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      pendingStrateFiles.splice(Number(a.dataset.idx), 1);
      renderStrateFileList();
      document.getElementById("mp-btn-clear-strate-files").style.display = pendingStrateFiles.length ? "" : "none";
    });
  });
  document.getElementById("mp-btn-clear-strate-files").style.display = pendingStrateFiles.length ? "" : "none";
}

async function analyze() {
  const status = document.getElementById("mp-status");
  status.className = "";
  status.textContent = "分析中...";
  document.getElementById("mp-btn-download-csv").style.display = "none";
  lastCsv = null;

  let strateFiles;
  if (pendingStrateFiles.length) {
    strateFiles = [];
    for (const f of pendingStrateFiles) {
      strateFiles.push({ name: f.name, text: await f.text() });
    }
    lastStrateFiles = strateFiles;
  } else if (lastStrateFiles.length) {
    strateFiles = lastStrateFiles; // nudge button, or a restored session — see the comment at lastStrateFiles' declaration
  } else {
    status.className = "error";
    status.textContent = "請至少選擇一份STRATE檔案";
    return;
  }

  const payload = {
    wafer_ring: document.getElementById("mp_wafer_ring").value,
    machine_type: document.getElementById("mp_machine_type").value,
    offset_axis: document.getElementById("mp_offset_axis").value,
    offset_value: document.getElementById("mp_offset_value").value,
    good_bins: document.getElementById("mp_good_bins").value,
    ng_bins: document.getElementById("mp_ng_bins").value,
    review_bins: document.getElementById("mp_review_bins").value,
    frm: {
      lot_no: document.getElementById("mp_frm_lot_no").value,
      barcode_id: document.getElementById("mp_frm_barcode_id").value,
      frm_path: document.getElementById("mp_frm_path").value,
    },
    strate_files: strateFiles,
  };

  const res = await fetch("/api/mispick/analyze", {
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

  renderResults(data);
  lastCsv = data.csv;
  document.getElementById("mp-btn-download-csv").style.display = "";
  updateOffsetDisplay();
  status.className = "ok";
  status.textContent = `分析完成，共 ${data.substrates.length} 份STRATE。`;
  saveState();
}

function downloadCsv() {
  if (!lastCsv) return;
  const blob = new Blob([lastCsv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "誤吸偏移點除清單.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function updateEsecWarning() {
  const isEsec = document.getElementById("mp_machine_type").value === "ESEC";
  document.getElementById("mp-esec-warning").style.display = isEsec ? "" : "none";
}

function updateOffsetDisplay() {
  const axis = document.getElementById("mp_offset_axis").value;
  const value = parseInt(document.getElementById("mp_offset_value").value, 10) || 0;
  // 2026/08/27更正：0是合法值，代表「T點沒有偏移」的基準狀態——之前這裡
  // (跟下面nudgeOffset()、mispick_analysis.py的make_offset())都把0當成
  // 不該出現的例外，使用者指出機台偏移量本來就應該能是0(沒偏移時就是0，
  // 只有真的量到偏移才會是非0)。
  document.getElementById("mp-offset-display").textContent =
    value === 0 ? "目前偏移：無（0，T點沒有偏移）" : `目前偏移：${axis} ${value > 0 ? "+" : ""}${value}`;
}

// Direction buttons (2026/08/18 ask: "當我將WAFER T點移動往右或往左或
// 往上或往下，對應的strate bingo map就要知道對應位置那一顆吃到bin7"):
// each click nudges the offset by 1 in that direction and immediately
// re-runs analyze() against the already-selected STRATE files, so the
// red-outlined force-delete cells on the BINGO MAP grid update live
// instead of needing a manual "分析" click each time. Switching axis
// (e.g. was on Y, click ←/→) starts that axis fresh at ±1 rather than
// carrying over the old axis's magnitude, since a diagonal offset isn't
// a representable case (see mispick_analysis.py's make_offset() — always
// single-axis, matching how the real bonder's known-offset failure mode
// actually happens).
function nudgeOffset(axis, delta) {
  const axisSelect = document.getElementById("mp_offset_axis");
  const valueInput = document.getElementById("mp_offset_value");
  if (axisSelect.value !== axis) {
    axisSelect.value = axis;
    valueInput.value = delta;
  } else {
    // 2026/08/27更正：0是合法的偏移量(代表T點沒有偏移)，不用再特別跳過
    // ——之前這裡會把算出來的0強制改回±1，導致方向微調永遠碰不到0。
    valueInput.value = (parseInt(valueInput.value, 10) || 0) + delta;
  }
  updateOffsetDisplay();
  renderWaferGrid(rotateWaferArray(mpRawWafer, mpAngle, mpMirror));
  analyze();
}

async function previewWaferMap() {
  const status = document.getElementById("mp-preview-status");
  status.className = "";
  status.textContent = "讀取中...";

  const payload = {
    lot_no: document.getElementById("mp_frm_lot_no").value,
    barcode_id: document.getElementById("mp_frm_barcode_id").value,
    frm_path: document.getElementById("mp_frm_path").value,
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

  // 2026/08/25：跟app.js同一次更正(見那邊setWaferRawData的完整註解)——換一片
  // wafer要把角度/鏡像重設回預設值，不然上一片wafer調過的方向會無聲無息
  // 帶到這一片。2026/09/02再更正：改成先查①頁有沒有存過這片wafer(同一組
  // LotNo+BarcodeID)的角度/鏡像——有的話直接套用，不用使用者自己對照兩頁
  // 手動調成一樣。
  mpRawWafer = data;
  const shared = loadSharedWaferAngle(payload.lot_no, payload.barcode_id);
  mpAngle = shared ? shared.angle : 0;
  mpMirror = shared ? !!shared.mirror : false;
  lastMispickActionMarkers = []; // 換一片wafer預覽，舊分析結果的標記不再對得上，清掉
  document.getElementById("mp-wafer-angle").value = String(mpAngle);
  document.getElementById("mp-wafer-mirror").checked = mpMirror;
  renderWaferGrid(rotateWaferArray(mpRawWafer, mpAngle, mpMirror));
  status.className = "ok";
  status.textContent = `已載入 LotNo=${data.lot_no} WaferID=${data.wafer_id}（${data.columns}x${data.rows}，共${data.cells.length}顆有資料）`;
  saveState();
}

document.getElementById("mp_strate_files").addEventListener("change", (e) => {
  const newFiles = [...(e.target.files || [])];
  for (const f of newFiles) {
    const alreadyIn = pendingStrateFiles.some((existing) => existing.name === f.name && existing.size === f.size);
    if (!alreadyIn) pendingStrateFiles.push(f);
  }
  e.target.value = ""; // allows re-picking the same file later and still firing "change"
  renderStrateFileList();
});
document.getElementById("mp-btn-clear-strate-files").addEventListener("click", () => {
  pendingStrateFiles = [];
  renderStrateFileList();
});

document.getElementById("mp-btn-preview-wafer").addEventListener("click", previewWaferMap);
document.getElementById("mp-btn-toggle-wafer-text").addEventListener("click", () => {
  const textarea = document.getElementById("mp-wafer-text");
  const copyBtn = document.getElementById("mp-btn-copy-wafer-text");
  const showing = textarea.style.display !== "none";
  textarea.style.display = showing ? "none" : "";
  copyBtn.style.display = showing ? "none" : "";
});
document.getElementById("mp-btn-copy-wafer-text").addEventListener("click", async () => {
  const copyBtn = document.getElementById("mp-btn-copy-wafer-text");
  const textarea = document.getElementById("mp-wafer-text");
  try {
    await navigator.clipboard.writeText(lastWaferPasteText);
    copyBtn.textContent = "已複製！";
  } catch (err) {
    textarea.select();
    copyBtn.textContent = "複製失敗，請手動選取文字複製";
  }
  setTimeout(() => {
    copyBtn.textContent = "複製到剪貼簿";
  }, 2000);
});

document.getElementById("mp-btn-analyze").addEventListener("click", analyze);
document.getElementById("mp-btn-download-csv").addEventListener("click", downloadCsv);
document.getElementById("mp_machine_type").addEventListener("change", updateEsecWarning);
// 2026/08/27新增：改軸向/改偏移量的當下就要讓下面「套用目前偏移後的T點」
// 那張預覽圖跟著重畫(不用等按「分析」)，跟T點X/Y欄位本來就有的即時重畫是
// 同一個道理(見下面mp-t-point-x/y的input監聽器)。
function updateOffsetDisplayAndPreview() {
  updateOffsetDisplay();
  renderWaferGrid(rotateWaferArray(mpRawWafer, mpAngle, mpMirror));
}
document.getElementById("mp_offset_axis").addEventListener("change", updateOffsetDisplayAndPreview);
document.getElementById("mp_offset_value").addEventListener("input", updateOffsetDisplayAndPreview);
document.getElementById("mp-btn-nudge-up").addEventListener("click", () => nudgeOffset("Y", -1));
document.getElementById("mp-btn-nudge-down").addEventListener("click", () => nudgeOffset("Y", 1));
document.getElementById("mp-btn-nudge-left").addEventListener("click", () => nudgeOffset("X", -1));
document.getElementById("mp-btn-nudge-right").addEventListener("click", () => nudgeOffset("X", 1));
updateEsecWarning();
updateOffsetDisplay();

// ---- Persistence (2026/08/19 ask: "每個分頁在切換的時候資料不要不見" —
// only STRATE補檔/SECS格式化參數頁 had this so far; extending the same
// localStorage convention here). Saves the already-read STRATE file
// contents (lastStrateFiles) plus every form field; a restored session
// re-runs analyze() against them rather than re-deriving results
// client-side, same principle as the other pages' restoreState(). ----
const MP_STORAGE_KEY = "bingomap_mispick_state";
const MP_FIELD_IDS = [
  "mp_frm_lot_no", "mp_frm_barcode_id", "mp_frm_path", "mp_wafer_ring",
  "mp_machine_type", "mp_offset_axis", "mp_offset_value",
  "mp_good_bins", "mp_ng_bins", "mp_review_bins",
  "mp-t-point-x", "mp-t-point-y",
  "mp-visual-ref-x", "mp-visual-ref-y",
];

function saveState() {
  try {
    const fields = {};
    for (const id of MP_FIELD_IDS) fields[id] = document.getElementById(id).value;
    localStorage.setItem(MP_STORAGE_KEY, JSON.stringify({ strateFiles: lastStrateFiles, fields }));
  } catch (err) {
    // localStorage unavailable or quota exceeded — just don't persist
  }
}

function restoreState() {
  const raw = localStorage.getItem(MP_STORAGE_KEY);
  if (!raw) return;
  let saved;
  try {
    saved = JSON.parse(raw);
  } catch (err) {
    return;
  }

  // Field values are restored unconditionally, even with no STRATE files
  // loaded yet — see app.js's identical fix (2026/08/19: saveState() was
  // only ever reached through analyze(), so filling in wafer_ring/FRM
  // lot no/offset settings before ever selecting a STRATE file silently
  // lost those values when switching tabs). A direct 'input'/'change'
  // listener on every field (wired below) now saves immediately too.
  for (const id of MP_FIELD_IDS) {
    if (saved.fields && saved.fields[id] !== undefined) document.getElementById(id).value = saved.fields[id];
  }
  updateEsecWarning();
  updateOffsetDisplay();

  if (!saved.strateFiles || !saved.strateFiles.length) return;
  lastStrateFiles = saved.strateFiles;
  analyze();
}

for (const id of MP_FIELD_IDS) {
  const el = document.getElementById(id);
  el.addEventListener("input", saveState);
  el.addEventListener("change", saveState); // belt-and-suspenders for <select> (machine_type/offset_axis)
}

// T點 fields need a live re-render (not just a save) on every keystroke,
// so the marker moves as the user types in wherever they've determined it
// to be — re-renders whichever wafer is already showing, if any.
document.getElementById("mp-t-point-x").addEventListener("input", () => renderWaferGrid(lastWaferData));
document.getElementById("mp-t-point-y").addEventListener("input", () => renderWaferGrid(lastWaferData));
document.getElementById("mp-btn-convert-visual-ref").addEventListener("click", convertVisualRefPoint);
document.getElementById("mp-wafer-angle").addEventListener("change", (e) => {
  mpAngle = Number(e.target.value);
  saveSharedWaferAngle(
    document.getElementById("mp_frm_lot_no").value,
    document.getElementById("mp_frm_barcode_id").value,
    mpAngle, mpMirror
  );
  renderWaferGrid(rotateWaferArray(mpRawWafer, mpAngle, mpMirror));
});
document.getElementById("mp-wafer-mirror").addEventListener("change", (e) => {
  mpMirror = e.target.checked;
  saveSharedWaferAngle(
    document.getElementById("mp_frm_lot_no").value,
    document.getElementById("mp_frm_barcode_id").value,
    mpAngle, mpMirror
  );
  renderWaferGrid(rotateWaferArray(mpRawWafer, mpAngle, mpMirror));
});
// ①補資料頁改了同一片wafer的角度/鏡像時即時跟著換，見app.js同一段的完整
// 說明——只在目前這裡載入的wafer身分剛好對得上時才套用。
window.addEventListener("storage", (e) => {
  if (e.key !== SHARED_WAFER_ANGLE_KEY || !mpRawWafer) return;
  const shared = loadSharedWaferAngle(
    document.getElementById("mp_frm_lot_no").value,
    document.getElementById("mp_frm_barcode_id").value
  );
  if (!shared || (shared.angle === mpAngle && !!shared.mirror === mpMirror)) return;
  mpAngle = shared.angle;
  mpMirror = !!shared.mirror;
  document.getElementById("mp-wafer-angle").value = String(mpAngle);
  document.getElementById("mp-wafer-mirror").checked = mpMirror;
  renderWaferGrid(rotateWaferArray(mpRawWafer, mpAngle, mpMirror));
});

restoreState();
