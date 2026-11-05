from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier, Money, Service


class Price(Contract):
    id: Identifier
    service: Service
    model: Identifier
    version: Identifier
    input_per_million: Money | None = None
    output_per_million: Money | None = None
    cached_input_per_million: Money | None = None
    per_page: Money | None = None
    per_text_record: Money | None = None
    per_request: Money | None = None
    cache_write_5m_per_million: Money | None = None
    cache_write_1h_per_million: Money | None = None
