/**
 * Phase 5 UI — textContent only for document/answer-derived text.
 * Admin token kept in a JS memory variable (not localStorage).
 */

let adminToken = "";

const $ = (id) => document.getElementById(id);

function setText(el, value) {
  if (!el) return;
  el.textContent = value == null ? "" : String(value);
}

function showPanel(name) {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === name);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    const match = panel.id === `panel-${name}`;
    panel.hidden = !match;
    panel.classList.toggle("active", match);
  });
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.json) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
    delete options.json;
  }
  if (options.admin) {
    headers["X-Admin-Token"] = adminToken;
  }
  const res = await fetch(path, { ...options, headers });
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const msg =
      body && body.error && body.error.message
        ? body.error.message
        : typeof body === "string"
          ? body
          : JSON.stringify(body);
    throw new Error(`${res.status}: ${msg}`);
  }
  return body;
}

function setStatusBadge(status) {
  const el = $("ask-status");
  const label = status || "idle";
  el.className = `status-badge ${label}`;
  setText(el, label);
}

function renderSources(sources) {
  const panel = $("sources-panel");
  panel.replaceChildren();
  (sources || []).forEach((src, idx) => {
    const card = document.createElement("div");
    card.className = "source-card";
    card.id = `source-${idx}`;
    card.dataset.chunkId = src.chunk_id || "";

    const title = document.createElement("div");
    setText(title, src.title || "(untitled)");
    title.style.fontWeight = "600";

    const meta = document.createElement("div");
    meta.className = "muted";
    const bits = [
      src.label ? `label ${src.label}` : null,
      src.version != null ? `v${src.version}` : null,
      src.page != null ? `page ${src.page}` : null,
      src.heading_path || null,
    ].filter(Boolean);
    setText(meta, bits.join(" · "));

    const quote = document.createElement("div");
    setText(quote, src.quote ? `Quote: ${src.quote}` : "");

    const excerpt = document.createElement("pre");
    setText(excerpt, src.excerpt || src.chunk_text || "");

    card.append(title, meta, quote, excerpt);
    panel.appendChild(card);
  });
}

function renderChips(sources) {
  const chips = $("citation-chips");
  chips.replaceChildren();
  (sources || []).forEach((src, idx) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip";
    setText(btn, src.label || `S${idx + 1}`);
    btn.addEventListener("click", () => {
      chips.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
      btn.classList.add("active");
      const card = $(`source-${idx}`);
      if (card) {
        document.querySelectorAll(".source-card").forEach((c) => c.classList.remove("highlight"));
        card.classList.add("highlight");
        card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });
    chips.appendChild(btn);
  });
}

function renderConflicts(conflicts) {
  const panel = $("conflicts-panel");
  panel.replaceChildren();
  if (!conflicts || !conflicts.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    setText(empty, "No conflicts detected.");
    panel.appendChild(empty);
    return;
  }
  conflicts.forEach((c) => {
    const box = document.createElement("div");
    box.className = "source-card";
    const head = document.createElement("div");
    setText(head, `${c.subject || "?"} / ${c.attribute || "?"}`);
    head.style.fontWeight = "600";
    const adj = document.createElement("div");
    adj.className = "muted";
    setText(adj, c.adjudication || "");
    const sides = document.createElement("pre");
    setText(
      sides,
      (c.sides || [])
        .map((s) => `${s.value || ""} — ${s.quote || ""} [${s.source_label || s.chunk_id}]`)
        .join("\n"),
    );
    box.append(head, adj, sides);
    panel.appendChild(box);
  });
}

async function ask() {
  const question = $("question").value.trim();
  if (!question) {
    setStatusBadge("insufficient");
    setText($("answer-text"), "Enter a question.");
    return;
  }
  setStatusBadge("idle");
  setText($("ask-status"), "running…");
  try {
    const mode = $("mode").value;
    const data = await api("/api/query", {
      method: "POST",
      json: { question, mode },
    });
    setStatusBadge(data.status || "insufficient");
    setText($("answer-text"), data.answer || data.abstention_reason || "(no answer)");
    setText($("missing-info"), data.missing_information || "");
    renderChips(data.sources || []);
    renderSources(data.sources || []);
    renderConflicts(data.conflicts || []);
    setText($("trace-panel"), JSON.stringify(data.trace || [], null, 2));
    setText($("usage-panel"), JSON.stringify(data.usage || {}, null, 2));
  } catch (err) {
    setStatusBadge("insufficient");
    setText($("answer-text"), String(err.message || err));
  }
}

async function refreshDocs() {
  const tbody = $("docs-table").querySelector("tbody");
  tbody.replaceChildren();
  try {
    const data = await api("/api/documents?limit=100");
    setText($("docs-msg"), `${data.total} document(s)`);
    (data.items || []).forEach((doc) => {
      const tr = document.createElement("tr");
      const tdTitle = document.createElement("td");
      setText(tdTitle, doc.title || doc.filename || doc.id);
      const tdStatus = document.createElement("td");
      setText(tdStatus, doc.status);
      const tdVer = document.createElement("td");
      setText(tdVer, String(doc.active_version));
      const tdAct = document.createElement("td");

      const viewBtn = document.createElement("button");
      viewBtn.type = "button";
      viewBtn.className = "linkish";
      setText(viewBtn, "chunks");
      viewBtn.addEventListener("click", () => viewChunks(doc.id));

      const upd = document.createElement("input");
      upd.type = "file";
      upd.title = "Update file";
      upd.addEventListener("change", async () => {
        if (!upd.files || !upd.files[0]) return;
        await updateDoc(doc.id, upd.files[0]);
        await refreshDocs();
      });

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "linkish";
      setText(delBtn, "delete");
      delBtn.addEventListener("click", async () => {
        await deleteDoc(doc.id);
        await refreshDocs();
      });

      tdAct.append(viewBtn, document.createTextNode(" "), upd, document.createTextNode(" "), delBtn);
      tr.append(tdTitle, tdStatus, tdVer, tdAct);
      tbody.appendChild(tr);
    });
  } catch (err) {
    setText($("docs-msg"), String(err.message || err));
  }
}

async function viewChunks(id) {
  try {
    const data = await api(`/api/documents/${encodeURIComponent(id)}/chunks`);
    const lines = (data.items || []).map(
      (c) => `[#${c.chunk_index}] ${c.heading_path || ""} p${c.page ?? "-"}\n${c.text}`,
    );
    setText($("chunks-panel"), lines.join("\n\n---\n\n") || "(no chunks)");
  } catch (err) {
    setText($("chunks-panel"), String(err.message || err));
  }
}

async function uploadDoc() {
  const fileInput = $("upload-file");
  if (!fileInput.files || !fileInput.files[0]) {
    setText($("docs-msg"), "Choose a file first.");
    return;
  }
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  const key = $("external-key").value.trim();
  if (key) fd.append("external_key", key);
  try {
    const data = await api("/api/documents", { method: "POST", body: fd, admin: true });
    setText($("docs-msg"), `Upload: ${data.outcome} ${data.document_id || ""}`);
    await refreshDocs();
  } catch (err) {
    setText($("docs-msg"), String(err.message || err));
  }
}

async function updateDoc(id, file) {
  const fd = new FormData();
  fd.append("file", file);
  try {
    const data = await api(`/api/documents/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: fd,
      admin: true,
    });
    setText($("docs-msg"), `Update: ${data.outcome}`);
  } catch (err) {
    setText($("docs-msg"), String(err.message || err));
  }
}

async function deleteDoc(id) {
  try {
    const data = await api(`/api/documents/${encodeURIComponent(id)}`, {
      method: "DELETE",
      admin: true,
    });
    setText($("docs-msg"), `Delete: ${data.outcome}`);
  } catch (err) {
    setText($("docs-msg"), String(err.message || err));
  }
}

async function refreshStats() {
  try {
    const data = await api("/api/stats");
    setText($("stats-panel"), JSON.stringify(data, null, 2));
  } catch (err) {
    setText($("stats-panel"), String(err.message || err));
  }
}

async function refreshEval() {
  try {
    const data = await api("/api/eval/runs");
    if (!data.runs || data.runs.length === 0) {
      setText(
        $("eval-panel"),
        data.note || "No evaluation runs yet (Phase 7).",
      );
    } else {
      setText($("eval-panel"), JSON.stringify(data, null, 2));
    }
  } catch (err) {
    setText($("eval-panel"), String(err.message || err));
  }
}

async function refreshHealth() {
  try {
    setText($("health-panel"), JSON.stringify(await api("/api/health"), null, 2));
    setText($("ready-panel"), JSON.stringify(await api("/api/health/ready"), null, 2));
    setText($("version-panel"), JSON.stringify(await api("/api/version"), null, 2));
  } catch (err) {
    setText($("health-panel"), String(err.message || err));
  }
}

function wire() {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const name = btn.dataset.tab;
      showPanel(name);
      if (name === "documents") refreshDocs();
      if (name === "stats") refreshStats();
      if (name === "eval") refreshEval();
      if (name === "health") refreshHealth();
    });
  });
  $("ask-btn").addEventListener("click", ask);
  $("save-token").addEventListener("click", () => {
    adminToken = $("admin-token").value;
    setText($("token-state"), adminToken ? "set (memory)" : "not set");
  });
  $("upload-btn").addEventListener("click", uploadDoc);
  $("refresh-stats").addEventListener("click", refreshStats);
  $("refresh-eval").addEventListener("click", refreshEval);
  $("refresh-health").addEventListener("click", refreshHealth);
  setStatusBadge("idle");
}

wire();
