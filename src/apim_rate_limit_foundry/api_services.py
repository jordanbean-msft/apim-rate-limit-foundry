"""Process-scoped dependencies of the budget API, built lazily and closed with the app."""

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import GatewayServices
from apim_rate_limit_foundry.reports.dashboard import DashboardService
from apim_rate_limit_foundry.runtime import Runtime


class ApiServices:
    """Expose the gateway services and dashboard, optionally injected for isolated tests.

    Cloud clients are constructed on first use rather than during route
    registration, so importing or creating the app never opens connections.
    """

    def __init__(
        self,
        settings: Settings,
        gateway: GatewayServices | None = None,
        dashboard: DashboardService | None = None,
    ) -> None:
        """Bind settings and any injected collaborators that replace the cloud runtime."""
        self.settings = settings
        self._gateway = gateway
        self._dashboard = dashboard
        self._runtime: Runtime | None = None

    @property
    def runtime(self) -> Runtime:
        """Share one lazily created set of clients for this application instance."""
        if self._runtime is None:
            self._runtime = Runtime(self.settings)
        return self._runtime

    @property
    def gateway(self) -> GatewayServices:
        """Return the injected services, otherwise the runtime's."""
        return self._gateway if self._gateway is not None else self.runtime.gateway

    @property
    def dashboard(self) -> DashboardService | None:
        """Return the injected dashboard, otherwise the runtime's (None if unconfigured)."""
        return self._dashboard if self._dashboard is not None else self.runtime.dashboard

    async def close(self) -> None:
        """Allow a bounded write-behind drain before releasing owned cloud clients."""
        if self._runtime is not None:
            await self._runtime.close()
