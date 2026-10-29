# Free-tier verification notes

**Verification date:** 28 October 2026  
**Constraint:** infrastructure must be genuinely free (no paid subscriptions). LLM API free quotas are acceptable and documented separately.  
**Owner note:** Hugging Face Gradio/Docker Spaces require a paid plan on this account; confirmed against current Hub docs.

Sources were checked via official documentation pages on this date. Figures can change; re-verify before submission.

---

## 1. Application hosting comparison

| Provider | Verified free resources | Inactivity / sleep | Local disk | Docker / FastAPI | Embedding fit (`bge-small` ONNX ~280–400 MB RSS) | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| **Hugging Face Spaces (Docker/Gradio)** | CPU Basic is $0/hour **but** creating Gradio/Docker Spaces requires PRO (personal) or Team/Enterprise (org). Static Spaces remain free. ZeroGPU carve-out is Gradio-only (not Docker). | N/A for our case | Ephemeral | Docker yes | 16 GB RAM would be ideal | **Rejected** — paid subscription required |
| **Render Free web service** | **0.1 CPU / 512 MB RAM**; 750 Free instance-hours/workspace/month; Docker or native Python; **no paid plan required** for Free web services | Spins down after **15 min** idle; ~1 min cold start (**assignment-acceptable** if documented) | Ephemeral; Free services **cannot** attach persistent disks | Yes | 512 MB: **must measure**; local BGE-small may OOM — contingency: remote/smaller embedder | **Primary (revised 28 Oct 2026)** |
| **Northflank Sandbox** | Up to **$20/mo** free; `nf-compute-50` ≈ $12/mo. Billing docs require a **payment method** before creating resources | Always on | Ephemeral | Yes | 1 GB would fit embeddings more easily | **Rejected for this account** — owner will not provide a card (§1.1) |
| **Koyeb Free Instance** | **0.1 vCPU / 512 MB RAM / 2 GB SSD**; 1 free web service (FRA or WAS) | Scales to zero after **1 hour** idle (cannot disable) | No Volumes on Free | Yes | Same 512 MB OOM risk | Fallback only with embedding offload |
| **Oracle Cloud Always Free** | Ampere A1: **2 OCPU / 12 GB RAM** total (reduced from 4/24 in Jun 2026); 2× AMD Micro 1 GB; **200 GB** block volume | Idle reclaim risk: 7-day window if CPU/network/(A1 memory) util &lt; 20% | Persistent block volume | Yes (prefer multi-arch / ARM images) | Excellent RAM headroom | **Strong fallback** if Northflank account/limits fail |
| **Google Cloud Run (Always Free)** | Request-based: 2M req, 180k vCPU-s, 360k GiB-s/month | Scale to zero | Ephemeral | Container yes | Can request ≥1 GiB; free allowance is metered | Rejected as primary: **billing account required**; overage risk if always-warm |
| **Railway Free** | $1/mo credit; max **0.5 GB RAM**/service | Credit exhaustion stops workloads | 0.5 GB volume on Free | Yes | Insufficient for always-on + model | Rejected |
| **Fly.io** | **No free tier** for new orgs (trial only: 2 machine-hours / 7 days) | N/A | Paid volumes | Yes | N/A | Rejected |
| **Vercel** | Serverless / edge oriented | Cold starts | N/A | Not suited to long-lived ONNX Python process | Poor fit | Rejected for APP-1 shape |

### Selected app host (revised 28 Oct 2026)

**Primary: Render Free web service (Docker or native Python).**

| Constraint | Verified value | Assignment impact |
| --- | --- | --- |
| RAM / CPU | 512 MB / 0.1 CPU | Embedding strategy gated on Phase 1 RSS benchmarks |
| Sleep | After **15 minutes** without traffic; ~1 minute wake | Allowed by assignment §4 if documented; mitigate with GitHub Actions keep-alive |
| Disk | Ephemeral; no persistent disks on Free | All state in **Neon + Qdrant** |
| Hours | 750 Free instance-hours/workspace/month | Sleeping does not consume hours; keep-alive wakes consume them |
| Payment | Free web service; no paid plan required | Owner rejected Northflank due to card requirement |

Reasons:

1. Genuinely free without payment information (owner constraint).
2. Public URL, Docker/FastAPI support, assignment explicitly lists Render and allows sleep.
3. Persistence via Neon + Qdrant (unchanged).
4. Embedding path **not finalized** until local RSS/latency tests pass under a 512 MB budget.

**Fallback order if Render Free fails (OOM, hours exhausted, account issues):**

1. Koyeb Free (same 512 MB class; 1-hour scale-to-zero) with the same measured embedding contingency.
2. Oracle Always Free A1 (more RAM; card often required for tenancy signup — only if owner accepts Oracle’s account rules).

### 1.1 Northflank — rejected for this account

Owner report (28 Oct 2026): `NORTHFLANK_BLOCKED` — account requires a payment card; owner will not provide payment information.

| Source | Claim |
| --- | --- |
| [northflank.com/pricing](https://northflank.com/pricing) | Marketing: “No card needed” |
| [Billing docs](https://northflank.com/docs/v1/application/billing/pricing-on-northflank.md) | Payment method required to create resources |
| Owner account | Card required in practice |

Northflank remains documented as a rejected alternative, not an active host.

---

## 2. Managed databases / indexes

| Service | Free resources | Inactivity | Persistence | Fit for ≥50k records | Notes |
| --- | --- | --- | --- | --- | --- |
| **Qdrant Cloud Free** | 1 node: **0.5 vCPU / 1 GB RAM / 4 GB disk**; no card | Suspend after **1 week** unused; **delete after 4 weeks** if not reactivated | Managed persistent | ~1M×768-d claimed; our 384-d + sparse + short Hotpot payloads should fit if `on_disk` tuned and footprint measured | Keep-alive required |
| **Neon Free Postgres** | **1 GB storage/project** (raised Oct 2026 from 0.5 GB); 100 projects; **100 CU-hours**/project/month; autoscaling up to 2 CU | Scale to zero after **5 min** (cannot disable on Free) | Persistent storage | Store document text once + chunk offsets (not duplicated full chunk text in PG); expect tens of MB for Hotpot subset — measure | Preferred metadata SoT |
| **Supabase Free** | **500 MB** DB; 2 active projects | Pause after **~1 week** low activity | Persistent until pause/restore | Tighter than Neon | Fallback Postgres |
| **Render Free Postgres** | 1 GB | **Expires / deleted 30 days after creation** | Not durable for assignment lifetime | Unsuitable | Rejected for DEP-3 |
| **Koyeb Free Postgres** | 1 GB storage, **5 hours active compute/month** | Sleeps after idle | Storage retained but almost never “on” | Unsuitable for demo | Rejected |

### Selected stores

- **Postgres (source of truth):** Neon Free.
- **Vector index (derived):** Qdrant Cloud Free (dense named vector + sparse named vector with IDF modifier).
- App local disk treated as **ephemeral** on all PaaS options; persistence proven via Neon + Qdrant after restart.

---

## 3. Embedding model

| Item | Verified fact | Source |
| --- | --- | --- |
| Model | `BAAI/bge-small-en-v1.5` | Master plan D5; fastembed supported list |
| Dims / disk | 384-d; ~**0.067 GB** ONNX | [fastembed Supported Models](https://qdrant.github.io/fastembed/examples/Supported_Models/) |
| Runtime RAM (measured 28 Oct 2026) | Windows process RSS **268 MB**; Docker Linux `--memory=512m` peak **284.6 MiB**, no OOM; embed load **~440 ms**; query p50 **~6.3 ms** | `embedding_rss_bench.json`, `container_512m_bench.json` |
| Hosted free alternative | Qdrant Cloud Inference free dense models: `sentence-transformers/all-minilm-l6-v2`, `intfloat/multilingual-e5-small`; free sparse `qdrant/bm25` | [Qdrant Inference docs](https://qdrant.tech/documentation/cloud/inference/) |

**Strategy under free hosting:**

1. **Selected for Render Free (provisionally):** local `fastembed` + `BAAI/bge-small-en-v1.5`, model baked in image.
2. **Phase 1 gates passed:** Windows RSS + Docker `--memory=512m` bench (`container_512m_bench.json`: peak **284.6 MiB**, `oom_killed=false`).
3. **Fallback retained if Render reality differs:** Qdrant Cloud Inference free dense models or smaller encoder — only after measured failure. Custom BM25 + custom reranker remain mandatory.

---

## 4. LLM free tiers (usage, not infrastructure)

| Provider | Status (28 Oct 2026) | Limits (org-level summary; confirm in console) | Tool calling |
| --- | --- | --- | --- |
| **Groq** | Free tier exists; **Llama 3.1 8B / Llama 3.3 70B removed** from free/Developer on 16 Aug 2026 | Example for `openai/gpt-oss-120b` / `openai/gpt-oss-20b` / `qwen/qwen3.8-27b`: **30 RPM, 1K RPD, 8K TPM, 200K TPD** ([rate limits](https://console.groq.com/docs/rate-limits)) | Supported on current chat models; verify chosen model ID |
| **Google Gemini (AI Studio)** | Free tier still listed (free I/O tokens; data may train products) | Exact RPM/TPM/RPD **per project in AI Studio**; historically Flash-class ~10 RPM / hundreds RPD — **do not hardcode**; read live limits | Prefer current Flash / Flash-Lite IDs (`gemini-3.5-flash-lite`, `gemini-3.8-flash`, etc.); 2.5 family restricted for new users |

**Primary LLM (revised from master prompt):** Groq `openai/gpt-oss-120b` (or `qwen/qwen3.8-27b` if tool-calling quality is better in smoke tests).  
**Secondary / fallback:** Gemini Flash-class free model ID chosen at implementation time from AI Studio.

### 4.1 Groq `openai/gpt-oss-120b` capability check (docs, 28 Oct 2026)

| Capability | Official status | Source |
| --- | --- | --- |
| Local tool / function calling | **Yes** (all Groq-hosted models; table marks local tool use ✅). Parallel tool use: **No** for gpt-oss-120b | [Tool Use Overview](https://console.groq.com/docs/tool-use/overview) |
| JSON Object Mode | **Yes** | Model page capabilities |
| JSON Schema structured outputs | **Yes**, including `strict: true` constrained decoding | [Structured Outputs](https://console.groq.com/docs/structured-outputs) |
| Tools + structured outputs together | **Not supported** in one call — use separate calls or tool-arg schemas | Same page |
| Free-tier quotas (summary) | 30 RPM, 1K RPD, 8K TPM, 200K TPD (org-level; confirm in console) | [Rate Limits](https://console.groq.com/docs/rate-limits) |

**Investigation-engine implication:** tool-calling workflow is supported; for strict Pydantic schemas prefer tool-argument JSON or a follow-up structured call (do not combine `tools` + `response_format` json_schema in one request). **Live smoke against the owner’s Groq key and Limits page is still required** before claiming account quotas.

Eval harness must throttle, cache (Postgres `llm_cache`), checkpoint, and possibly span multiple days within 1K RPD / 200K TPD.

---

## 5. Corpus storage estimate (pre-measure; not evidence)

Assumptions for **≥55,000** HotpotQA paragraph records + ~100 synthetic docs (orders of magnitude smaller):

| Component | Formula / assumption | Estimate |
| --- | --- | --- |
| Avg normalised paragraph text | ~400–800 bytes UTF-8 | use **600 B** mid |
| Neon `documents.text` + row overhead | 55k × (600 B text + ~200 B meta/indexes) | **~45 MB** |
| Neon `chunks` (offsets only, ~1–2 chunks/doc) | ~70k × ~150 B | **~10 MB** |
| Neon versions / bands / index_stats / llm_cache | small + eval cache growth | **~5–50 MB** (cache-dominated) |
| **Neon total (order of magnitude)** | | **~60–150 MB** vs **1 GB** free cap → **likely OK**; prove with `pg_database_size` after ingest |
| Dense vectors | 70k × 384 × 4 B | **~103 MB** |
| Sparse BM25 | highly variable; budget **~50–150 MB** | |
| Qdrant payload (text + meta) | 70k × ~700 B | **~50 MB** |
| HNSW / indexes / overhead | often 1–2× vector RAM if in-memory | use **`on_disk`** vectors/payload as needed |
| **Qdrant disk (order of magnitude)** | | **~0.3–1.0 GB** vs **4 GB** free disk → **plausible** |
| **Qdrant RAM (order of magnitude)** | with on-disk segments | target **&lt;1 GB**; **must measure** — do not assume |

**Hard rule:** no README/report claim of “fits free tier” until `docs/evidence/dataset_counts.json` (and Qdrant/Neon size fields) are produced by scripts against real stores. If measurement exceeds caps: reduce payload text in Qdrant (retrieve text from Postgres by chunk id), enable on-disk, shrink llm_cache, or reduce synthetic bulk — **never** silently pay for larger clusters.

## 6. Dataset access (HotpotQA)

| Item | Finding |
| --- | --- |
| Assignment attachment | **None present** in the workspace; assignment lists public datasets |
| Source | [`hotpotqa/hotpot_qa`](https://huggingface.co/datasets/hotpotqa/hotpot_qa) + [hotpotqa.github.io](https://hotpotqa.github.io/) |
| License | **CC BY-SA 4.0** (attribution + share-alike) |
| Config | Use **`distractor`** (train ~90,447 + validation ~7,405 questions) |
| ≥50k records | Feasible: extract unique context paragraphs as independent records until ≥55k unique `hotpotqa:<title>` keys |
| Gating | Public dataset; no special access key observed for standard download |
| Storage impact | Short Wikipedia paragraphs → Neon 1 GB and Qdrant 4 GB disk are plausible; **must measure** after ingest (`docs/evidence/dataset_counts.json`) |

Synthetic enterprise corpus (multi-format, contradictions, injections) remains Part B as in the master plan.

---

## 7. Keep-alive / anti-suspension plan

| Target | Risk | Mitigation |
| --- | --- | --- |
| Render Free app | Sleep after 15 min idle; ~1 min cold start | GitHub Actions keep-alive ping `/api/health`; document cold start in DEPLOYMENT.md |
| Neon | Cold start after 5 min | Accept latency; ping from keep-alive wakes compute |
| Qdrant Free | Suspend 1 week / delete 4 weeks | Scheduled ping that performs a cheap authenticated API call; document reactivation steps |
| Oracle (if used) | Idle reclaim | Light cron load + consider converting tenancy to PAYG while staying inside Always Free quotas (still $0 if within limits) |

---

## 8. Cost table (target architecture)

| Component | Monthly infrastructure cost | Notes |
| --- | --- | --- |
| Render Free web service | **$0** | 512 MB; sleep; 750 instance-hours; no paid plan |
| Neon Free | **$0** | Storage + CU-hour caps |
| Qdrant Cloud Free | **$0** | Cluster size fixed |
| Groq / Gemini | **$0** within free quotas | Eval may be quota-bound, not dollar-bound |
| **Total** | **$0** | If Render Free is insufficient after measured embedding contingency, evaluate Koyeb Free or Oracle — do **not** upgrade to paid Render |

---

## 9. Human actions required for free tiers

See the consolidated **HUMAN ACTION REQUIRED** block in `docs/PROGRESS.md`. Accounts: **Render**, Neon, Qdrant Cloud, Groq, Google AI Studio, GitHub (repo + Actions). Hugging Face account optional for dataset download via `datasets` (no Spaces needed). Northflank rejected for this account.
