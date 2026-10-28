// SECS LOG BINGO MAP 檢視器 — 簡化版獨立小工具的前端。
// 只做三件事：上傳log(base64送到後端解析)→每枚基板畫一張BINGO MAP格子圖
// (正向/反向純粹是前端重新排列畫面，不重新打API、更不會動到下載的文字)
// →逐枚下載(直接用後端回傳的文字組Blob，不用再打一次API)。

let lastSubstrates = [];
let orientation = "forward"; // "forward" | "reverse" — see simple_bingo_viewer.py's module docstring

function arrayBufferToBase64(buf) {
  let binary = "";
  const bytes = new Uint8Array(buf);
  const chunkSize = 0x8000; // avoid call-stack limits on String.fromCharCode for large files
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

async function extractLog() {
  const fileInput = document.getElementById("log-file");
  const status = document.getElementById("status");
  const file = fileInput.files[0];
  if (!file) {
    status.className = "error";
    status.textContent = "請先選擇log檔案";
    return;
  }
  status.className = "";
  status.textContent = "解析中...";

  const buf = await file.arrayBuffer();
  const log_base64 = arrayBufferToBase64(buf);

  const res = await fetch("/api/simple_bingo/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ log_base64 }),
  });
  const data = await res.json();
  if (!res.ok) {
    status.className = "error";
    status.textContent = data.error || "解析失敗";
    document.getElementById("orientation-panel").style.display = "none";
    document.getElementById("substrates-panel").style.display = "none";
    return;
  }

  lastSubstrates = data.substrates;
  status.className = "ok";
  status.textContent = `解析完成，找到 ${lastSubstrates.length} 枚基板。`;
  document.getElementById("orientation-panel").style.display = "";
  document.getElementById("substrates-panel").style.display = "";
  document.getElementById("substrate-count").textContent = lastSubstrates.length;
  renderAll();
}

// 「反向」只是把列的畫面順序倒過來(欄不動)——跟bingomap/CLAUDE.md記錄過的
// 「Bingo Map Query」報表工具自己的顯示轉換是同一種變換，純畫面層，不碰
// 座標資料本身。row這裡仍然是原始row值，只是決定畫在畫面上的哪一列。
function displayRow(row, minRow, maxRow) {
  return orientation === "reverse" ? maxRow - (row - minRow) : row;
}

function renderSubstrateGrid(container, substrate) {
  container.innerHTML = "";
  const { min_col, max_col, min_row, max_row, positions } = substrate;
  const posByRowCol = new Map();
  for (const p of positions) posByRowCol.set(`${p.col},${p.row}`, p);

  const grid = document.createElement("div");
  grid.className = "lyr-substrate-grid";

  // Build row -> display position once, then iterate display order top to
  // bottom so "反向" doesn't need to touch posByRowCol at all.
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
  grid.appendChild(headerRow);

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
    grid.appendChild(rowEl);
  }
  container.appendChild(grid);
}

function downloadSubstrate(substrate) {
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

function renderAll() {
  const list = document.getElementById("substrates-list");
  list.innerHTML = "";
  for (const substrate of lastSubstrates) {
    const card = document.createElement("div");
    card.className = "panel";
    card.style.marginTop = "1rem";

    const title = document.createElement("h3");
    title.textContent = `流水號：${substrate.substrate_id || "(無編號)"}`;
    card.appendChild(title);

    const info = document.createElement("p");
    info.className = "small";
    info.textContent =
      `Wafer Ring：${substrate.wafer_ring || "—"}　EQPID：${substrate.eqpid || "—"}　` +
      `DIE數量：${substrate.num_dies}` +
      (substrate.num_other_layer_dies ? `（另有疊層${substrate.num_other_layer_dies}顆）` : "");
    card.appendChild(info);

    const gridWrap = document.createElement("div");
    gridWrap.style.overflow = "auto";
    gridWrap.style.maxWidth = "100%";
    card.appendChild(gridWrap);
    renderSubstrateGrid(gridWrap, substrate);

    const btn = document.createElement("button");
    btn.textContent = `下載 ${substrate.filename}`;
    btn.style.marginTop = "0.6rem";
    btn.addEventListener("click", () => downloadSubstrate(substrate));
    card.appendChild(btn);

    list.appendChild(card);
  }
}

document.getElementById("btn-extract").addEventListener("click", extractLog);
for (const el of document.querySelectorAll('input[name="orientation"]')) {
  el.addEventListener("change", (e) => {
    orientation = e.target.value;
    renderAll();
  });
}
