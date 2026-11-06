# Verify live rate limits and observability

Audit the existing public Commercial demo without disabling authentication, resetting
Redis, accepting Claude terms or logging credentials, prompts, document bodies or PII.
Keep infrastructure updates in Terraform and preserve the demo resource tags.

- [ ] Audit live Redis state and Application Insights, Log Analytics, APIM and hosting logs.
  Parent owns live queries and evidence under ignored `.azure/publicdemo/`.
- [ ] Add comprehensive structured Function decision, settlement, dependency, configuration,
  recovery and error telemetry. Backend agent owns Python source, Function entry point,
  Python dependencies and focused tests; use Microsoft Azure Monitor OpenTelemetry.
- [ ] Add safe portal server and browser telemetry. Portal agent owns `web/` only:
  request outcomes, API/configuration actions and failures, no token/body/identity logging.
- [ ] Correct Terraform diagnostic destinations and hosting/APIM telemetry settings.
  Parent owns `infra/`, APIM policies, operator docs and developer automation.
- [ ] Integrate and validate Python, web, gateway and Terraform changes, then deploy.
  Depends on the three implementation items; require zero-warning Terraform validation,
  warning-free tests and applicable lint/type/build checks.
- [ ] Configure multiple limits through the authenticated portal and verify allowed/denied
  calls to Chat, Responses, Language and Document Intelligence, counter values and logs.
  Confirm request, cost and service-unit limits, disabled/raised limits, shared protocol
  budgets, actual cached settlement and conservative streaming. Restore test policies.
- [ ] Record concrete correlation evidence, destinations, endpoints and limitations.
  Anthropic live verification needs an approved backend. Interactive MFA may require
  the operator; browser automation must disclose any use of an existing delegated token.

Agents work on isolated branches/worktrees, read this plan before coding, run their
focused validation, update their assigned progress and commit only owned files.
The parent integrates deliberately and performs the real-cloud checks.
