from typing import Annotated

from pydantic import Field, model_validator

from apim_rate_limit_foundry.models.contract import Contract

TokenCount = Annotated[int, Field(strict=True, ge=0, le=9_000_000_000_000)]


class UsageCounts(Contract):
    """Normalized provider token counts for one priced request.

    Cached and cache-write tokens are disjoint subsets of input tokens, so
    input - cached - cache_write is the ordinary uncached input. Output already
    includes reasoning tokens and is never split further.
    """

    input_tokens: TokenCount
    cached_input_tokens: TokenCount = 0
    cache_write_tokens: TokenCount = 0
    output_tokens: TokenCount

    @model_validator(mode="after")
    def subsets_fit_input(self) -> "UsageCounts":
        """Reject cache subsets that together exceed total input."""
        if self.cached_input_tokens + self.cache_write_tokens > self.input_tokens:
            raise ValueError("Cached and cache-write input tokens cannot exceed total input tokens")
        return self

    @property
    def uncached_input_tokens(self) -> int:
        """Input charged at the ordinary input rate."""
        return self.input_tokens - self.cached_input_tokens - self.cache_write_tokens
