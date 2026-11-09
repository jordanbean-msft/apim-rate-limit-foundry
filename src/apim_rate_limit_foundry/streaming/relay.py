import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextvars import Token
from typing import Any, Literal

import aiohttp
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import AzureError
from redis.exceptions import RedisError

from apim_rate_limit_foundry.accounting import digest
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import USAGE_COLLECTION, Engine
from apim_rate_limit_foundry.models.budget_check import UsageRecordRequest
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment
from apim_rate_limit_foundry.models.types import ApiProtocol
from apim_rate_limit_foundry.stores.contracts import Conflict, Record
from apim_rate_limit_foundry.streaming.usage import StreamUsage
from apim_rate_limit_foundry.telemetry import correlation_id, emit


class StreamRelay:
    def __init__(
        self, engine: Engine, credential: AsyncTokenCredential, settings: Settings
    ) -> None:
        self.engine = engine
        self.credential = credential
        self.settings = settings

    async def open(
        self, tenant_id: str, request_id: str, body: bytes
    ) -> tuple[int, str, AsyncIterator[bytes], dict[str, str]]:
        if len(body) > self.settings.stream_max_body_bytes:
            raise ValueError("Stream request exceeds bound")
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Invalid streaming request body") from error
        if not isinstance(payload, dict) or payload.get("stream") is not True:
            raise ValueError("A streaming OpenAI request is required")
        key = digest(tenant_id, request_id)
        admission = await self.engine.repository.get("requests", key)
        if admission is None:
            raise Conflict("An admitted budget check is required")
        check = admission["data"]["check"]
        if not admission["data"]["decision"]["allowed"] or not check["streaming"]:
            raise Conflict("An admitted stream request is required")
        if await self.engine.repository.get(USAGE_COLLECTION, key) is not None:
            raise Conflict("Completed request IDs cannot be dispatched again")
        protocol: ApiProtocol = check["api_protocol"]
        model = self.settings.registered_model(protocol, check["model"])
        if payload.get("model") != model.model:
            raise ValueError("Streaming model does not match the admitted model")
        if protocol == "openai-chat":
            options = payload.get("stream_options")
            if not isinstance(options, dict) or options.get("include_usage") is not True:
                raise ValueError("Chat streams require stream_options.include_usage=true")
        return await self._open_upstream(request_id, model, protocol, body)

    async def _open_upstream(
        self,
        request_id: str,
        backend: ModelDeployment,
        protocol: ApiProtocol,
        body: bytes,
    ) -> tuple[int, str, AsyncIterator[bytes], dict[str, str]]:
        session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(
                total=self.settings.stream_timeout_seconds,
                connect=10,
                sock_read=self.settings.stream_timeout_seconds,
            ),
            auto_decompress=True,
        )
        try:
            token = await self.credential.get_token(f"{str(backend.audience).rstrip('/')}/.default")
            headers = {
                "Authorization": f"Bearer {token.token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Accept-Encoding": "identity",
            }
            response = await session.post(
                f"{str(backend.endpoint).rstrip('/')}{backend.path}",
                params={"api-version": backend.api_version} if backend.api_version else {},
                headers=headers,
                data=body,
                allow_redirects=False,
            )
        except BaseException:
            await session.close()
            await self._record(request_id, "usage_unknown", None)
            raise
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        response_headers = {
            name: response.headers[name]
            for name in ("Retry-After", "retry-after-ms", "x-ms-request-id", "request-id")
            if name in response.headers and len(response.headers[name]) <= 160
        }
        if response.status != 200 or content_type != "text/event-stream":
            status = response.status if response.status != 200 else 502
            try:
                body_buffer = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    body_buffer.extend(chunk)
                    if len(body_buffer) > self.settings.stream_max_event_bytes:
                        break
                if (
                    len(body_buffer) > self.settings.stream_max_event_bytes
                    or content_type != "application/json"
                ):
                    body_buffer = bytearray(b'{"error":"provider_stream_unavailable"}')
            finally:
                response.close()
                await session.close()
            await self._record(request_id, "usage_unknown", None)
            return status, "application/json", self._error(bytes(body_buffer)), response_headers
        return (
            response.status,
            "text/event-stream",
            self._stream(request_id, protocol, response, session),
            response_headers,
        )

    @staticmethod
    async def _error(body: bytes) -> AsyncIterator[bytes]:
        yield body

    async def _stream(
        self,
        request_id: str,
        protocol: ApiProtocol,
        response: aiohttp.ClientResponse,
        session: aiohttp.ClientSession,
    ) -> AsyncIterator[bytes]:
        token: Token[str] = correlation_id.set(request_id)
        observer = StreamUsage(protocol, self.settings.stream_max_event_bytes)
        usage: dict[str, Any] | None
        finalized = False
        try:
            async for chunk in response.content.iter_chunked(8192):
                observer.feed(chunk)
                yield chunk
            try:
                usage = observer.finish()
            except (ValueError, KeyError, TypeError):
                await self._record(request_id, "usage_unknown", None)
            else:
                await self._record(request_id, "actual", usage)
            finalized = True
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except (
            OSError,
            aiohttp.ClientError,
            AzureError,
            RedisError,
            ValueError,
            KeyError,
            TypeError,
        ) as error:
            emit("stream_usage_unknown", level=logging.WARNING, error_type=type(error).__name__)
        finally:
            response.close()
            await session.close()
            if not finalized:
                try:
                    usage = observer.finish()
                except (ValueError, KeyError, TypeError):
                    usage = None
                try:
                    await asyncio.shield(
                        self._record(
                            request_id, "actual" if usage is not None else "usage_unknown", usage
                        )
                    )
                except (
                    OSError,
                    aiohttp.ClientError,
                    AzureError,
                    RedisError,
                    ValueError,
                    Conflict,
                ):
                    emit("usage_record_failed", level=logging.ERROR, status="usage_unknown")
            correlation_id.reset(token)

    async def _record(
        self,
        request_id: str,
        status: Literal["actual", "usage_unknown"],
        provider_usage: dict[str, Any] | None,
    ) -> None:
        result = await self.engine.record_usage(
            UsageRecordRequest(request_id=request_id, provider_usage=provider_usage, status=status)
        )
        if not result["replayed"]:
            await self._publish(result["event"])

    async def _publish(self, usage_event: Record) -> None:
        if not self.settings.apim_usage_event_url or not self.settings.api_audience:
            emit("usage_event_publish_failed", level=logging.WARNING, error_type="not_configured")
            return
        try:
            token = await self.credential.get_token(
                f"{self.settings.api_audience.rstrip('/')}/.default"
            )
            timeout = aiohttp.ClientTimeout(total=3)
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.post(
                    self.settings.apim_usage_event_url,
                    json=usage_event,
                    headers={"Authorization": f"Bearer {token.token}"},
                    allow_redirects=False,
                ) as response,
            ):
                if response.status >= 300:
                    emit(
                        "usage_event_publish_failed",
                        level=logging.WARNING,
                        error_type=f"http_{response.status}",
                    )
        except (OSError, aiohttp.ClientError, AzureError, TimeoutError, ValueError) as error:
            emit(
                "usage_event_publish_failed",
                level=logging.WARNING,
                error_type=type(error).__name__,
            )
