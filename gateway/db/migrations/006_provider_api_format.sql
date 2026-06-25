-- 006_provider_api_format — add api_format to providers so adapter selection
-- is decoupled from the provider name. Defaults to 'openai' for existing rows.
ALTER TABLE providers ADD COLUMN IF NOT EXISTS api_format VARCHAR(32) NOT NULL DEFAULT 'openai';
UPDATE providers SET api_format = 'anthropic' WHERE name = 'anthropic';
