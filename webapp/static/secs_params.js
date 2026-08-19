// ⑥ SECS格式化參數 — list every S7F25FormattedPPRequest (Reply) parameter
// snapshot found in a SECS/AFC transaction log (see bingomap/secs_params.py).
// Same UTF-16LE-no-BOM log, same base64-upload/server-side-decode pattern as
// strate_xml.js (file.text() mis-decodes this log, so don't use it).
//
// 2026/08/19: real log only has 2 Reply snapshots (same recipe captured
// twice), 199 unique parameters each — not 181 (使用者記憶中的目前組數)
// or 349 (使用者計畫要擴充到的組數). Flagged to the user in chat; this
// page just lists what's actually in the log. Excel比對功能還沒做——
// 需要使用者提供一份範例Excel檔案才能繼續，不要用猜的欄位格式硬做。
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

function downloadText(filename, text) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function snapshotToCsv(snap) {
  const header = ["CCODE", "名稱", "單位", "格式", "數值", "下限", "上限"];
  const lines = [header.map(csvEscape).join(",")];
  snap.params.forEach((p) => {
    lines.push([p.ccode, p.name, p.unit, p.format, p.value, p.min, p.max].map(csvEscape).join(","));
  });
  return lines.join("\r\n") + "\r\n";
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
      `<div style="overflow-x:auto;margin-top:0.6rem">` +
      `<table class="tbl"><thead><tr>` +
      `<th>CCODE</th><th>名稱</th><th>單位</th><th>格式</th><th>數值</th><th>下限</th><th>上限</th>` +
      `</tr></thead><tbody></tbody></table></div>`;

    const tbody = box.querySelector("tbody");
    snap.params.forEach((p) => {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${p.ccode}</td><td>${p.name}</td><td>${p.unit}</td><td>${p.format}</td>` +
        `<td>${p.value}</td><td>${p.min}</td><td>${p.max}</td>`;
      tbody.appendChild(tr);
    });

    box.querySelector(".sp-btn-download-csv").addEventListener("click", () => {
      const name = (snap.pp_id || `snapshot_${snap.index + 1}`).replace(/[\\/:*?"<>|]/g, "_");
      downloadText(`${name}_TID${snap.tid}.csv`, snapshotToCsv(snap));
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
  saveState(file.name, data);

  status.className = "ok";
  const total = data.snapshots.reduce((sum, s) => sum + s.params.length, 0);
  status.textContent = `解析完成：共找到 ${data.snapshots.length} 筆參數快照，合計 ${total} 項參數。`;
}

// ---- Persistence (同STRATE補檔頁的做法："我切換分頁的時候檔案不要不見") ----
const SP_STORAGE_RESULT = "bingomap_secs_params_result";
const SP_STORAGE_FILENAME = "bingomap_secs_params_filename";

function saveState(filename, data) {
  try {
    localStorage.setItem(SP_STORAGE_RESULT, JSON.stringify(data));
    localStorage.setItem(SP_STORAGE_FILENAME, filename);
  } catch (err) {
    // localStorage unavailable (private mode etc.) — just don't persist
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
  const filename = localStorage.getItem(SP_STORAGE_FILENAME) || "";

  renderSnapshots(data.snapshots);

  const status = document.getElementById("sp-status");
  status.className = "ok";
  const total = data.snapshots.reduce((sum, s) => sum + s.params.length, 0);
  status.textContent =
    `已還原上次解析過的結果${filename ? `（${filename}）` : ""}：共 ${data.snapshots.length} 筆參數快照，` +
    `合計 ${total} 項參數。`;
}

document.getElementById("sp-btn-extract").addEventListener("click", extractLog);
restoreState();
