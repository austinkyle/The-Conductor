-- 001_init — five-table data model + pgvector.
-- Secrets are never stored here: providers.auth_ref names the env var holding the
-- provider key; api_keys stores a hash of the gateway-issued caller key, not the key.

CREATE EXTENSION IF NOT EXISTS vector;

-- Caller keys issued by the gateway. Stored hashed. Optional per-key budgets.
CREATE TABLE IF NOT EXISTS api_keys (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key_hash         text   NOT NULL UNIQUE,
    name             text   NOT NULL,
    soft_limit_cents bigint,
    hard_limit_cents bigint,
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- Upstream providers. auth_ref = name of the env var holding the secret.
CREATE TABLE IF NOT EXISTS providers (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       text NOT NULL UNIQUE,
    base_url   text NOT NULL,
    auth_ref   text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Logical model aliases -> concrete provider model, with pricing for cost accounting.
-- Prices are USD per 1,000,000 tokens.
CREATE TABLE IF NOT EXISTS models (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alias                  text NOT NULL,
    provider_id            bigint NOT NULL REFERENCES providers(id),
    provider_model         text NOT NULL,
    input_price_per_mtok   numeric(12, 6),
    output_price_per_mtok  numeric(12, 6),
    created_at             timestamptz NOT NULL DEFAULT now()
);

-- The request spine: one row per proxied call, written even on failure.
CREATE TABLE IF NOT EXISTS requests (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    api_key_id         bigint REFERENCES api_keys(id),
    requested_model    text,
    served_provider_id bigint REFERENCES providers(id),
    served_model       text,
    status             text NOT NULL,
    error_class        text,
    fallback_depth     int  NOT NULL DEFAULT 0,
    cache_status       text,
    prompt_tokens      int,
    completion_tokens  int,
    total_tokens       int,
    cost_cents         numeric(12, 4),
    latency_ms         int,
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- Semantic cache. embedding dimension matches the default OpenAI embedding model.
CREATE TABLE IF NOT EXISTS semantic_cache (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_hash  text NOT NULL,
    embedding     vector(1536) NOT NULL,
    response_body jsonb NOT NULL,
    model         text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
