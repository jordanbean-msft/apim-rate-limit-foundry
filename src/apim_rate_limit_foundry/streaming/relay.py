"""Pass provider SSE through unchanged while observing terminal usage separately."""

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

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.models.budget_check import UsageRecordRequest
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment
from apim_rate_limit_foundry.models.types import ApiProtocol
from apim_rate_limit_foundry.observed_credential import ObservedCredential
from apim_rate_limit_foundry.stores.contracts import Conflict, Record
from apim_rate_limit_foundry.streaming.usage import StreamUsage
from apim_rate_limit_foundry.telemetry import (
    correlation_id,
    dependency_http_status,
    emit,
    http_dependency_span,
    outgoing_trace_headers,
)


class StreamRelay:
    """Bind streaming dispatch and final accounting to an existing Redis admission."""

    def __init__(
        self,
        engine: Engine,
        credential: AsyncTokenCredential,
        settings: Settings,
        session: aiohttp.ClientSession,
    ) -> None:
        """Bind collaborators; the caller owns the shared HTTP session's lifetime."""
        self.engine = engine
        self.credential = ObservedCredential(credential)
        self.settings = settings
        self.session = session

    async def open(
        self, tenant_id: str, request_id: str, body: bytes
    ) -> tuple[int, str, AsyncIterator[bytes], dict[str, str]]:
        """Validate admitted identity/model and open an upstream streaming response.

        Return status, media type, a byte iterator and allowlisted response headers.
        No new budget decision is made here: the tenant/request ID must reference
        an allowed streaming context that has not already been finalized.
        """
        if len(body) > self.settings.stream_max_body_bytes:
            raise ValueError("Stream request exceeds bound")
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Invalid streaming request body") from error
        if not isinstance(payload, dict) or payload.get("stream") is not True:
            raise ValueError("A streaming OpenAI request is required")
        admission = await self.engine.counters.request(request_id)
        if admission is None or admission["tenant_id"] != tenant_id:
            raise Conflict("An admitted budget check is required")
        check = admission["data"]["check"]
        if not admission["data"]["decision"]["allowed"] or not check["streaming"]:
            raise Conflict("An admitted stream request is required")
        if await self.engine.counters.usage(request_id) is not None:
            raise Conflict("Completed request IDs cannot be dispatched again")
        protocol: ApiProtocol = check["api_protocol"]
        # Resolve the saved alias, not a caller-controlled provider URL or model.
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
        """Acquire provider credentials and return an owned response-body iterator.

        The iterator releases its response after consumption. Open failures
        attempt unknown-usage accounting (charged at the pinned upper bound) before
        propagating. A non-200 provider reply (throttling, rejection) generated no
        tokens and is not charged; a 200 with a non-SSE body is charged as unknown.
        Non-SSE/non-200 replies are bounded JSON errors, never
        buffered model output.
        """
        try:
            with http_dependency_span("provider.stream_open", "model-provider") as span:
                token = await self.credential.get_token(
                    f"{str(backend.audience).rstrip('/')}/.default"
                )
                headers = {
                    "Authorization": f"Bearer {token.token}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "Accept-Encoding": "identity",
                    **outgoing_trace_headers(request_id),
                }
                response = await self.session.post(
                    f"{str(backend.endpoint).rstrip('/')}{backend.path}",
                    params={"api-version": backend.api_version} if backend.api_version else {},
                    headers=headers,
                    data=body,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(
                        total=self.settings.stream_timeout_seconds,
                        connect=10,
                        sock_read=self.settings.stream_timeout_seconds,
                    ),
                )
                dependency_http_status(span, response.status)
        except BaseException:
            await self._record(request_id, "usage_unknown", None)
            raise
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        response_headers = {
            name: response.headers[name]
            for name in ("Retry-After", "retry-after-ms", "x-ms-request-id", "request-id")
            if name in response.headers and len(response.headers[name]) <= 160
        }
        if response.status != 200 or content_type != "text/event-stream":
            # A successful HTTP status with a non-stream body is not a usable SSE response.
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
            if response.status == 200:
                await self._record(request_id, "usage_unknown", None)
            return status, "application/json", self._error(bytes(body_buffer)), response_headers
        return (
            response.status,
            "text/event-stream",
            self._stream(request_id, protocol, response),
            response_headers,
        )

    @staticmethod
    async def _error(body: bytes) -> AsyncIterator[bytes]:
        """Adapt bounded provider error bytes to the streaming response interface."""
        yield body

    async def _stream(
        self,
        request_id: str,
        protocol: ApiProtocol,
        response: aiohttp.ClientResponse,
    ) -> AsyncIterator[bytes]:
        """Yield original chunks, then finalize whatever terminal usage was observed.

        Observation never changes chunk contents. Normal completion, provider
        errors and client disconnects share one shielded finalization: observed
        usage is priced, otherwise the engine charges its conservative upper bound.
        A worker crash can lose that attempt and any process-local persistence/export.
        """
        token: Token[str] = correlation_id.set(request_id)
        observer = StreamUsage(protocol, self.settings.stream_max_event_bytes)
        try:
            async for chunk in response.content.iter_chunked(8192):
                # The observer retains only bounded SSE framing/usage, not the full response.
                observer.feed(chunk)
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except (OSError, aiohttp.ClientError, AzureError) as error:
            emit("stream_usage_unknown", level=logging.WARNING, error_type=type(error).__name__)
        finally:
            response.close()
            await self._finalize(request_id, observer)
            correlation_id.reset(token)

    async def _finalize(self, request_id: str, observer: StreamUsage) -> None:
        """Record observed terminal usage, or unknown usage, shielded from cancellation."""
        try:
            usage: dict[str, Any] | None = observer.finish()
        except (ValueError, KeyError, TypeError):
            usage = None
        if usage is None and observer.rejected:
            emit("stream_rejected_by_provider", level=logging.WARNING)
            return
        status: Literal["actual", "usage_unknown"] = (
            "actual" if usage is not None else "usage_unknown"
        )
        try:
            await asyncio.shield(self._record(request_id, status, usage))
        except (OSError, aiohttp.ClientError, AzureError, RedisError, ValueError):
            emit("usage_record_failed", level=logging.ERROR, status=status)

    async def _record(
        self,
        request_id: str,
        status: Literal["actual", "usage_unknown"],
        provider_usage: dict[str, Any] | None,
    ) -> None:
        """Accept actual/unknown usage into Redis and enqueue export only once.

        The engine independently schedules the Table mirror. Neither that mirror
        nor APIM's export callback is awaited as part of this method's completion.
        """
        result = await self.engine.record_usage(
            UsageRecordRequest(request_id=request_id, provider_usage=provider_usage, status=status)
        )
        if not result["replayed"]:
            self.engine.background.submit(
                "usage_event", request_id, lambda: self._publish(result["event"])
            )

    async def _publish(self, usage_event: Record) -> None:
        """POST the versioned usage event to APIM as a best-effort background job.

        Observe HTTP acceptance, not Event Hub delivery or consumer processing.
        Failures are logged without retrying or undoing Redis-accepted accounting.
        """
        identifiers: Record = {
            "request_id": usage_event.get("request_id"),
            "event_id": usage_event.get("event_id"),
        }
        if not self.settings.apim_usage_event_url or not self.settings.api_audience:
            emit(
                "usage_event_publish_failed",
                level=logging.WARNING,
                error_type="not_configured",
                **identifiers,
            )
            return
        try:
            with http_dependency_span("apim.usage_events", "apim") as span:
                token = await self.credential.get_token(
                    f"{self.settings.api_audience.rstrip('/')}/.default"
                )
                async with self.session.post(
                    self.settings.apim_usage_event_url,
                    json=usage_event,
                    headers={
                        "Authorization": f"Bearer {token.token}",
                        **outgoing_trace_headers(usage_event.get("request_id")),
                    },
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as response:
                    dependency_http_status(span, response.status)
                    if response.status >= 300:
                        emit(
                            "usage_event_publish_failed",
                            level=logging.WARNING,
                            error_type=f"http_{response.status}",
                            http_status=response.status,
                            **identifiers,
                        )
                    else:
                        emit(
                            "usage_event_publish_accepted",
                            status="accepted",
                            http_status=response.status,
                            **identifiers,
                        )
        except (OSError, aiohttp.ClientError, AzureError, TimeoutError, ValueError) as error:
            emit(
                "usage_event_publish_failed",
                level=logging.WARNING,
                error_type=type(error).__name__,
                **identifiers,
            )
