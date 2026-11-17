"""One relayed provider response."""

from collections.abc import AsyncIterator
from typing import NamedTuple


class UpstreamResponse(NamedTuple):
    """Status, media type, body iterator and allowlisted headers to send to the caller."""

    status: int
    media_type: str
    chunks: AsyncIterator[bytes]
    headers: dict[str, str]
