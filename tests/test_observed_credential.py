from types import SimpleNamespace
from unittest.mock import AsyncMock

from azure.core.credentials import AccessToken, AccessTokenInfo

from apim_rate_limit_foundry.observed_credential import ObservedCredential


class LegacyCredential:
    """Credential exposing only get_token, like older Azure credential types."""

    def __init__(self) -> None:
        self.get_token = AsyncMock(return_value=AccessToken("legacy-token", 123))
        self.close = AsyncMock()


async def test_tokens_are_delegated_unchanged() -> None:
    inner = LegacyCredential()

    token = await ObservedCredential(inner).get_token("scope/.default", tenant_id="t")  # type: ignore[arg-type]

    assert token == AccessToken("legacy-token", 123)
    inner.get_token.assert_awaited_once_with("scope/.default", tenant_id="t")


async def test_token_info_uses_the_wrapped_credentials_support_when_present() -> None:
    info = AccessTokenInfo("native-token", 456)
    inner = SimpleNamespace(get_token_info=AsyncMock(return_value=info), close=AsyncMock())

    result = await ObservedCredential(inner).get_token_info("scope/.default")  # type: ignore[arg-type]

    assert result is info
    inner.get_token_info.assert_awaited_once_with("scope/.default", options=None)


async def test_token_info_is_adapted_from_legacy_credentials() -> None:
    inner = LegacyCredential()

    result = await ObservedCredential(inner).get_token_info(  # type: ignore[arg-type]
        "scope/.default", options={"tenant_id": "t"}
    )

    assert (result.token, result.expires_on) == ("legacy-token", 123)
    inner.get_token.assert_awaited_once_with("scope/.default", tenant_id="t")


async def test_leaving_the_context_closes_the_wrapped_credential() -> None:
    inner = LegacyCredential()

    async with ObservedCredential(inner) as observed:  # type: ignore[arg-type]
        assert isinstance(observed, ObservedCredential)

    inner.close.assert_awaited_once()
