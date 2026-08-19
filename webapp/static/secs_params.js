// ⑥ SECS格式化參數 — the page's default content is a FIXED 199-parameter
// baseline (see bingomap/data/secs_params_baseline.json), loaded straight
// from the server on page open — 2026/08/19 ask: "把這頁改成這199格式化
// 參數固定在裡面", so it doesn't need a log re-upload every time just to
// see the current parameter list. Separately, "上傳SECS Log" (section③)
// still works for checking a DIFFERENT log's own snapshot on its own —
// same UTF-16LE-no-BOM log, same base64-upload/server-side-decode pattern
// as strate_xml.js (file.text() mis-decodes this log, so don't use it).
//
// Excel比對功能(section②)還沒做——需要使用者提供一份範例Excel檔案才能
// 繼續，不要用猜的欄位格式硬做；目前只是UI骨架(輸入框/按鈕都disabled)。
let lastLogBase64 = null;

function arrayBufferToBase64(buf) {
  let binary = "";
  const bytes = new Uint8Array(buf);
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

function csvEscape(v) {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

// BOM prefix so Excel opens it as UTF-8 rather than guessing Big5 (garbled
// Chinese column headers) — same fix already applied to the mispick CSV
// export server-side (webapp/app.py's _csv_text); this one is generated
// client-side so the BOM has to go into the Blob's text content itself.
function downloadText(filename, text, withBom) {
  const blob = new Blob([withBom ? "﻿" + text : text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function paramsToCsv(params) {
  const header = ["#", "CCODE", "名稱", "單位", "格式", "數值", "下限", "上限"];
  const lines = [header.map(csvEscape).join(",")];
  params.forEach((p, i) => {
    lines.push([i + 1, p.ccode, p.name, p.unit, p.format, p.value, p.min, p.max].map(csvEscape).join(","));
  });
  return lines.join("\r\n") + "\r\n";
}

// Shared table renderer (2026/08/19 ask: "要有項目1.2.3讓我知道共有幾項")
// — every params table (baseline + any per-snapshot table) gets a leading
// "#" column, both so the total count is obvious at a glance and so a
// specific row is easy to reference/report back.
function renderParamsTable(container, params) {
  container.innerHTML = "";
  const table = document.createElement("table");
  table.className = "tbl";
  table.innerHTML =
    "<thead><tr><th>#</th><th>CCODE</th><th>名稱</th><th>單位</th><th>格式</th><th>數值</th><th>下限</th><th>上限</th></tr></thead>";
  const tbody = document.createElement("tbody");
  params.forEach((p, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${i + 1}</td><td>${p.ccode}</td><td>${p.name}</td><td>${p.unit}</td><td>${p.format}</td>` +
      `<td>${p.value}</td><td>${p.min}</td><td>${p.max}</td>`;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.appendChild(table);
}

async function downloadGet(path, filename) {
  const res = await fetch(path);
  if (!res.ok) {
    const data = await res.json();
    alert(data.error || "下載失敗");
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ---- ①目前機台基準參數清單 (固定內建，開啟頁面就直接載入，不用上傳log) ----
async function loadBaseline() {
  const info = document.getElementById("sp-baseline-info");
  const res = await fetch("/api/secs_params/baseline");
  const data = await res.json();
  if (!res.ok) {
    info.className = "error";
    info.textContent = data.error || "載入基準參數清單失敗";
    return;
  }
  document.getElementById("sp-baseline-count").textContent = data.params.length;
  info.className = "";
  info.textContent = `PP_ID：${data.pp_id}　MDLN：${data.mdln}　SOFTREV：${data.softrev}　來源TID：${data.source_tid}`;
  renderParamsTable(document.getElementById("sp-baseline-table-wrap"), data.params);
}

document.getElementById("sp-btn-download-baseline-txt").addEventListener("click", () => {
  downloadGet("/api/secs_params/baseline/download_txt", "secs_params_baseline.txt");
});
document.getElementById("sp-btn-download-baseline-excel").addEventListener("click", () => {
  downloadGet("/api/secs_params/baseline/download_excel", "secs_params_baseline.xlsx");
});

// ---- ③（進階/選用）從其他SECS Log重新解析 — unlike ①, this re-sends the
// original log to the server and re-parses it there, same principle as
// STRATE補檔頁的「全部下載zip」：never trust client-held result data for
// a download when the source log is still available, re-derive it. ----
async function downloadFromServer(path, filename) {
  const status = document.getElementById("sp-status");
  if (!lastLogBase64) {
    status.className = "error";
    status.textContent = "請先重新選擇log檔案（上次的log內容太大，沒能一起保留，需要重新上傳一次才能匯出）";
    return;
  }
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ log_base64: lastLogBase64 }),
  });
  if (!res.ok) {
    const data = await res.json();
    status.className = "error";
    status.textContent = data.error;
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function downloadAllTxt() {
  downloadFromServer("/api/secs_params/download_txt", "secs_params.txt");
}

function downloadAllExcel() {
  downloadFromServer("/api/secs_params/download_excel", "secs_params.xlsx");
}

function renderSnapshots(snapshots) {
  const panel = document.getElementById("sp-snapshots-panel");
  const list = document.getElementById("sp-snapshots-list");
  list.innerHTML = "";
  document.getElementById("sp-snapshot-count").textContent = snapshots.length;
  panel.style.display = snapshots.length ? "" : "none";

  snapshots.forEach((snap) => {
    const box = document.createElement("div");
    box.className = "notice";
    box.style.marginTop = "0.6rem";
    box.innerHTML =
      `<b>PP_ID：${snap.pp_id}</b>　MDLN：${snap.mdln}　SOFTREV：${snap.softrev}　TID：${snap.tid}　` +
      `參數數量：${snap.params.length}<br>` +
      `<button type="button" class="secondary sp-btn-download-csv">下載CSV</button>` +
      `<div class="sp-table-wrap" style="overflow-x:auto;margin-top:0.6rem"></div>`;

    renderParamsTable(box.querySelector(".sp-table-wrap"), snap.params);

    box.querySelector(".sp-btn-download-csv").addEventListener("click", () => {
      const name = (snap.pp_id || `snapshot_${snap.index + 1}`).replace(/[\\/:*?"<>|]/g, "_");
      downloadText(`${name}_TID${snap.tid}.csv`, paramsToCsv(snap.params), true);
    });

    list.appendChild(box);
  });
}

async function extractLog() {
  const status = document.getElementById("sp-status");
  const fileInput = document.getElementById("sp_log_file");
  const file = fileInput.files && fileInput.files[0];
  if (!file) {
    status.className = "error";
    status.textContent = "請先選擇一個log檔案";
    return;
  }

  status.className = "";
  status.textContent = "讀取中...";

  const buf = await file.arrayBuffer();
  lastLogBase64 = arrayBufferToBase64(buf);

  const res = await fetch("/api/secs_params/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ log_base64: lastLogBase64 }),
  });
  const data = await res.json();
  if (!res.ok) {
    status.className = "error";
    status.textContent = data.error;
    return;
  }

  renderSnapshots(data.snapshots);
  saveState(file.name, lastLogBase64, data);

  status.className = "ok";
  const total = data.snapshots.reduce((sum, s) => sum + s.params.length, 0);
  status.textContent = `解析完成：共找到 ${data.snapshots.length} 筆參數快照，合計 ${total} 項參數。`;
}

// ---- Persistence (同STRATE補檔頁的做法："我切換分頁的時候檔案不要不見") ----
// Only covers section③ (checking a different log) — section① is always
// re-fetched fresh from the server on load, so it never goes stale.
const SP_STORAGE_RESULT = "bingomap_secs_params_result";
const SP_STORAGE_FILENAME = "bingomap_secs_params_filename";
const SP_STORAGE_LOG = "bingomap_secs_params_log_base64";

function saveState(filename, logBase64, data) {
  try {
    localStorage.setItem(SP_STORAGE_RESULT, JSON.stringify(data));
    localStorage.setItem(SP_STORAGE_FILENAME, filename);
  } catch (err) {
    return; // localStorage unavailable entirely (private mode etc.) — just don't persist
  }
  try {
    localStorage.setItem(SP_STORAGE_LOG, logBase64);
  } catch (err) {
    localStorage.removeItem(SP_STORAGE_LOG); // too large for quota — drop it, keep the rest
  }
}

function restoreState() {
  const raw = localStorage.getItem(SP_STORAGE_RESULT);
  if (!raw) return;
  let data;
  try {
    data = JSON.parse(raw);
  } catch (err) {
    return;
  }
  lastLogBase64 = localStorage.getItem(SP_STORAGE_LOG); // may be null — see saveState()
  const filename = localStorage.getItem(SP_STORAGE_FILENAME) || "";

  renderSnapshots(data.snapshots);

  const status = document.getElementById("sp-status");
  status.className = "ok";
  const total = data.snapshots.reduce((sum, s) => sum + s.params.length, 0);
  const logNote = lastLogBase64 ? "" : "（檔案內容太大沒能一起保留，匯出TXT/Excel要重新選一次同一個log檔案才能用）";
  status.textContent =
    `已還原上次解析過的結果${filename ? `（${filename}）` : ""}：共 ${data.snapshots.length} 筆參數快照，` +
    `合計 ${total} 項參數。${logNote}`;
}

document.getElementById("sp-btn-extract").addEventListener("click", extractLog);
document.getElementById("sp-btn-download-all-txt").addEventListener("click", downloadAllTxt);
document.getElementById("sp-btn-download-all-excel").addEventListener("click", downloadAllExcel);
loadBaseline();
restoreState();
