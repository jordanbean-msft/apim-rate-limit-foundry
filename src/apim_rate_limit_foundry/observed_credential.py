"""Credential adapter that exposes dependency timing but not credential material."""

from types import TracebackType
from typing import Any, cast

from azure.core.credentials import AccessToken, AccessTokenInfo, TokenRequestOptions
from azure.core.credentials_async import AsyncSupportsTokenInfo, AsyncTokenCredential

from apim_rate_limit_foundry.telemetry import dependency_span


class ObservedCredential:
    """Observe token acquisition without exporting scopes, tokens or identity details."""

    def __init__(self, credential: AsyncTokenCredential) -> None:
        self.credential = credential

    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        """Delegate token acquisition unchanged inside a sanitized dependency span."""
        with dependency_span("managed-identity", "get_token"):
            return await self.credential.get_token(*scopes, **kwargs)

    async def get_token_info(
        self, *scopes: str, options: TokenRequestOptions | None = None
    ) -> AccessTokenInfo:
        """Support Azure SDK token-info calls, adapting older credential interfaces.

        The fallback preserves token/expiry rather than exporting either value.
        """
        with dependency_span("managed-identity", "get_token_info"):
            if hasattr(self.credential, "get_token_info"):
                return await cast(AsyncSupportsTokenInfo, self.credential).get_token_info(
                    *scopes, options=options
                )
            token = await self.credential.get_token(*scopes, **(options or {}))
            return AccessTokenInfo(token.token, token.expires_on)

    async def close(self) -> None:
        """Close the wrapped credential; runtime composition determines ownership."""
        await self.credential.close()

    async def __aenter__(self) -> "ObservedCredential":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        await self.close()
