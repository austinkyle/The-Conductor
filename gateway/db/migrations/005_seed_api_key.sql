-- 005_seed_api_key — insert one demo API key for budget enforcement testing.
--
-- Raw key value: "dev-key"  (documented in README quickstart / DECISIONS.md only)
-- sha256("dev-key") = 7e9f8fd111802be56c379d597842e29b2cebd35ff2133d431a49fa556a18704e
-- Limits are intentionally low to make the hard-block easy to demo.
-- hard_limit_cents = 100  ($1.00) — triggers 402 quickly in testing
-- soft_limit_cents = 10   ($0.10) — logs a warning before the block

INSERT INTO api_keys (key_hash, name, soft_limit_cents, hard_limit_cents)
VALUES (
    encode(sha256('dev-key'::bytea), 'hex'),
    'dev-key',
    10,
    100
)
ON CONFLICT (key_hash) DO NOTHING;
