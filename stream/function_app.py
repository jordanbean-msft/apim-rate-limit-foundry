import logging

import aiohttp
import azure.functions as func
from azure.core.exceptions import AzureError
from azurefunctions.extensions.http.fastapi import JSONResponse, Request, StreamingResponse
from fastapi import HTTPException
from redis.exceptions import RedisError
from starlette.responses import Response

from apim_rate_limit_foundry.auth import authenticate
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.monitoring import configure_monitoring
from apim_rate_limit_foundry.runtime import Runtime
from apim_rate_limit_foundry.stores.contracts import Conflict
from apim_rate_limit_foundry.streaming.relay import StreamRelay
from apim_rate_limit_foundry.telemetry import correlation_id, emit, request_correlation, safe_id

settings = Settings()
configure_monitoring(settings)
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
runtime: Runtime | None = None


@app.route(route="api/stream", methods=[func.HttpMethod.POST])
async def stream_provider(req: Request) -> Response:
    global runtime
    token = correlation_id.set(request_correlation(req.headers.get("x-correlation-id")))
    try:
        actor = authenticate(req, settings)
        actor.require("RateLimit.Gateway")
        request_id = safe_id(req.headers.get("x-usage-request-id"))
        if not request_id:
            raise HTTPException(400, "X-Usage-Request-ID is required")
        body = bytearray()
        async for chunk in req.stream():
            body.extend(chunk)
            if len(body) > settings.stream_max_body_bytes:
                raise HTTPException(413, "Stream request exceeds bound")
        if runtime is None:
            runtime = Runtime(settings)
        if runtime.credential is None:
            raise HTTPException(503, "Managed identity is required for provider streams")
        relay = StreamRelay(runtime.engine, runtime.credential, settings)
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
        return JSONResponse({"detail": error.detail}, status_code=error.status_code)
    except (ValueError, Conflict):
        return JSONResponse({"detail": "Invalid stream admission"}, status_code=409)
    except (OSError, aiohttp.ClientError, AzureError, RedisError):
        emit("limiter_dependency_unavailable", level=logging.ERROR, streaming=True)
        return JSONResponse({"detail": "Streaming relay unavailable"}, status_code=503)
    finally:
        correlation_id.reset(token)
