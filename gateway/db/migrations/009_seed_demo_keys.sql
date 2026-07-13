-- 009_seed_demo_keys — public demo key and internal benchmark key for the live
-- Fly.io instance. Never edit 005_seed_api_key.sql; keys are additive.
--
-- Raw key value: "demo-key"  — shared publicly in README as the live-demo credential.
-- hard_limit_cents = 1000 ($10.00) — the public spend cap. hard_limit_cents being
-- non-NULL is what turns enforcement on (see gateway/budgets/enforce.py); there is
-- no separate boolean flag.
-- soft_limit_cents = 800  ($8.00) — warns before the hard block.
INSERT INTO api_keys (key_hash, name, soft_limit_cents, hard_limit_cents)
VALUES (
    encode(sha256('demo-key'::bytea), 'hex'),
    'demo-key',
    800,
    1000
)
ON CONFLICT (key_hash) DO NOTHING;

-- Raw key value: "bench-key" — used only for the S2 final benchmark run against
-- this deployed instance, kept separate from demo-key so bench traffic can't burn
-- the public key's budget.
-- hard_limit_cents = 2500 ($25.00).
INSERT INTO api_keys (key_hash, name, soft_limit_cents, hard_limit_cents)
VALUES (
    encode(sha256('bench-key'::bytea), 'hex'),
    'bench-key',
    2000,
    2500
)
ON CONFLICT (key_hash) DO NOTHING;
