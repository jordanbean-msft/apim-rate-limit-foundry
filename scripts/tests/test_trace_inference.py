import json
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import ValidationError

from scripts import trace_inference
from scripts.inference_settings import InferenceSettings
from scripts.trace_inference import infer
from tests.fakes import FakeHttpSession

CORRELATION = "b9e8bc31-72f6-4f2e-8f5b-d87d8c8a93fa"


def test_cli_settings_load_required_values_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in {
        "GATEWAY": "https://gateway.example.com",
        "MODEL": "model-1",
        "ACCESS_TOKEN": "private-token",
        "SUBSCRIPTION_KEY": "private-key",
        "APPLICATIONINSIGHTS_CONNECTION_STRING": "private-connection",
    }.items():
        monkeypatch.setenv("INFERENCE_" + name, value)

    settings = InferenceSettings.model_validate({})

    assert settings.model == "model-1"
    assert settings.access_token.get_secret_value() == "private-token"
    assert "private-token" not in repr(settings)


@pytest.fixture
def client_settings() -> InferenceSettings:
    return InferenceSettings(
        gateway="https://gateway.example.com",
        model="model-1",
        access_token="private-token",
        subscription_key="private-key",
        applicationinsights_connection_string="private-connection",
    )


@pytest.fixture
def tracing() -> Iterator[SimpleNamespace]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        yield SimpleNamespace(exporter=exporter, tracer=provider.get_tracer("test"))
    finally:
        provider.shutdown()


async def test_run_supplies_private_provider_to_the_azure_exporter(
    client_settings: InferenceSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    exporter = Mock()
    factory = Mock(return_value=exporter)
    monkeypatch.setattr(InferenceSettings, "model_validate", Mock(return_value=client_settings))
    monkeypatch.setattr(trace_inference, "AzureMonitorTraceExporter", factory)
    monkeypatch.setattr(trace_inference, "infer", AsyncMock(return_value={"outcome": "completed"}))
    global_provider = trace.get_tracer_provider()

    await trace_inference.run("openai-chat", False)

    provider = factory.call_args.kwargs["tracer_provider"]
    assert provider.resource.attributes["service.name"] == "inference-test-client"
    assert provider is not global_provider
    assert trace.get_tracer_provider() is global_provider
    exporter.shutdown.assert_called_once()


@pytest.mark.parametrize("protocol", ["openai-chat", "openai-responses"])
@pytest.mark.parametrize("streaming", [False, True])
async def test_client_exports_parent_and_gateway_uuid_without_content_or_credentials(
    protocol: str,
    streaming: bool,
    client_settings: InferenceSettings,
    tracing: SimpleNamespace,
) -> None:
    chat = protocol == "openai-chat"
    usage = (
        {"prompt_tokens": 2, "completion_tokens": 1}
        if chat
        else {"input_tokens": 2, "output_tokens": 1}
    )
    document = {"usage": usage, "choices": []}
    if streaming and not chat:
        document = {
            "type": "response.completed",
            "response": {"status": "completed", "usage": usage},
        }
    data = json.dumps(document).encode()
    if streaming:
        data = b"data: " + data + b"\n\n"

    async def chunks(size: int):
        assert trace.get_current_span().get_span_context().is_valid
        assert not tracing.exporter.get_finished_spans()
        yield data

    response = SimpleNamespace(
        status=200,
        headers={"X-Correlation-ID": CORRELATION},
        content=SimpleNamespace(iter_chunked=chunks),
    )
    session = FakeHttpSession(lambda *args, **kwargs: response)

    result = await infer(client_settings, protocol, streaming, session, tracing.tracer)

    (span,) = tracing.exporter.get_finished_spans()
    assert span.kind == SpanKind.CLIENT
    assert span.status.status_code == StatusCode.OK
    assert span.attributes["request_id"] == CORRELATION
    assert result["trace_id"] == f"{span.context.trace_id:032x}"
    assert result["span_id"] == f"{span.context.span_id:016x}"
    url, options = session.calls[0]
    assert url.endswith("/foundry/chat/completions" if chat else "/foundry/responses")
    assert options["headers"]["traceparent"] == (
        f"00-{result['trace_id']}-{result['span_id']}-{int(span.context.trace_flags):02x}"
    )
    assert options["allow_redirects"] is False
    assert "X-Correlation-ID" not in options["headers"]
    assert not span.events
    exported = repr(dict(span.attributes)) + repr(result)
    assert all(value not in exported for value in ("private-", "Say hello.", "Bearer"))
    assert trace.get_current_span().get_span_context().is_valid is False


@pytest.mark.parametrize("status", [302, 429])
async def test_denial_and_redirect_fail_without_reading_or_exporting_response_body(
    status: int, client_settings: InferenceSettings, tracing: SimpleNamespace
) -> None:
    response = SimpleNamespace(status=status, headers={"X-Correlation-ID": CORRELATION})
    session = FakeHttpSession(lambda *args, **kwargs: response)

    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        await infer(client_settings, "openai-chat", False, session, tracing.tracer)

    (span,) = tracing.exporter.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["correlation_id"] == CORRELATION
    assert not span.events


async def test_truncated_sse_is_a_failed_client_span(
    client_settings: InferenceSettings, tracing: SimpleNamespace
) -> None:
    async def chunks(size: int):
        yield b'data: {"choices":[{"delta":{"content":"private-output"}}]}\n\n'

    response = SimpleNamespace(
        status=200,
        headers={"X-Correlation-ID": CORRELATION},
        content=SimpleNamespace(iter_chunked=chunks),
    )
    session = FakeHttpSession(lambda *args, **kwargs: response)

    with pytest.raises(ValueError, match="terminal usage"):
        await infer(client_settings, "openai-chat", True, session, tracing.tracer)

    (span,) = tracing.exporter.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert "private-output" not in repr(span)


@pytest.mark.parametrize(
    "gateway",
    [
        "http://gateway.example.com",
        "https://user:password@gateway.example.com",
        "https://gateway.example.com/evil",
    ],
)
def test_client_refuses_unsafe_credential_destinations(
    gateway: str, client_settings: InferenceSettings
) -> None:
    with pytest.raises(ValidationError):
        InferenceSettings(**{**client_settings.model_dump(), "gateway": gateway})
