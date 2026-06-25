-- 004_semantic_cache_index — HNSW cosine index for fast ANN search + btree for hash lookups.
--
-- The HNSW index makes approximate nearest-neighbor cosine search sub-linear at scale;
-- without it every lookup does a full sequential scan of the semantic_cache table.
-- The btree index on request_hash accelerates ON CONFLICT (request_hash) DO NOTHING
-- in store() and any future point-lookup by hash.

CREATE INDEX IF NOT EXISTS idx_semantic_cache_embedding
    ON semantic_cache USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_semantic_cache_request_hash
    ON semantic_cache (request_hash);
