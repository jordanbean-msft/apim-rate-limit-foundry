"""Join manual dependencies to native service diagnostics using bounded request IDs."""

from collections.abc import Mapping

from azure.core.pipeline import PipelineResponse
from opentelemetry import trace

from apim_rate_limit_foundry.telemetry.events import emit
from apim_rate_limit_foundry.telemetry.sanitizer import safe_attributes


def record_service_response(
    dependency: str,
    status: int,
    headers: Mapping[str, str],
    request_headers: Mapping[str, str] | None = None,
) -> None:
    """Record only service/client request IDs, never arbitrary headers or response data."""
    response = {name.lower(): value for name, value in headers.items()}
    request = {name.lower(): value for name, value in (request_headers or {}).items()}
    attributes = safe_attributes(
        {
            "dependency": dependency,
            "http_status": status,
            "service_request_id": response.get("x-ms-request-id")
            or response.get("apim-request-id")
            or response.get("request-id")
            or response.get("x-request-id"),
            "client_request_id": request.get("x-ms-client-request-id"),
        }
    )
    trace.get_current_span().set_attributes(attributes)
    emit("dependency_response", **attributes)


def record_table_response(response: PipelineResponse) -> None:
    """Azure SDK response hook, called within the enclosing Table dependency span."""
    record_service_response(
        "table",
        response.http_response.status_code,
        response.http_response.headers,
        response.http_request.headers,
    )
