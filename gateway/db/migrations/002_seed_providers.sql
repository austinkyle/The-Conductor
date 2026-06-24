-- 002_seed_providers — the two providers and a starter model per provider.
-- auth_ref names the env var holding the key; the secret itself never lives here.
-- Phase 1 resolves a request's `model` directly against models.alias (alias =
-- provider_model for now). Phase 3 turns alias into logical names ("smart"/"fast").

INSERT INTO providers (name, base_url, auth_ref) VALUES
    ('openai',    'https://api.openai.com/v1',  'OPENAI_API_KEY'),
    ('anthropic', 'https://api.anthropic.com/v1', 'ANTHROPIC_API_KEY');

-- Prices are USD per 1,000,000 tokens (see 001_init). Kept in the DB, not hardcoded
-- in Python — model strings and pricing drift, the table is the source of truth.
INSERT INTO models (alias, provider_id, provider_model, input_price_per_mtok, output_price_per_mtok)
SELECT 'gpt-4o-mini', p.id, 'gpt-4o-mini', 0.15, 0.60
FROM providers p WHERE p.name = 'openai';

INSERT INTO models (alias, provider_id, provider_model, input_price_per_mtok, output_price_per_mtok)
SELECT 'claude-3-5-sonnet-latest', p.id, 'claude-3-5-sonnet-latest', 3.00, 15.00
FROM providers p WHERE p.name = 'anthropic';
