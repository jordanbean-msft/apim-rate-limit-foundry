import azure.functions as func

from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.telemetry import configure_logging

configure_logging()
api = create_app()
app = func.AsgiFunctionApp(app=api, http_auth_level=func.AuthLevel.ANONYMOUS)


@app.timer_trigger(
    schedule="0 */5 * * * *", arg_name="timer", run_on_startup=False, use_monitor=True
)
async def reconcile_usage(timer: func.TimerRequest) -> None:
    await api.state.get_engine().reconcile()
