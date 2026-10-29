# Chunking comparison (DOC-6)

Generated: 2026-10-29T04:12:15.712299+00:00

**Winner:** `fixed_window`

**Why:** Higher span-level Recall@5=1.0 and MRR=1.0 on synthetic gold markers; tie on recall, fewer/equal chunks (118 vs 153)

## Chunk stats

| Strategy | Docs | Chunks | Avg chunks/doc | Avg tokens | Latency s |
| --- | ---: | ---: | ---: | ---: | ---: |
| fixed_window | 105 | 118 | 1.124 | 87.92 | 0.007 |
| structure_aware | 105 | 153 | 1.457 | 65.41 | 0.0154 |

## Span metrics (synthetic gold)

| Strategy | Recall@K | MRR |
| --- | ---: | ---: |
| fixed_window | 1.0 | 1.0 |
| structure_aware | 1.0 | 1.0 |

## Hotpot lexical proxy

| Strategy | Recall@K | MRR |
| --- | ---: | ---: |
| fixed_window | 1.0 | 0.995 |
| structure_aware | 1.0 | 0.995 |
