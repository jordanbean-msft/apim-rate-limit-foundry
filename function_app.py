import azure.functions as func

from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.monitoring import configure_monitoring

settings = Settings()
configure_monitoring(settings)
api = create_app(settings)
app = func.AsgiFunctionApp(app=api, http_auth_level=func.AuthLevel.ANONYMOUS)
