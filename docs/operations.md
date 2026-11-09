# Operations

## Request diagnosis

Start with `X-Correlation-ID`, then join APIM requests and Function events.
Budget denials return limiting budget IDs and UTC reset/retry information.
Distinguish native gateway/provider throttles from monthly dollar-budget denials.
Changing an application key must not reset a user's budget.

## Counter recovery

Table Storage is authoritative. Redis is not a second billing ledger. After
cache loss, call the protected `POST /api/counters/rebuild` as an Admin, then
verify that recorded spend and denials are unchanged. Never reset financial
allowance by deleting Redis keys or creating a new empty projection.

There is no scheduled liability reconciliation or refund operation. Only
finalized actual usage contributes dollars. Unknown usage requires operator
review and is not quietly converted into a free request.

## Event Hub export gaps

APIM uses its native logger with managed identity. Check Sender RBAC,
identity propagation, private DNS/egress, logger configuration and Event Hub
incoming/throttled/error metrics. No Python producer or retry worker exists.

Native logging is best effort. A logger invocation or incoming-message count is
not end-to-end downstream processing confirmation. Compare stable event IDs
against the durable ledger; downstream consumers own checkpoints/deduplication.

## Acceptance checklist

- Require valid Entra user and product key; reject missing/forged identities.
- Use the same user through two application subscriptions and confirm pooled user spend.
- Independently exhaust user, team, department and model-specific monthly budgets.
- Verify no provider call on denial and document concurrent in-flight overshoot.
- Exercise Chat and Responses, both JSON and SSE, including cached input.
- Compare provider terminal totals, durable usage, Event Hub event and chargeback export.
- Interrupt a stream and verify unknown usage is visible rather than zero.
- Simulate recording/export dependency failures without inventing success.
- Rebuild counters and verify no double debit or reopened budget.
- Execute every persisted Azure dashboard query for fresh test traffic.

Local tests do not establish live APIM policy compilation, Government availability,
interactive sign-in, private-network connectivity or financial completeness.
