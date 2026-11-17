# Simplify gateway complexity

Source: complexity review of the Azure Functions and APIM policy code.
Work is sequential in the shared working tree: it already holds uncommitted changes, so separate
worktrees would not contain them, and the phases touch the same files.

Validation per phase: `uv run ruff check .`, `uv run pytest -W error`,
`terraform -chdir=infra fmt -check -recursive`, `terraform -chdir=infra validate`.

## Phase A: publish usage events from Python (APIM findings 4, 5)

- [x] Add `azure-eventhub` settings (`EVENT_HUB_FQDN`, `EVENT_HUB_NAME`) and an async publisher class.
- [x] Publish from `UsageRecorder` as a best-effort background job for streaming and non-streaming requests.
- [x] Remove the relay `_publish` HTTP callback and `APIM_USAGE_EVENT_URL`.
- [x] Terraform: grant the Function identity Event Hubs Data Sender, pass settings to both hosts, remove the APIM logger, internal API and `usage-events` policy.
- [x] Shrink `usage-record` fragment and `ai.xml` on-error to "record unknown usage when admitted".

## Phase B: slim APIM policies (APIM findings 1, 2, 3, 6)

- [x] Put `backend_id` in the policy registry so Terraform owns the hashing rule.
- [x] Parse the request body and the registry entry once.
- [x] Merge the two admission templates into a small shared validation plus per-protocol sections; drop provider-schema duplication. The two templates remain; they now check only fields that affect cost or the input bound.
- [x] Compare the measured body size to the model bound directly.
- [x] Extract the caller-header stripping and simplify identity claims.

## Phase C: streaming parser and relay (Python findings 1, 6)

- [x] Replace `TerminalEventScanner` with gating of oversized terminal events. Gating uses the JSON `"type"` prefix (`response.completed`/`response.incomplete`, Responses only, 1 MiB cap), not `event:` lines.
- [x] Split SSE framing from Chat and Responses semantics.
- [x] Return a small dataclass from the relay and split `_open_upstream`.

## Phase D: typed contexts and layering (Python findings 2, 3, 4, 5)

- [x] `AdmissionContext` and `UsageRecord` pydantic models at the Redis boundary. Only `AdmissionContext` was added: `UsageRecord` keeps its stored shape because reports read the flat fields and replay reads the nested event.
- [x] Move telemetry emission out of `AdmissionService` and `UsageRecorder` bodies.
- [x] Remove the `Engine` pass-through facade. Replaced by `GatewayServices` (`engine/gateway_services.py`), a dataclass of the wired services; callers use `gateway.admission`, `gateway.usage`, `gateway.configuration` and `gateway.reports` directly, and tests were renamed to match. The small helper modules stay: the repo keeps one component per file.
- [ ] Require a model registry in every mode. Kept: local mode without a registry uses host-wide ceilings by design; Azure already requires one.
- [ ] Replace the nested stream-tracing decorator with a span inside the relay. Instead the decorator was split into smaller helpers, because request-level spans must also cover non-streaming failures.

## Deferred with reasons

- `BackgroundWriter` redesign: needs a decision on the downstream Event Hub consumer.
- Removing the legacy-schema handling: depends on whether deployed data still holds the archived schema.
- `Runtime.close_on_loop_shutdown`: the streaming host has no lifespan hook, so the guard stays.
- `validate-content` JSON schema: cannot be verified offline against the live gateway.
