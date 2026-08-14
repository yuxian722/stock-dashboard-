let lastCsv = null;

function decisionLabel(decision) {
  if (decision === "FORCE_DELETE_ACTUAL_BIN_NG") return "強制點除";
  if (decision === "REVIEW_ACTUAL_BIN_REVIEW") return "人工確認";
  return decision;
}

function decisionClass(decision) {
  if (decision === "FORCE_DELETE_ACTUAL_BIN_NG") return "bad";
  if (decision === "REVIEW_ACTUAL_BIN_REVIEW") return "warnRow";
  return "";
}

function renderResults(data) {
  const container = document.getElementById("mp-results");
  container.innerHTML = "";

  const waferInfo = document.createElement("p");
  waferInfo.className = "small";
  waferInfo.textContent = `原始wafer MAP：LotNo=${data.wafer.lot_no} WaferID=${data.wafer.wafer_id}（${data.wafer.columns}x${data.wafer.rows}）`;
  container.appendChild(waferInfo);

  for (const sub of data.substrates) {
    const box = document.createElement("div");
    box.className = "notice";
    box.style.marginTop = "0.8rem";

    if (sub.error) {
      box.classList.add("error");
      box.innerHTML = `<b>${sub.name}</b>（Substrate ID: ${sub.substrate_id ?? "?"}）<br>錯誤：${sub.error}`;
      container.appendChild(box);
      continue;
    }

    const s = sub.summary;
    const head = document.createElement("div");
    head.innerHTML =
      `<b>${sub.name}</b>（Substrate ID: ${sub.substrate_id}）｜` +
      `強制點除 ${s.force_delete}｜人工確認 ${s.review}｜異常 ${s.anomaly}｜正常 ${s.ok}｜其他 ${s.other}｜` +
      `排除(非目標Wafer) ${sub.excluded_count}`;
    container.appendChild(head);

    if (sub.action_rows.length) {
      const table = document.createElement("table");
      table.className = "tbl";
      table.style.marginTop = "0.5rem";
      table.innerHTML =
        "<thead><tr><th>No.</th><th>判定</th><th>Layer</th><th>Block</th><th>座標</th><th>TX:TY</th><th>實際BIN</th></tr></thead>";
      const tbody = document.createElement("tbody");
      for (const r of sub.action_rows) {
        const tr = document.createElement("tr");
        tr.className = decisionClass(r.decision);
        tr.innerHTML =
          `<td>${r.action_no}</td><td>${decisionLabel(r.decision)}</td><td>${r.layer}</td>` +
          `<td>${r.output_block ?? ""}</td><td>${r.output_coord}</td><td>${r.tx}:${r.ty}</td><td>${r.actual_bin}</td>`;
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
  }
}

async function analyze() {
  const status = document.getElementById("mp-status");
  status.className = "";
  status.textContent = "分析中...";
  document.getElementById("mp-btn-download-csv").style.display = "none";
  lastCsv = null;

  const files = [...(document.getElementById("mp_strate_files").files || [])];
  if (!files.length) {
    status.className = "error";
    status.textContent = "請至少選擇一份STRATE檔案";
    return;
  }
  const strateFiles = [];
  for (const f of files) {
    strateFiles.push({ name: f.name, text: await f.text() });
  }

  const payload = {
    wafer_ring: document.getElementById("mp_wafer_ring").value,
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
  status.className = "ok";
  status.textContent = `分析完成，共 ${data.substrates.length} 份STRATE。`;
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

document.getElementById("mp-btn-analyze").addEventListener("click", analyze);
document.getElementById("mp-btn-download-csv").addEventListener("click", downloadCsv);
