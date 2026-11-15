# Deploy budget grid and generate demo traffic

- [x] Implement the unified admin budget grid and preserve Reader access.
- [x] Validate portal tests, formatting, lint, types, production build and packages.
- [x] Confirm the existing deployment target and bounded paid traffic with the user.
- [x] Validate Azure configuration and read-only infrastructure preview.
- [x] Deploy only web; verify the deployed bundle and existing authentication.
- [x] Generate at most 120 real inference requests with at most $2 estimated cost,
  including cached/uncached usage and model-specific monthly-budget denials.
- [x] Verify ledger and dashboard results; restore temporary budget changes.

Deployment validation proof and operational progress:
`.azure/deployment-plan.md`. Traffic evidence belongs in session artifacts, not
source control. No infrastructure changes are required.
