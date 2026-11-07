import logging

import azure.functions as func
from opentelemetry import trace
from opentelemetry.trace import StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.monitoring import configure_monitoring
from apim_rate_limit_foundry.streaming.replay import replay_stream_usage
from apim_rate_limit_foundry.telemetry import (
    LOGGER_NAME,
    correlation_id,
    emit,
    request_correlation,
)

settings = Settings()
configure_monitoring(settings)
api = create_app(settings)
app = func.AsgiFunctionApp(app=api, http_auth_level=func.AuthLevel.ANONYMOUS)


@app.timer_trigger(
    schedule="0 */5 * * * *", arg_name="timer", run_on_startup=False, use_monitor=True
)
async def reconcile_usage(timer: func.TimerRequest, context: func.Context) -> None:
    token = correlation_id.set(request_correlation(context.invocation_id))
    parent = TraceContextTextMapPropagator().extract(
        {"traceparent": context.trace_context.trace_parent or ""}
    )
    try:
        with trace.get_tracer(LOGGER_NAME).start_as_current_span(
            "limiter.reconcile_timer",
            context=parent,
            attributes={"correlation_id": correlation_id.get()},
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            emit("reconciliation_timer_started", past_due=timer.past_due)
            try:
                await replay_stream_usage(api.state.get_engine())
                count = await api.state.get_engine().reconcile()
            except Exception as error:
                span.set_status(StatusCode.ERROR)
                emit(
                    "reconciliation_timer_failed",
                    level=logging.ERROR,
                    error_type=type(error).__name__,
                )
                raise
            else:
                span.set_status(StatusCode.OK)
                emit("reconciliation_timer_completed", records=count, status="ok")
    finally:
        correlation_id.reset(token)
