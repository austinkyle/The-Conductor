"""Pure cost math: convert token counts + model prices to cost in cents.

No I/O. Prices come from the DB (models.input_price_per_mtok / output_price_per_mtok),
stored as USD per 1,000,000 tokens. Result is numeric(12,4) cents.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from db.models import Model

_log = logging.getLogger(__name__)

_MILLION = Decimal("1_000_000")
_HUNDRED = Decimal("100")


def cost_cents(model: Model, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Compute cost in cents (USD×100), numeric(12,4) precision.

    A None price for either side contributes 0 (logged once at debug — usually means the
    model row was seeded without pricing, which is fine for budget-untracked models).
    """
    if model.input_price_per_mtok is None:
        _log.debug("model %s has no input price; treating as 0", model.alias)
        input_cost = Decimal("0")
    else:
        input_cost = Decimal(prompt_tokens) * model.input_price_per_mtok / _MILLION

    if model.output_price_per_mtok is None:
        _log.debug("model %s has no output price; treating as 0", model.alias)
        output_cost = Decimal("0")
    else:
        output_cost = Decimal(completion_tokens) * model.output_price_per_mtok / _MILLION

    return ((input_cost + output_cost) * _HUNDRED).quantize(Decimal("0.0001"))
