import asyncio
import hashlib
import hmac
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import aiohttp
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import AzureError
from redis.exceptions import RedisError

from apim_rate_limit_foundry.caller_reference import caller_ref
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine, event
from apim_rate_limit_foundry.models import Reserve, Settle
from apim_rate_limit_foundry.models.stream_backend import StreamBackend
from apim_rate_limit_foundry.normalization.settlement import normalize_settlement_usage
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

    async def claim(self, reservation_id: str, body: bytes) -> tuple[Reserve, StreamBackend]:
        if len(body) > self.settings.stream_max_body_bytes:
            raise ValueError("Stream request exceeds bound")
        admitted = await self.engine.repository.get("usage", reservation_id)
        if admitted is None or not admitted["data"]["allowed"]:
            raise Conflict("An admitted stream reservation is required")
        if not admitted["data"].get("request", {}).get("subscription_id"):
            raise Conflict("Legacy user-scoped reservations cannot be dispatched as streams")
        request = Reserve.model_validate(admitted["data"]["request"])
        application = self.engine.application_context(request)
        protocol = request.effective_protocol
        backend: StreamBackend | None
        if self.settings.model_registry:
            if protocol is None:
                raise Conflict("A model protocol is required for streaming")
            backend = self.settings.registered_model(protocol, request.model)
            if request.price_version != backend.price_version:
                raise Conflict("Stream reservation does not match the registered price version")
        else:
            backend = self.settings.stream_backends.get(protocol)  # type: ignore[arg-type]
        if (
            request.service != "foundry"
            or not request.streaming
            or not request.payload_sha256
            or backend is None
            or (not self.settings.model_registry and request.model != backend.model)
        ):
            raise Conflict("Reservation does not identify a configured stream backend")
        if not hmac.compare_digest(request.payload_sha256, hashlib.sha256(body).hexdigest()):
            raise Conflict("Stream body does not match admission")
        payload = json.loads(body)
        if (
            not isinstance(payload, dict)
            or payload.get("stream") is not True
            or payload.get("model") != backend.model
        ):
            raise ValueError("A pinned streaming body is required")
        if request.effective_protocol == "openai-chat" and payload.get("stream_options") != {
            "include_usage": True
        }:
            raise ValueError("Chat streams require provider usage")
        if any(d["reset_at"] <= datetime.now(UTC).isoformat() for d in admitted["data"]["debits"]):
            raise Conflict("Stream admission window expired")
        if await self.engine.repository.get("settlements", reservation_id):
            raise Conflict("Stream reservation is already finalized")
        claim_id = uuid4().hex
        claimed = await self.engine.repository.create(
            "stream_dispatches",
            reservation_id,
            event(
                "stream_dispatch",
                reservation_id,
                request.tenant_id,
                request.principal_id,
                {"claim_id": claim_id, "payload_sha256": request.payload_sha256},
                request.subscription_id,
            ),
        )
        if claimed["data"]["claim_id"] != claim_id:
            raise Conflict("Stream reservation has already been dispatched")
        emit(
            "stream_dispatch_started",
            reservation_id=reservation_id,
            service=request.service,
            model=request.model,
            api_protocol=request.effective_protocol,
            streaming=True,
            caller_ref=caller_ref(request.tenant_id, request.subscription_id),
            **application,
        )
        return request, backend

    async def open(
        self, reservation_id: str, body: bytes
    ) -> tuple[int, str, AsyncIterator[bytes], dict[str, str]]:
        request, backend = await self.claim(reservation_id, body)
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
            if backend.anthropic_version:
                headers["anthropic-version"] = backend.anthropic_version
            response = await session.post(
                f"{str(backend.endpoint).rstrip('/')}{backend.path}",
                params={"api-version": backend.api_version} if backend.api_version else {},
                headers=headers,
                data=body,
                allow_redirects=False,
            )
        except BaseException:
            # Cancellation before headers must close transport but never refund a dispatch.
            await session.close()
            await self._pending(request, reservation_id, "upstream_open_failed")
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
                error = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    error.extend(chunk)
                    if len(error) > self.settings.stream_max_event_bytes:
                        break
                if (
                    len(error) > self.settings.stream_max_event_bytes
                    or content_type != "application/json"
                ):
                    error = bytearray(b'{"error":"provider_stream_unavailable"}')
            finally:
                response.close()
                await session.close()
            await self._pending(request, reservation_id, "upstream_not_sse")
            return status, "application/json", self._error(bytes(error)), response_headers
        return (
            response.status,
            "text/event-stream",
            self._stream(request, reservation_id, response, session),
            response_headers,
        )

    @staticmethod
    async def _error(body: bytes) -> AsyncIterator[bytes]:
        yield body

    async def _stream(
        self,
        request: Reserve,
        reservation_id: str,
        response: aiohttp.ClientResponse,
        session: aiohttp.ClientSession,
    ) -> AsyncIterator[bytes]:
        context_token = correlation_id.set(request.request_id)
        observer = StreamUsage(
            request.effective_protocol or "openai-chat", self.settings.stream_max_event_bytes
        )
        reason = "stream_interrupted"
        settled = False
        try:
            async for chunk in response.content.iter_chunked(8192):
                observer.feed(chunk)
                yield chunk
            raw = observer.finish()
            settlement = Settle(reservation_id=reservation_id, status="actual", provider_usage=raw)
            # Only bounded, validated terminal evidence can survive for retry after a crash.
            normalize_settlement_usage(settlement, request)
            await self.engine.repository.create(
                "stream_usage",
                reservation_id,
                event(
                    "stream_usage",
                    reservation_id,
                    request.tenant_id,
                    request.principal_id,
                    {"provider_usage": raw, "payload_sha256": request.payload_sha256},
                    request.subscription_id,
                ),
            )
            emit(
                "stream_usage_observed",
                reservation_id=reservation_id,
                service=request.service,
                model=request.model,
                api_protocol=request.effective_protocol,
                streaming=True,
                settlement_source="provider_stream",
                caller_ref=caller_ref(request.tenant_id, request.subscription_id),
                **self.engine.application_context(request),
            )
            result = await self.engine.settle(settlement)
            settled = result["kind"] == "settlement"
            reason = "incomplete_provider_usage"
            if settled:
                emit(
                    "stream_settlement_completed",
                    reservation_id=reservation_id,
                    service=request.service,
                    model=request.model,
                    api_protocol=request.effective_protocol,
                    streaming=True,
                    estimated=result["data"]["estimated"],
                    settlement_source="provider_stream",
                    caller_ref=caller_ref(request.tenant_id, request.subscription_id),
                    cost_micro_usd=result["data"]["cost_micro_usd"],
                    **self.engine.application_context(request),
                )
        except asyncio.CancelledError:
            reason = "client_disconnected"
            raise
        except GeneratorExit:
            reason = "client_disconnected"
            raise
        except (ValueError, KeyError, TypeError):
            reason = "invalid_or_missing_stream_usage"
        except (OSError, aiohttp.ClientError, AzureError, RedisError, Conflict) as error:
            reason = "stream_or_settlement_dependency_failed"
            emit(
                "stream_settlement_pending",
                level=logging.WARNING,
                reservation_id=reservation_id,
                error_type=type(error).__name__,
                streaming=True,
                estimated=True,
                reason=reason,
                caller_ref=caller_ref(request.tenant_id, request.subscription_id),
                **self.engine.application_context(request),
            )
        finally:
            response.close()
            await session.close()
            try:
                if not settled:
                    await self._pending(request, reservation_id, reason)
            finally:
                correlation_id.reset(context_token)

    async def _pending(self, request: Reserve, reservation_id: str, reason: str) -> None:
        emit(
            "stream_settlement_pending",
            level=logging.WARNING,
            reservation_id=reservation_id,
            service=request.service,
            model=request.model,
            api_protocol=request.effective_protocol,
            streaming=True,
            estimated=True,
            reason=reason,
            **self.engine.application_context(request),
        )
        record: Record = event(
            "stream_pending",
            reservation_id,
            request.tenant_id,
            request.principal_id,
            {
                "reservation_id": reservation_id,
                "status": "conservative",
                "estimated": True,
                "streaming": True,
                "reason": reason,
            },
            request.subscription_id,
        )
        try:
            async with asyncio.timeout(5):
                await self.engine.repository.create(
                    "reconciliation", f"stream-{reservation_id}", record
                )
        except (TimeoutError, OSError, AzureError, RedisError):
            # Durable admission already retains the entire liability.
            pass
