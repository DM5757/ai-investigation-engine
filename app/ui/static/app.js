/**
 * Reviewer demo UI — textContent only for document/answer-derived text.
 * Admin token kept in a JS memory variable only. Sample chips hit the live API.
 */

let adminToken = "";
let askController = null;
let progressTimer = null;
let progressStartedAt = 0;

const QUERY_TIMEOUT_MS = 320000;

const SAMPLES = [
  {
    id: "factual",
    label: "Factual",
    question: "What is Roanoke–Blacksburg Regional Airport, and where is it located?",
  },
  {
    id: "comparison",
    label: "Multi-doc comparison",
    question:
      "Is Ohio State University or California State University, Dominguez Hills further west?",
  },
  {
    id: "multihop",
    label: "Multi-hop",
    question:
      "Michael Lent is best known as the co-writer of the memoirs of Hugh Rowland, a star on a reality television series that premiered on what date?",
  },
  {
    id: "conflict",
    label: "Conflicting evidence",
    question:
      "What do the documents say about auth-gateway deploy time on 2024-03-12? Note any contradictions.",
  },
  {
    id: "insufficient",
    label: "Insufficient evidence",
    question: "What was FraudScorer CPU usage during the incident?",
  },
];

const $ = (id) => document.getElementById(id);

function setText(el, value) {
  if (!el) return;
  el.textContent = value == null ? "" : String(value);
}

function showPanel(name) {
  document.querySelectorAll(".tab").forEach((btn) => {
    const on = btn.dataset.tab === name;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    const match = panel.id === `panel-${name}`;
    panel.hidden = !match;
    panel.classList.toggle("active", match);
  });
}

function humanError(err) {
  const raw = String(err && err.message ? err.message : err || "Request failed");
  const lower = raw.toLowerCase();
  if (err && err.name === "AbortError") {
    return "The investigation timed out waiting for the server. Free-tier cold starts can take about a minute — try again.";
  }
  if (lower.includes("quota") || lower.includes("rate limit") || lower.includes("429")) {
    return "Provider quota or rate limit reached. The engine will not invent an answer; try again later or use a case that stays on the deterministic path.";
  }
  if (lower.includes("daily llm") || lower.includes("llm call cap")) {
    return "Daily LLM call cap reached. Deterministic investigations may still work; adaptive synthesis is paused.";
  }
  if (lower.includes("502") || lower.includes("503") || lower.includes("504")) {
    return "Service temporarily unavailable (likely a cold start or deploy). Wait a moment and retry.";
  }
  if (lower.includes("failed to fetch") || lower.includes("networkerror")) {
    return "Network error reaching the API. Check connectivity and retry.";
  }
  return raw.length > 280 ? `${raw.slice(0, 277)}…` : raw;
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
    const err = new Error(`${res.status}: ${msg}`);
    err.status = res.status;
    err.payload = body;
    throw err;
  }
  return body;
}

function setStatusBadge(status) {
  const el = $("ask-status");
  const label = status || "idle";
  el.className = `status-badge ${label}`;
  setText(el, label);
}

function clearProgress() {
  if (progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
  const box = $("progress");
  if (box) box.hidden = true;
}

function startProgress() {
  clearProgress();
  progressStartedAt = performance.now();
  const box = $("progress");
  box.hidden = false;
  setText($("progress-label"), "Investigating…");
  setText($("progress-elapsed"), "0.0s");
  setText(
    $("progress-note"),
    "Cold starts on free hosting can take up to about a minute. Stages below appear after the response.",
  );
  progressTimer = setInterval(() => {
    const s = (performance.now() - progressStartedAt) / 1000;
    setText($("progress-elapsed"), `${s.toFixed(1)}s`);
    if (s > 45) {
      setText($("progress-label"), "Still working…");
      setText(
        $("progress-note"),
        "Longer waits usually mean cold start or retrieval over the full corpus — not a frozen page.",
      );
    } else if (s > 15) {
      setText($("progress-label"), "Retrieving and verifying evidence…");
    }
  }, 200);
}

function metricCard(label, value, note) {
  const card = document.createElement("div");
  card.className = "metric-card";
  const l = document.createElement("div");
  l.className = "label";
  setText(l, label);
  const v = document.createElement("div");
  v.className = "value";
  setText(v, value);
  card.append(l, v);
  if (note) {
    const n = document.createElement("div");
    n.className = "note";
    setText(n, note);
    card.append(n);
  }
  return card;
}

function renderSources(sources, { supportingOnly = true } = {}) {
  const panel = $("sources-panel");
  panel.replaceChildren();
  const list = sources || [];
  const cited = supportingOnly
    ? list.filter((s) => s.quote || (s.label && /^S\d+/i.test(s.label)))
    : list;
  if (!cited.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    setText(empty, "No supporting citations in this response.");
    panel.appendChild(empty);
    return;
  }
  cited.forEach((src, idx) => {
    const card = document.createElement("div");
    card.className = "source-card";
    card.id = `source-${idx}`;
    card.dataset.chunkId = src.chunk_id || "";

    const title = document.createElement("div");
    title.className = "source-title";
    setText(title, `${src.label || `S${idx + 1}`} · ${src.title || "(untitled)"}`);

    const meta = document.createElement("div");
    meta.className = "source-meta";
    const bits = [
      src.version != null ? `version ${src.version}` : null,
      src.page != null ? `page ${src.page}` : null,
      src.heading_path || null,
      src.doc_id ? `doc ${String(src.doc_id).slice(0, 8)}…` : null,
    ].filter(Boolean);
    setText(meta, bits.join(" · "));

    const quote = document.createElement("div");
    quote.className = "source-quote";
    setText(quote, src.quote ? `Supporting excerpt: ${src.quote}` : "(no quote attached)");

    card.append(title, meta, quote);
    if (src.excerpt && src.excerpt !== src.quote) {
      const excerpt = document.createElement("pre");
      excerpt.className = "source-excerpt";
      setText(excerpt, src.excerpt);
      card.append(excerpt);
    }
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
    setText(btn, `${src.label || `S${idx + 1}`}: ${(src.title || "source").slice(0, 42)}`);
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
    head.className = "source-title";
    setText(head, `${c.subject || "?"} / ${c.attribute || "?"}`);
    const adj = document.createElement("div");
    adj.className = "muted";
    setText(adj, c.adjudication || "");
    const sides = document.createElement("pre");
    sides.className = "source-excerpt";
    setText(
      sides,
      (c.sides || [])
        .map((s) => `${s.value || ""} — ${s.quote || ""} [${s.source_label || s.chunk_id || ""}]`)
        .join("\n"),
    );
    box.append(head, adj, sides);
    panel.appendChild(box);
  });
}

function renderSteps(trace, usage, elapsedMs) {
  const panel = $("steps-panel");
  panel.replaceChildren();
  const steps = Array.isArray(trace) ? trace : [];
  if (!steps.length) {
    const li = document.createElement("li");
    setText(li, "No stage trace returned.");
    panel.appendChild(li);
  } else {
    steps.forEach((step) => {
      const li = document.createElement("li");
      const name = step.stage || step.name || step.tool || "step";
      const ms = step.latency_ms != null ? step.latency_ms : step.ms;
      const summary = step.outputs_summary || step.summary || step.detail || "";
      const main = document.createElement("div");
      setText(main, summary ? `${name}: ${summary}` : String(name));
      li.appendChild(main);
      if (ms != null) {
        const t = document.createElement("div");
        t.className = "step-time";
        setText(t, `${Number(ms).toFixed(0)} ms`);
        li.appendChild(t);
      }
      panel.appendChild(li);
    });
  }
  const metaBits = [];
  if (elapsedMs != null) metaBits.push(`wall ${ (elapsedMs / 1000).toFixed(1) }s`);
  if (usage && usage.llm_calls != null) metaBits.push(`llm_calls ${usage.llm_calls}`);
  if (usage && usage.tokens != null) metaBits.push(`tokens ${usage.tokens}`);
  if (usage && usage.synthesis_mode) metaBits.push(`synthesis ${usage.synthesis_mode}`);
  setText($("result-meta"), metaBits.join(" · "));
  setText($("trace-panel"), JSON.stringify({ trace: steps, usage: usage || {} }, null, 2));
}

function renderSamples() {
  const host = $("sample-chips");
  if (!host) return;
  host.replaceChildren();
  SAMPLES.forEach((sample) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sample-chip";
    btn.dataset.sampleId = sample.id;
    setText(btn, sample.label);
    btn.title = sample.question;
    btn.addEventListener("click", () => {
      host.querySelectorAll(".sample-chip").forEach((c) => c.classList.remove("active"));
      btn.classList.add("active");
      $("question").value = sample.question;
      $("question").focus();
    });
    host.appendChild(btn);
  });
}

async function ask() {
  const question = $("question").value.trim();
  const errBanner = $("error-banner");
  const missing = $("missing-info");
  errBanner.hidden = true;
  missing.hidden = true;
  setText(errBanner, "");
  setText(missing, "");

  if (!question) {
    setStatusBadge("insufficient");
    setText($("answer-text"), "Enter a question.");
    return;
  }

  if (askController) {
    askController.abort();
  }
  askController = new AbortController();
  const timeout = setTimeout(() => askController.abort(), QUERY_TIMEOUT_MS);

  const btn = $("ask-btn");
  btn.disabled = true;
  setStatusBadge("running");
  setText($("answer-text"), "");
  $("citation-chips").replaceChildren();
  $("sources-panel").replaceChildren();
  $("conflicts-panel").replaceChildren();
  $("steps-panel").replaceChildren();
  setText($("result-meta"), "");
  startProgress();

  const wallStart = performance.now();
  try {
    const mode = $("mode").value;
    const data = await api("/api/query", {
      method: "POST",
      json: { question, mode },
      signal: askController.signal,
    });
    const elapsed = performance.now() - wallStart;
    setStatusBadge(data.status || "insufficient");
    const answerBody =
      data.answer ||
      data.abstention_reason ||
      data.missing_information ||
      "(no answer text returned)";
    setText($("answer-text"), answerBody);
    const miss =
      data.missing_information ||
      (data.status === "insufficient" || data.status === "partial"
        ? data.abstention_reason
        : null);
    if (miss && miss !== data.answer) {
      missing.hidden = false;
      setText(missing, miss);
    }
    if (data.status === "llm_unavailable") {
      errBanner.hidden = false;
      setText(
        errBanner,
        "Language-model path unavailable (quota, rate limit, or timeout). The system did not invent an answer. Try again later or use a sample that can stay deterministic.",
      );
    }
    if (data.status === "conflicting") {
      missing.hidden = false;
      setText(
        missing,
        miss ||
          "Independent sources disagree. Review the Conflicts panel for opposing quotes.",
      );
    }
    const sources = data.sources || [];
    renderChips(sources);
    renderSources(sources);
    renderConflicts(data.conflicts || []);
    const usage = data.usage || {};
    if (data.trace && Array.isArray(data.trace)) {
      const synth = data.trace.find(
        (t) => t && (t.stage === "synthesize" || t.name === "synthesize"),
      );
      if (synth && synth.outputs_summary && !usage.synthesis_mode) {
        const m = String(synth.outputs_summary).match(/mode=(\w+)/);
        if (m) usage.synthesis_mode = m[1];
      }
    }
    renderSteps(data.trace || [], usage, elapsed);
  } catch (err) {
    setStatusBadge("insufficient");
    setText($("answer-text"), "");
    errBanner.hidden = false;
    setText(errBanner, humanError(err));
    renderSteps([], {}, performance.now() - wallStart);
  } finally {
    clearTimeout(timeout);
    clearProgress();
    btn.disabled = false;
    askController = null;
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
    setText($("docs-msg"), humanError(err));
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
    setText($("chunks-panel"), humanError(err));
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
    setText($("docs-msg"), humanError(err));
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
    setText($("docs-msg"), humanError(err));
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
    setText($("docs-msg"), humanError(err));
  }
}

async function refreshStats() {
  const cards = $("stats-cards");
  const raw = $("stats-panel");
  try {
    const data = await api("/api/stats");
    cards.replaceChildren();
    const by = data.documents_by_status || {};
    cards.append(
      metricCard("ACTIVE documents", String(by.ACTIVE ?? "—"), "Live Neon lifecycle count"),
      metricCard("Document total", String(data.document_total ?? "—"), "Includes deleted rows"),
      metricCard("Chunk rows", String(data.chunk_total ?? "—"), "Postgres chunk table"),
      metricCard("Collection", data.collection_name || "—", "Active Qdrant collection"),
    );
    Object.entries(by).forEach(([status, n]) => {
      if (status === "ACTIVE") return;
      cards.append(metricCard(status, String(n), "By lifecycle status"));
    });
    raw.hidden = true;
    setText(raw, JSON.stringify(data, null, 2));
    const active = by.ACTIVE;
    if (active != null) setText($("header-active"), Number(active).toLocaleString());
  } catch (err) {
    cards.replaceChildren();
    raw.hidden = false;
    setText(raw, humanError(err));
  }
}

function fmtPct(x) {
  if (x == null || Number.isNaN(Number(x))) return "—";
  return Number(x).toFixed(3);
}

async function refreshEval() {
  const host = $("eval-summary");
  const raw = $("eval-panel");
  try {
    const data = await api("/api/eval/runs");
    host.replaceChildren();

    const intro = document.createElement("div");
    intro.className = "eval-block";
    const h = document.createElement("h3");
    setText(h, "How to read these numbers");
    const p = document.createElement("p");
    p.className = "hint";
    setText(
      p,
      data.note ||
        "Held-out metrics from committed artifacts. Smoke-test success is not overall accuracy.",
    );
    intro.append(h, p);

    if (data.corpus_at_eval) {
      const c = document.createElement("p");
      c.className = "muted";
      setText(
        c,
        `Corpus at eval: ACTIVE ${data.corpus_at_eval.active_documents?.toLocaleString?.() || data.corpus_at_eval.active_documents}; chunks ${data.corpus_at_eval.chunk_rows?.toLocaleString?.() || data.corpus_at_eval.chunk_rows}.`,
      );
      intro.append(c);
    }

    if (data.synthesis_modes) {
      const modes = document.createElement("ul");
      modes.className = "limit-list";
      Object.entries(data.synthesis_modes).forEach(([k, v]) => {
        const li = document.createElement("li");
        setText(li, `${k}: ${v}`);
        modes.appendChild(li);
      });
      intro.append(modes);
    }
    host.appendChild(intro);

    (data.runs || []).forEach((run) => {
      const block = document.createElement("div");
      block.className = "eval-block";
      const title = document.createElement("h3");
      setText(
        title,
        `${run.headline || run.run_id} · ${run.kind || "run"}${run.status_label ? ` · ${run.status_label}` : ""}`,
      );
      block.appendChild(title);
      const meta = document.createElement("p");
      meta.className = "muted";
      setText(meta, `run_id=${run.run_id} · split=${run.split || "—"} · ${run.created_at || ""}`);
      block.appendChild(meta);

      const table = document.createElement("table");
      table.className = "eval-table";
      const thead = document.createElement("thead");
      const hr = document.createElement("tr");
      ["Config", "n scored / total", "Key metrics", "Notes"].forEach((lab) => {
        const th = document.createElement("th");
        setText(th, lab);
        hr.appendChild(th);
      });
      thead.appendChild(hr);
      table.appendChild(thead);
      const tbody = document.createElement("tbody");

      (run.configs || []).forEach((cfg) => {
        const tr = document.createElement("tr");
        const td0 = document.createElement("td");
        setText(td0, cfg.config_id || "—");
        const td1 = document.createElement("td");
        if (run.kind === "retrieval") {
          setText(
            td1,
            `${cfg.n_scored_retrieval ?? "—"} / ${cfg.n_questions_total ?? "—"} (excl ${cfg.n_excluded ?? 0})`,
          );
        } else {
          setText(
            td1,
            `${cfg.n_scored_answer ?? "—"} / ${cfg.n_questions_total ?? "—"}`,
          );
        }
        const td2 = document.createElement("td");
        if (run.kind === "retrieval") {
          setText(
            td2,
            `R@${cfg.k ?? "k"} ${fmtPct(cfg.recall_at_k)}; MRR ${fmtPct(cfg.mrr)}; all-gold ${fmtPct(cfg.all_gold_at_k)}`,
          );
        } else {
          setText(
            td2,
            `token F1 ${fmtPct(cfg.token_f1)}; cite F1 ${fmtPct(cfg.citation_f1)}; abstention ${fmtPct(cfg.correct_abstention_rate)}; contradiction ${fmtPct(cfg.contradiction_detection_rate)}`,
          );
        }
        const td3 = document.createElement("td");
        const notes = [];
        if (cfg.exclusion_note) notes.push(cfg.exclusion_note);
        if (cfg.denominator_note) notes.push(cfg.denominator_note);
        if (cfg.status_counts) {
          notes.push(
            `statuses: ${Object.entries(cfg.status_counts)
              .map(([k, v]) => `${k}=${v}`)
              .join(", ")}`,
          );
        }
        if (cfg.mean_llm_calls != null) notes.push(`mean LLM calls ${fmtPct(cfg.mean_llm_calls)}`);
        if (cfg.mean_latency_s != null) notes.push(`mean latency ${Number(cfg.mean_latency_s).toFixed(2)}s`);
        setText(td3, notes.join(" · ") || "—");
        tr.append(td0, td1, td2, td3);
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      block.appendChild(table);
      host.appendChild(block);
    });

    if (data.limitations && data.limitations.length) {
      const lim = document.createElement("div");
      lim.className = "eval-block";
      const lh = document.createElement("h3");
      setText(lh, "Known limitations");
      const ul = document.createElement("ul");
      ul.className = "limit-list";
      data.limitations.forEach((item) => {
        const li = document.createElement("li");
        setText(li, item);
        ul.appendChild(li);
      });
      lim.append(lh, ul);
      host.appendChild(lim);
    }

    if (data.generated_from) {
      const src = document.createElement("p");
      src.className = "hint";
      setText(src, `Artifacts: ${(data.generated_from || []).join("; ")}`);
      host.appendChild(src);
    }

    raw.hidden = true;
    setText(raw, JSON.stringify(data, null, 2));
  } catch (err) {
    host.replaceChildren();
    raw.hidden = false;
    setText(raw, humanError(err));
  }
}

async function refreshHealth() {
  const cards = $("health-cards");
  try {
    const health = await api("/api/health");
    const ready = await api("/api/health/ready");
    const version = await api("/api/version");
    setText($("health-panel"), JSON.stringify(health, null, 2));
    setText($("ready-panel"), JSON.stringify(ready, null, 2));
    setText($("version-panel"), JSON.stringify(version, null, 2));
    cards.replaceChildren();
    cards.append(
      metricCard("Health", health.status || "—"),
      metricCard("Ready", ready.status || "—", ready.database ? `db ${ready.database}` : ""),
      metricCard("Commit", (version.git_commit || "—").slice(0, 7), version.app || ""),
      metricCard("LLM", ready.llm_status || "—"),
    );
    if (version.git_commit) {
      setText($("header-sha"), String(version.git_commit).slice(0, 7));
    }
    if ($("header-reader")) {
      const mode = version.effective_reader_mode || "legacy";
      setText(
        $("header-reader"),
        mode === "experimental_passage_reader" ? "experimental" : "legacy",
      );
    }
    cards.append(
      metricCard(
        "Reader",
        version.effective_reader_mode || "legacy",
        version.experimental_passage_reader
          ? `bridge=${version.reader_max_bridge_rounds}`
          : "production default",
      ),
    );
  } catch (err) {
    setText($("health-panel"), humanError(err));
  }
}

async function bootstrapHeader() {
  try {
    const [stats, version] = await Promise.all([
      api("/api/stats").catch(() => null),
      api("/api/version").catch(() => null),
    ]);
    if (stats && stats.documents_by_status && stats.documents_by_status.ACTIVE != null) {
      setText($("header-active"), Number(stats.documents_by_status.ACTIVE).toLocaleString());
    }
    if (version && version.git_commit) {
      setText($("header-sha"), String(version.git_commit).slice(0, 7));
    }
    if (version && $("header-reader")) {
      const mode = version.effective_reader_mode || "legacy";
      setText(
        $("header-reader"),
        mode === "experimental_passage_reader" ? "experimental" : "legacy",
      );
    }
  } catch {
    /* header is best-effort */
  }
}

function wire() {
  renderSamples();
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
  $("question").addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
      ev.preventDefault();
      ask();
    }
  });
  $("save-token").addEventListener("click", () => {
    adminToken = $("admin-token").value;
    setText($("token-state"), adminToken ? "set (memory)" : "not set");
  });
  $("upload-btn").addEventListener("click", uploadDoc);
  $("refresh-stats").addEventListener("click", refreshStats);
  $("refresh-eval").addEventListener("click", refreshEval);
  $("refresh-health").addEventListener("click", refreshHealth);
  setStatusBadge("idle");
  bootstrapHeader();
}

wire();
