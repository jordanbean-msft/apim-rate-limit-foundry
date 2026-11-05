from pydantic import model_validator

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Amount


class Usage(Contract):
    input_tokens: Amount = 0
    output_tokens: Amount = 0
    cached_input_tokens: Amount = 0
    pages: Amount = 0
    text_records: Amount = 0
    requests: Amount = 1

    @model_validator(mode="after")
    def cached_subset(self) -> "Usage":
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("Cached tokens must be a subset of input tokens")
        return self
