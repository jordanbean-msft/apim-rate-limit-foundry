"""Pass provider SSE through unchanged while observing terminal usage separately."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextvars import Token
from time import perf_counter
from typing import Any, Literal

import aiohttp
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import AzureError
from redis.exceptions import RedisError

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import GatewayServices
from apim_rate_limit_foundry.models import BudgetCheck
from apim_rate_limit_foundry.models.admission_context import AdmissionContext
from apim_rate_limit_foundry.models.budget_check import UsageRecordRequest
from apim_rate_limit_foundry.models.model_deployment import ModelDeployment
from apim_rate_limit_foundry.models.types import ApiProtocol
from apim_rate_limit_foundry.observed_credential import ObservedCredential
from apim_rate_limit_foundry.rate_limit_metrics import rate_metrics
from apim_rate_limit_foundry.stores.contracts import Conflict
from apim_rate_limit_foundry.streaming.upstream_response import UpstreamResponse
from apim_rate_limit_foundry.streaming.usage import StreamUsage
from apim_rate_limit_foundry.telemetry import (
    correlation_id,
    dependency_http_status,
    elapsed_ms,
    emit,
    http_dependency_span,
    outgoing_trace_headers,
    record_service_response,
)


class StreamRelay:
    """Bind streaming dispatch and final accounting to an existing Redis admission."""

    def __init__(
        self,
        gateway: GatewayServices,
        credential: AsyncTokenCredential,
        settings: Settings,
        session: aiohttp.ClientSession,
    ) -> None:
        """Bind collaborators; the caller owns the shared HTTP session's lifetime."""
        self.gateway = gateway
        self.credential = ObservedCredential(credential)
        self.settings = settings
        self.session = session

    async def open(self, tenant_id: str, request_id: str, body: bytes) -> UpstreamResponse:
        """Validate admitted identity/model and open an upstream streaming response.

        No new budget decision is made here: the tenant/request ID must reference
        an allowed streaming context that has not already been finalized.
        """
        payload = self._parse_body(body)
        check = await self._admitted_check(tenant_id, request_id)
        protocol = check.api_protocol
        # Resolve the saved alias, not a caller-controlled provider URL or model.
        model = self.settings.registered_model(protocol, check.model)
        if payload.get("model") != model.model:
            raise ValueError("Streaming model does not match the admitted model")
        if protocol == "openai-chat":
            options = payload.get("stream_options")
            if not isinstance(options, dict) or options.get("include_usage") is not True:
                raise ValueError("Chat streams require stream_options.include_usage=true")
        return await self._open_upstream(request_id, model, protocol, body)

    def _parse_body(self, body: bytes) -> dict[str, Any]:
        """Require a bounded JSON object that asks for a stream."""
        if len(body) > self.settings.stream_max_body_bytes:
            raise ValueError("Stream request exceeds bound")
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Invalid streaming request body") from error
        if not isinstance(payload, dict) or payload.get("stream") is not True:
            raise ValueError("A streaming OpenAI request is required")
        return payload

    async def _admitted_check(self, tenant_id: str, request_id: str) -> BudgetCheck:
        """Return the saved check of an allowed, unfinalized streaming admission."""
        admission = await self.gateway.counters.request(request_id)
        if admission is None or admission["tenant_id"] != tenant_id:
            raise Conflict("An admitted budget check is required")
        context = AdmissionContext.model_validate(admission["data"])
        if not context.decision.allowed or not context.check.streaming:
            raise Conflict("An admitted stream request is required")
        if await self.gateway.counters.usage(request_id) is not None:
            raise Conflict("Completed request IDs cannot be dispatched again")
        return context.check

    async def _open_upstream(
        self,
        request_id: str,
        backend: ModelDeployment,
        protocol: ApiProtocol,
        body: bytes,
    ) -> UpstreamResponse:
        """Acquire provider credentials and return an owned response-body iterator.

        The iterator releases its response after consumption. Open failures
        attempt unknown-usage accounting (charged at the pinned upper bound) before
        propagating. A non-200 provider reply (throttling, rejection) generated no
        tokens and is not charged; a 200 with a non-SSE body is charged as unknown.
        Non-SSE/non-200 replies are bounded JSON errors, never
        buffered model output.
        """
        started = perf_counter()
        try:
            response = await self._post_upstream(request_id, backend, body)
        except BaseException as error:
            rate_metrics.provider_response(
                protocol, None, elapsed_ms(started), type(error).__name__
            )
            rate_metrics.stream_outcome(protocol, "open_failed")
            await self._record(request_id, "usage_unknown", None)
            raise
        rate_metrics.provider_response(protocol, response.status, elapsed_ms(started))
        headers = {
            name: response.headers[name]
            for name in ("Retry-After", "retry-after-ms", "x-ms-request-id", "request-id")
            if name in response.headers and len(response.headers[name]) <= 160
        }
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if response.status == 200 and content_type == "text/event-stream":
            return UpstreamResponse(
                200, "text/event-stream", self._stream(request_id, protocol, response), headers
            )
        # A successful HTTP status with a non-stream body is not a usable SSE response.
        error_body = await self._read_error_body(response, content_type)
        rate_metrics.stream_outcome(
            protocol, "provider_error" if response.status != 200 else "invalid_response"
        )
        if response.status == 200:
            await self._record(request_id, "usage_unknown", None)
        status = response.status if response.status != 200 else 502
        return UpstreamResponse(status, "application/json", self._error(error_body), headers)

    async def _post_upstream(
        self, request_id: str, backend: ModelDeployment, body: bytes
    ) -> aiohttp.ClientResponse:
        """Send the admitted body to the registered deployment with its own identity token."""
        with http_dependency_span(
            "provider.stream_open", "model-provider", server_address=backend.endpoint.host or ""
        ) as span:
            token = await self.credential.get_token(f"{str(backend.audience).rstrip('/')}/.default")
            response = await self.session.post(
                f"{str(backend.endpoint).rstrip('/')}{backend.path}",
                params={"api-version": backend.api_version} if backend.api_version else {},
                headers={
                    "Authorization": f"Bearer {token.token}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "Accept-Encoding": "identity",
                    **outgoing_trace_headers(request_id),
                },
                data=body,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(
                    total=self.settings.stream_timeout_seconds,
                    connect=10,
                    sock_read=self.settings.stream_timeout_seconds,
                ),
            )
            dependency_http_status(span, response.status)
            record_service_response("model-provider", response.status, response.headers)
            return response

    async def _read_error_body(self, response: aiohttp.ClientResponse, content_type: str) -> bytes:
        """Read a bounded provider JSON error, replacing anything else with a fixed error."""
        limit = self.settings.stream_max_event_bytes
        collected = bytearray()
        try:
            async for chunk in response.content.iter_chunked(8192):
                collected.extend(chunk)
                if len(collected) > limit:
                    break
        finally:
            response.close()
        if len(collected) > limit or content_type != "application/json":
            return b'{"error":"provider_stream_unavailable"}'
        return bytes(collected)

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
        usage is priced, otherwise the usage recorder charges its conservative upper bound.
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
            await self._finalize(request_id, protocol, observer)
            correlation_id.reset(token)

    async def _finalize(
        self, request_id: str, protocol: ApiProtocol, observer: StreamUsage
    ) -> None:
        """Record observed terminal usage, or unknown usage, shielded from cancellation."""
        try:
            usage: dict[str, Any] | None = observer.finish()
        except (ValueError, KeyError, TypeError):
            usage = None
        if usage is None and observer.rejected:
            emit("stream_rejected_by_provider", level=logging.WARNING)
            rate_metrics.stream_outcome(protocol, "provider_throttled")
            return
        status: Literal["actual", "usage_unknown"] = (
            "actual" if usage is not None else "usage_unknown"
        )
        try:
            await asyncio.shield(self._record(request_id, status, usage))
        except (OSError, aiohttp.ClientError, AzureError, RedisError, ValueError):
            emit("usage_record_failed", level=logging.ERROR, status=status)
            rate_metrics.stream_outcome(protocol, "accounting_failed")
        else:
            rate_metrics.stream_outcome(protocol, "completed" if usage else "usage_unknown")

    async def _record(
        self,
        request_id: str,
        status: Literal["actual", "usage_unknown"],
        provider_usage: dict[str, Any] | None,
    ) -> None:
        """Accept actual/unknown usage into Redis; the recorder schedules mirror and export.

        Neither the Table mirror nor the Event Hub export is awaited here.
        """
        await self.gateway.usage.record(
            UsageRecordRequest(request_id=request_id, provider_usage=provider_usage, status=status)
        )
