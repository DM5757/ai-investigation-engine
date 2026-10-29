# Database design (Phase 2)

Postgres (Neon) is the source of truth for document identity, versions, chunks,
and SimHash LSH bands. Qdrant holds derived dense/sparse vectors filtered by
`doc_id` + `version`. Retrieval must ignore points whose `version` is not equal
to `documents.active_version`.

## Entity relationship

```mermaid
erDiagram
    documents ||--o{ document_versions : has
    documents ||--o{ chunks : has
    documents ||--o{ simhash_bands : has
    documents ||--o| documents : near_duplicate_of

    documents {
        string id PK
        string external_key
        string filename
        string title
        string content_hash
        string simhash
        string status
        int active_version
        string near_duplicate_of FK
        json metadata
        string error_message
        datetime created_at
        datetime updated_at
        datetime deleted_at
    }

    document_versions {
        string id PK
        string document_id FK
        int version
        string content_hash
        text text
        string title
        string simhash
        json metadata
        datetime created_at
    }

    chunks {
        string id PK
        string document_id FK
        int version
        int chunk_index
        string content_hash
        text text
        int char_start
        int char_end
        string heading_path
        int page
        int token_count
        string strategy
        string qdrant_point_id
        json metadata
        datetime created_at
    }

    simhash_bands {
        string id PK
        string document_id FK
        int band_index
        int band_value
        string simhash
        string content_hash
    }

    index_stats {
        string id PK
        string collection_name
        int document_count
        int chunk_count
        datetime last_reconcile_at
        json metadata
        datetime updated_at
    }

    health_probes {
        string id PK
        text note
        datetime created_at
    }
```

## Lifecycle statuses

`PENDING` → `INDEXING` → `ACTIVE`, plus `FAILED`, `DELETING`, `DELETED`.

- Soft delete sets `DELETED` and frees `external_key` (partial unique index
  excludes deleted rows).
- Exact duplicates share `content_hash` and are not indexed twice.
- Near duplicates (Hamming ≤ threshold via 4×16-bit bands) are indexed and
  flagged with `near_duplicate_of`.
