"""Issue one real, bounded inference and export its client span without model content."""

import argparse
import asyncio
import json
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import SpanKind, StatusCode, Tracer

from apim_rate_limit_foundry.accounting import normalize_openai_usage
from apim_rate_limit_foundry.models.types import ApiProtocol
from apim_rate_limit_foundry.streaming.usage import StreamUsage
from apim_rate_limit_foundry.telemetry import outgoing_trace_headers, safe_id
from scripts.inference_settings import InferenceSettings


async def infer(
    settings: InferenceSettings,
    protocol: ApiProtocol,
    streaming: bool,
    session: aiohttp.ClientSession,
    tracer: Tracer,
) -> dict[str, Any]:
    """Keep the client span open until body consumption, including SSE terminal usage."""
    chat = protocol == "openai-chat"
    path = "/foundry/chat/completions" if chat else "/foundry/responses"
    payload: dict[str, Any] = {"model": settings.model, "stream": streaming}
    if chat:
        payload.update(
            messages=[{"role": "user", "content": "Say hello."}], max_completion_tokens=32
        )
    else:
        payload.update(input="Say hello.", max_output_tokens=32)
    if streaming and chat:
        payload["stream_options"] = {"include_usage": True}
    with tracer.start_as_current_span(
        "POST " + path,
        kind=SpanKind.CLIENT,
        attributes={
            "http.request.method": "POST",
            "server.address": urlsplit(str(settings.gateway)).hostname or "",
            "peer.service": urlsplit(str(settings.gateway)).hostname or "",
            "api_protocol": protocol,
            "streaming": streaming,
            "model": settings.model,
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        context = span.get_span_context()
        result: dict[str, Any] = {
            "trace_id": f"{context.trace_id:032x}",
            "span_id": f"{context.span_id:016x}",
            "api_protocol": protocol,
            "streaming": streaming,
        }
        try:
            async with session.post(
                str(settings.gateway).rstrip("/") + path,
                json=payload,
                headers={
                    "Authorization": "Bearer " + settings.access_token.get_secret_value(),
                    "Ocp-Apim-Subscription-Key": settings.subscription_key.get_secret_value(),
                    **outgoing_trace_headers(),
                },
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=settings.timeout_seconds),
            ) as response:
                span.set_attribute("http.response.status_code", response.status)
                correlation = safe_id(response.headers.get("X-Correlation-ID"))
                if correlation:
                    span.set_attribute("correlation_id", correlation)
                    span.set_attribute("request_id", correlation)
                    result["correlation_id"] = correlation
                if response.status != 200:
                    raise RuntimeError(f"Inference returned HTTP {response.status}")
                if correlation is None:
                    raise RuntimeError("Gateway response did not contain a valid correlation ID")
                observer = StreamUsage(protocol, 65536) if streaming else None
                usage: object
                body = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    if observer is not None:
                        observer.feed(chunk)
                    else:
                        if len(body) + len(chunk) > 1024 * 1024:
                            raise RuntimeError("Inference response exceeded the test-client bound")
                        body.extend(chunk)
                if observer is not None:
                    usage = observer.finish()
                else:
                    document = json.loads(body)
                    usage = document.get("usage") if isinstance(document, dict) else None
                if not isinstance(usage, dict):
                    raise RuntimeError("Inference ended without complete provider usage")
                normalize_openai_usage(usage, protocol)
                result["http_status"] = response.status
                result["outcome"] = "completed"
        except BaseException as error:
            span.set_attribute("error.type", type(error).__name__)
            span.set_status(StatusCode.ERROR)
            raise
        span.set_status(StatusCode.OK)
        return result


async def run(protocol: ApiProtocol, streaming: bool) -> None:
    """Flush the explicit client exporter before exiting; no auto HTTP/content collectors."""
    settings = InferenceSettings.model_validate({})
    provider = TracerProvider(resource=Resource.create({"service.name": "inference-test-client"}))
    provider.add_span_processor(
        SimpleSpanProcessor(
            AzureMonitorTraceExporter(
                connection_string=settings.applicationinsights_connection_string.get_secret_value(),
                disable_offline_storage=True,
                tracer_provider=provider,
            )
        )
    )
    try:
        async with aiohttp.ClientSession() as session:
            result = await infer(
                settings, protocol, streaming, session, provider.get_tracer(__name__)
            )
        print(json.dumps(result))
    finally:
        provider.force_flush(timeout_millis=10000)
        provider.shutdown()


def main() -> None:
    """Run one opt-in request; credentials come only from INFERENCE_* environment variables."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol", choices=("openai-chat", "openai-responses"), default="openai-chat"
    )
    parser.add_argument("--stream", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.protocol, args.stream))


if __name__ == "__main__":
    main()
