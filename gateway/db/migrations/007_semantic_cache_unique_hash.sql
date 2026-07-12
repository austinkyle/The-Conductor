-- 007_semantic_cache_unique_hash — make request_hash actually unique.
--
-- 004's plain btree index on request_hash cannot satisfy `ON CONFLICT (request_hash)
-- DO NOTHING` in semantic.store() — Postgres requires a unique constraint or unique
-- index on the conflict target, and a non-unique btree doesn't count. Every store()
-- call has been raising InvalidColumnReferenceError since 004 shipped. Replace it
-- with a unique index (de-duplicating any existing rows first, since concurrent
-- writes may have inserted duplicate hashes while ON CONFLICT was silently broken).

DELETE FROM semantic_cache a
USING semantic_cache b
WHERE a.request_hash = b.request_hash AND a.id > b.id;

DROP INDEX IF EXISTS idx_semantic_cache_request_hash;

CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_cache_request_hash
    ON semantic_cache (request_hash);
