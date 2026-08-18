// ④ STRATE補檔 XML合併 — extract already-complete substrate data and
// wafer bin maps directly from a SECS/AFC transaction log (see
// bingomap/secs_log.py). The log's real encoding is UTF-16LE with no
// BOM, which a plain `file.text()` read mis-decodes (same failure mode
// as reading the raw bytes as ASCII) — so the file is sent as base64 and
// decoded server-side by decode_secs_log() instead of trusting the
// browser's own text decoding.
let lastLogBase64 = null;

function arrayBufferToBase64(buf) {
  let binary = "";
  const bytes = new Uint8Array(buf);
  const chunkSize = 0x8000; // avoid call-stack limits on String.fromCharCode for large files
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
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

function renderSubstrates(substrates) {
  const panel = document.getElementById("sx-substrates-panel");
  const tbody = document.querySelector("#sx-substrates-table tbody");
  tbody.innerHTML = "";
  document.getElementById("sx-substrate-count").textContent = substrates.length;
  panel.style.display = substrates.length ? "" : "none";

  substrates.forEach((s) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${s.index + 1}</td><td>${s.substrate_id}</td><td>${s.wafer_ring}</td><td>${s.eqpid}</td>` +
      `<td>${s.num_dies}</td><td>${s.num_other_layer_dies}</td><td>${s.total_bond_die_qty}</td><td>${s.good_die}</td>` +
      `<td>${s.last_timestamp}</td><td><button type="button" class="secondary sx-btn-download-one">下載</button></td>`;
    tr.querySelector(".sx-btn-download-one").addEventListener("click", () => downloadText(s.filename, s.text));
    tbody.appendChild(tr);
  });
}

function renderWaferMaps(waferMaps) {
  const panel = document.getElementById("sx-wafer-maps-panel");
  const list = document.getElementById("sx-wafer-maps-list");
  list.innerHTML = "";
  document.getElementById("sx-wafer-map-count").textContent = waferMaps.length;
  panel.style.display = waferMaps.length ? "" : "none";

  waferMaps.forEach((wm) => {
    const box = document.createElement("div");
    box.className = "notice";
    box.style.marginTop = "0.6rem";
    const textareaId = `sx-wafer-map-text-${wm.index}`;
    box.innerHTML =
      `<b>Frame ID：${wm.frame_id}</b>　Wafer ID：${wm.wafer_id}　尺寸：${wm.columns}x${wm.rows}　有資料的格子：${wm.num_cells}顆<br>` +
      `<button type="button" class="secondary sx-btn-toggle-text">顯示/複製座標文字</button>` +
      `<button type="button" class="secondary sx-btn-copy-text" style="display:none">複製到剪貼簿</button>` +
      `<textarea id="${textareaId}" rows="6" readonly style="display:none;width:100%;margin-top:0.4rem"></textarea>`;
    const textarea = box.querySelector(`#${textareaId}`);
    textarea.value = wm.paste_text;
    const toggleBtn = box.querySelector(".sx-btn-toggle-text");
    const copyBtn = box.querySelector(".sx-btn-copy-text");
    toggleBtn.addEventListener("click", () => {
      const showing = textarea.style.display !== "none";
      textarea.style.display = showing ? "none" : "";
      copyBtn.style.display = showing ? "none" : "";
    });
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(wm.paste_text);
        copyBtn.textContent = "已複製！";
      } catch (err) {
        textarea.select();
        copyBtn.textContent = "複製失敗，請手動選取文字複製";
      }
      setTimeout(() => {
        copyBtn.textContent = "複製到剪貼簿";
      }, 2000);
    });
    list.appendChild(box);
  });
}

async function extractLog() {
  const status = document.getElementById("sx-status");
  const fileInput = document.getElementById("sx_log_file");
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

  const res = await fetch("/api/strate_xml/extract", {
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

  renderSubstrates(data.substrates);
  renderWaferMaps(data.wafer_maps);

  status.className = "ok";
  status.textContent = `解析完成：共找到 ${data.substrates.length} 筆基板資料、${data.wafer_maps.length} 筆wafer bin map資料。`;
}

async function downloadZip() {
  const status = document.getElementById("sx-status");
  if (!lastLogBase64) {
    status.className = "error";
    status.textContent = "請先解析log";
    return;
  }
  const res = await fetch("/api/strate_xml/download_zip", {
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
  a.download = "strate_xml_extract.zip";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

document.getElementById("sx-btn-extract").addEventListener("click", extractLog);
document.getElementById("sx-btn-download-zip").addEventListener("click", downloadZip);
