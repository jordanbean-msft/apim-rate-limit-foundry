"""Separate HTTP-streaming Function host; Easy Auth, not function keys, authenticates it."""

import logging
from functools import cache

import aiohttp
import azure.functions as func
from azure.core.exceptions import AzureError
from azurefunctions.extensions.http.fastapi import Request, StreamingResponse
from fastapi import HTTPException
from redis.exceptions import RedisError
from starlette.responses import Response

from apim_rate_limit_foundry.api_errors import detail_response
from apim_rate_limit_foundry.auth import ROLE_GATEWAY, authenticate
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.monitoring import configure_monitoring
from apim_rate_limit_foundry.runtime import Runtime
from apim_rate_limit_foundry.streaming.relay import StreamRelay
from apim_rate_limit_foundry.streaming.request_telemetry import trace_stream_request
from apim_rate_limit_foundry.telemetry import emit, safe_id

settings = Settings()
configure_monitoring(settings)
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@cache
def get_runtime() -> Runtime:
    """Build the process-wide runtime once so connections are reused across invocations.

    Must first be called inside the serving event loop: the runtime then drains its
    best-effort writes and closes its clients when that loop shuts down.
    """
    runtime = Runtime(settings)
    runtime.close_on_loop_shutdown()
    return runtime


@app.route(route="api/stream", methods=[func.HttpMethod.POST])
@trace_stream_request
async def stream_provider(req: Request) -> Response:
    """Relay POST /api/stream only for an already admitted gateway request.

    APIM supplies X-Usage-Request-ID and an OpenAI JSON body with stream=true.
    The response forwards bounded provider error JSON or unbuffered SSE bytes
    plus selected provider headers. X-RateLimit-Accounting=post-request means
    final usage is not yet known when response headers are sent.

    Authentication/role failures retain 401/403; missing ID is 400 and oversized
    input is 413. Invalid or conflicting admission becomes 409, dependency
    unavailability 503. Final Redis accounting and best-effort Table/export jobs
    run as the stream terminates; headers cannot promise their future success.
    """
    try:
        actor = authenticate(req, settings)
        actor.require(ROLE_GATEWAY)
        request_id = safe_id(req.headers.get("x-usage-request-id"))
        if not request_id:
            raise HTTPException(400, "X-Usage-Request-ID is required")
        body = bytearray()
        async for chunk in req.stream():
            body.extend(chunk)
            if len(body) > settings.stream_max_body_bytes:
                raise HTTPException(413, "Stream request exceeds bound")
        runtime = get_runtime()
        if runtime.credential is None:
            raise HTTPException(503, "Managed identity is required for provider streams")
        relay = StreamRelay(runtime.gateway, runtime.credential, settings, runtime.http_session())
        status, content_type, chunks, provider_headers = await relay.open(
            actor.tenant_id, request_id, bytes(body)
        )
        return StreamingResponse(
            chunks,
            status_code=status,
            media_type=content_type,
            headers={
                **provider_headers,
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
                "X-RateLimit-Accounting": "post-request",
            },
        )
    except HTTPException as error:
        return detail_response(error.status_code, str(error.detail))
    except ValueError:
        return detail_response(409, "Invalid stream admission")
    except (OSError, aiohttp.ClientError, AzureError, RedisError):
        emit("limiter_dependency_unavailable", level=logging.ERROR, streaming=True)
        return detail_response(503, "Streaming relay unavailable")
