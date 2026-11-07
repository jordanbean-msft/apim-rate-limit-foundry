# Trusted streaming settlement and caller observability

Resolve review items 1 and 3 without changing subscription products or group/tier authorization.
Keep reserve/settle decisions in the Python limiter. Observe provider SSE through a separate
managed-identity-protected Python streaming Function, rather than buffering APIM responses or
trusting client-submitted usage. Strict worst-case admission remains the documented default:
unknown cache hits cannot safely be spent before the provider reports them.

- [x] Parent: add bounded incremental SSE observers for Chat, Responses and Messages, trusted
  stream dispatch and actual settlement. Missing, malformed, truncated or disconnected streams
  must retain conservative liability; no content or credentials in logs.
- [x] Parent: route admitted streaming requests through the dedicated streaming Function, bind
  request bodies to reservations, configure fixed provider backends and managed identity,
  preserve unbuffered delivery and non-streaming behavior.
- [x] Caller agent (isolated worktree): add deterministic caller references to decisions and
  settlements; authorized caller/service/model summaries and Fluent UI identity correlation.
  Readers must remain limited to their own identity. Do not send names or raw identities to logs.
- [x] Parent, after telemetry contracts: add Azure dashboard charts and tables for caller denials
  and costs, stream actual/conservative accounting, cache tokens and reservation refunds.
- [x] Parent: update architecture, operator documentation, packaging and VS Code automation.
- [x] Integrate and validate warning-free Python tests, lint/types, actual incremental stream
  forwarding, portal checks/build, APIM contracts, Terraform formatting/validation/tests and hooks.
  154 Python tests, 73 portal tests, 25 gateway tests, 21 Terraform plans; 22 live KQL schemas;
  actual Functions host indexing/401 and eight rendered Mermaid diagrams verified.
- [x] Deploy only required resources/services, preserving unrelated hosting drift; generate gateway
  traffic and verify persisted Azure dashboard queries, caller joins and cached stream settlement.
  Corrected preview and azd provision: five additions, twelve updates, zero deletions. Separate
  streaming diagnostics avoid changes to existing applications. Both P1v2 plans and existing
  Function Always On=false verified unchanged. All three services deployed successfully.
  Live Chat/Responses streams settle to actual pinned-price usage, including 5,376 cached tokens;
  original immutable Table records prove reservation refunds. Language and Document Intelligence
  calls succeed; temporary cost rules produce custom denials and are removed without changing
  baseline prices/policies. All 22 persisted queries run, all 13 charts populate, and chart/table
  costs, decisions and token totals reconcile. APIM and Function caller references match; 24
  native-probe denials and custom denials join to the real caller. Anonymous relay receives 401.
  The portal is responsive and exposes the authorized caller view. Final Terraform validation
  has zero warnings/errors and all 21 cases pass. Evidence is under .azure/publicdemo/.

Dependencies: stream routing requires trusted observer contracts; charts require caller/stream
telemetry; integration checks and deployment follow implementation. Actual Messages backend
validation remains gated on an approved deployed backend; deterministic protocol fixtures cover it.
Interactive pi/Copilot BYOK acceptance, signed-in Azure portal rendering and an actual Government
deployment remain unverified. A client disconnect may leave the relay consuming valid provider
terminal usage; only genuinely missing/truncated observed usage must retain conservative liability.
