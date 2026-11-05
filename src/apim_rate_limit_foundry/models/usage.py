from pydantic import Field, model_validator

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Amount


class Usage(Contract):
    input_tokens: Amount = Field(
        default=0,
        description="Total input, including cache reads and both cache-write TTL classes.",
    )
    output_tokens: Amount = 0
    cached_input_tokens: Amount = Field(default=0, description="Cache-read subset of total input.")
    pages: Amount = 0
    text_records: Amount = 0
    requests: Amount = 1
    cache_write_input_tokens_5m: Amount = 0
    cache_write_input_tokens_1h: Amount = 0

    @model_validator(mode="after")
    def cached_subset(self) -> "Usage":
        if (
            self.cached_input_tokens
            + self.cache_write_input_tokens_5m
            + self.cache_write_input_tokens_1h
            > self.input_tokens
        ):
            raise ValueError("Cached tokens must be a subset of input tokens")
        return self
