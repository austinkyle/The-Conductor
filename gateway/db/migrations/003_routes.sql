-- 003_routes — priority column for ordered fallback chains; seed "smart" and "fast" aliases.
-- Model strings and pricing stay in the DB, never hardcoded in Python — they drift.

ALTER TABLE models ADD COLUMN IF NOT EXISTS priority int NOT NULL DEFAULT 0;

-- Route "smart": primary Anthropic (claude-3-5-sonnet-latest), fallback OpenAI (gpt-4o).
INSERT INTO models (alias, provider_id, provider_model, input_price_per_mtok, output_price_per_mtok, priority)
SELECT 'smart', p.id, 'claude-3-5-sonnet-latest', 3.00, 15.00, 0
FROM providers p WHERE p.name = 'anthropic';

INSERT INTO models (alias, provider_id, provider_model, input_price_per_mtok, output_price_per_mtok, priority)
SELECT 'smart', p.id, 'gpt-4o', 2.50, 10.00, 1
FROM providers p WHERE p.name = 'openai';

-- Route "fast": primary OpenAI (gpt-4o-mini), fallback Anthropic (claude-3-5-haiku-latest).
INSERT INTO models (alias, provider_id, provider_model, input_price_per_mtok, output_price_per_mtok, priority)
SELECT 'fast', p.id, 'gpt-4o-mini', 0.15, 0.60, 0
FROM providers p WHERE p.name = 'openai';

INSERT INTO models (alias, provider_id, provider_model, input_price_per_mtok, output_price_per_mtok, priority)
SELECT 'fast', p.id, 'claude-3-5-haiku-latest', 0.80, 4.00, 1
FROM providers p WHERE p.name = 'anthropic';
