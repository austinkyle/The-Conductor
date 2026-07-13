-- 008_update_anthropic_models — the models seeded in 002/003 (claude-3-5-sonnet-latest,
-- claude-3-5-haiku-latest) are retired and 404 live against the real Anthropic API.
-- Never edit an applied migration (002/003 stay as historical record) — update in place here.

UPDATE models
SET alias = 'claude-sonnet-5',
    provider_model = 'claude-sonnet-5',
    input_price_per_mtok = 3.00,
    output_price_per_mtok = 15.00
WHERE alias = 'claude-3-5-sonnet-latest'
  AND provider_model = 'claude-3-5-sonnet-latest';

UPDATE models
SET provider_model = 'claude-sonnet-5',
    input_price_per_mtok = 3.00,
    output_price_per_mtok = 15.00
WHERE alias = 'smart'
  AND provider_model = 'claude-3-5-sonnet-latest';

UPDATE models
SET provider_model = 'claude-haiku-4-5-20251001',
    input_price_per_mtok = 1.00,
    output_price_per_mtok = 5.00
WHERE alias = 'fast'
  AND provider_model = 'claude-3-5-haiku-latest';
